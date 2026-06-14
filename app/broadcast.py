"""Realtime broadcast pump: render the fragment whose table changed, fan it out.

A Postgres trigger NOTIFYs on every write; the lifespan listener forwards the
table name to `notify`, which wakes `run`. Each structural table maps to one
fragment (see REGIONS); cursors broadcast a delta instead of a full re-render.
Each client has its own writer draining its own queue, so one slow socket can
never stall the loop.
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import zstandard
from fastapi import WebSocket

from app import services
from app.dependencies import (
    get_current_bricks,
    get_current_cursors,
    get_current_events,
    get_current_players,
)
from app.jinja import render
from app.models import Brick, Cursor, Event, Player

TICK = 0.02
SEND_QUEUE_MAX = 64

# A write to each table re-renders one fragment: (model, template, template var, provider).
REGIONS = (
    (Brick, "_brick_list.html", "bricks", get_current_bricks),
    (Player, "_player_list.html", "players", get_current_players),
    (Event, "_event_list.html", "events", get_current_events),
)

_ZSTD = zstandard.ZstdCompressor(level=3)

# session_key -> send queue, drained by that client's writer task.
clients: dict[str, asyncio.Queue] = {}

# Tables changed since the last render, plus the event that wakes the loop.
_changed: set[str] = set()
_wake = asyncio.Event()


def notify(table: str) -> None:
    """Record a changed table and wake the loop. Called by the Postgres listener."""
    _changed.add(table)
    _wake.set()


def compress(html: str) -> bytes:
    """Compress one fragment of HTML into a single WebSocket frame."""
    return _ZSTD.compress(html.encode())


@asynccontextmanager
async def client(session_key: str, websocket: WebSocket) -> AsyncIterator[None]:
    """Serve one client for the duration of the `with` block.

    Sends the full current state, then joins the fan-out: a background writer
    drains this client's queue to its socket until the block exits.
    """
    for template, var, provider in (
        ("_brick_list.html", "bricks", get_current_bricks),
        ("_player_list.html", "players", get_current_players),
        ("_event_list.html", "events", get_current_events),
        ("_cursor_list.html", "cursors", get_current_cursors),
    ):
        await websocket.send_bytes(compress(render(template, {var: await provider()})))

    queue: asyncio.Queue = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
    clients[session_key] = queue

    async def drain() -> None:
        try:
            while True:
                for blob in await queue.get():
                    await websocket.send_bytes(blob)
        except Exception:
            clients.pop(session_key, None)

    writer = asyncio.create_task(drain())
    try:
        yield
    finally:
        clients.pop(session_key, None)
        writer.cancel()


async def cursor_delta(after: int) -> tuple[list[dict], int]:
    """Cursors changed since version `after`, plus the new high-water mark."""
    rows = (
        await Cursor.filter(version__gt=after)
        .order_by("version")
        .values(
            "player__session_key",
            "player__name",
            "player__color",
            "x",
            "y",
            "z",
            "is_active",
            "version",
        )
    )
    cursors = [
        {
            "session_key": row["player__session_key"],
            "grid_x": row["x"],
            "grid_y": row["y"],
            "grid_z": row["z"],
            "is_active": row["is_active"],
            "name": row["player__name"],
            "color": row["player__color"],
        }
        for row in rows
    ]
    watermark = rows[-1]["version"] if rows else after
    return cursors, watermark


async def max_cursor_version() -> int:
    rows = (
        await Cursor.all()
        .order_by("-version")
        .limit(1)
        .values_list("version", flat=True)
    )
    return rows[0] if rows else 0


class Profiler:
    """One `BCAST` stats line per second when HS_BCAST_LOG=1.

    The load harness (bench/crowd.py) reads server capacity from this line, so
    its format is a contract. A no-op when the env var is unset.
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get("HS_BCAST_LOG") == "1"
        self.window_start = time.monotonic()
        self.rounds = 0
        self.build_ms = 0.0
        self.compress_ms = 0.0
        self.send_ms = 0.0
        self.blob_bytes = 0

    def record(
        self,
        build_ms: float,
        compress_ms: float,
        send_ms: float,
        blob_bytes: int,
        client_count: int,
    ) -> None:
        if not self.enabled:
            return

        self.rounds += 1
        self.build_ms += build_ms
        self.compress_ms += compress_ms
        self.send_ms += send_ms
        self.blob_bytes = blob_bytes

        now = time.monotonic()
        if now - self.window_start < 1.0:
            return

        rounds = self.rounds
        print(
            f"BCAST n={client_count} rounds/s={rounds} build={self.build_ms / rounds:.1f} "
            f"compress={self.compress_ms / rounds:.1f} send={self.send_ms / rounds:.1f} "
            f"total={(self.build_ms + self.compress_ms + self.send_ms) / rounds:.1f} "
            f"blob_bytes={self.blob_bytes}",
            flush=True,
        )
        self.window_start = now
        self.rounds = 0
        self.build_ms = self.compress_ms = self.send_ms = 0.0


async def run() -> None:
    """Render and fan out changed fragments until cancelled."""
    cursor_version = await max_cursor_version()
    profiler = Profiler()

    while True:
        await _wake.wait()
        _wake.clear()
        changed = set(_changed)
        _changed.clear()

        started = time.monotonic()
        if "player" in changed:
            await services.load_players()

        htmls = []
        if "cursor" in changed:
            delta, cursor_version = await cursor_delta(cursor_version)
            if delta:
                htmls.append(render("_cursor_list.html", {"cursors": delta}))
        for model, template, var, provider in REGIONS:
            if model._meta.db_table in changed:
                htmls.append(render(template, {var: await provider()}))
        built = time.monotonic()

        blobs = [compress(html) for html in htmls]
        compressed = time.monotonic()

        for queue in list(clients.values()):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(blobs)
        sent = time.monotonic()

        profiler.record(
            build_ms=(built - started) * 1000,
            compress_ms=(compressed - built) * 1000,
            send_ms=(sent - compressed) * 1000,
            blob_bytes=sum(len(blob) for blob in blobs),
            client_count=len(clients),
        )
        await asyncio.sleep(TICK)
