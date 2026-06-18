"""
Render the fragment whose table changed and fan it out to every client.
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator

import zstandard

from app.dependencies import (
    get_current_bricks,
    get_current_cursors,
    get_latest_events,
    get_current_players,
)
from app.jinja import render
from app.models import Brick, Cursor, Event, Player

TICK = 0.02
SEND_QUEUE_MAX = 64

REGIONS = (
    (Brick, "brick-list", "_brick_list.html", "bricks", get_current_bricks),
    (Player, "player-list", "_player_list.html", "players", get_current_players),
    (Event, "event-list", "_event_list.html", "events", get_latest_events),
    (Cursor, "cursor-list", "_cursor_list.html", "cursors", get_current_cursors),
)

zstd = zstandard.ZstdCompressor(level=3)

sse_clients: dict[str, asyncio.Queue] = {}

_changed: set[str] = set()
_wake = asyncio.Event()


def notify(table: str) -> None:
    _changed.add(table)
    _wake.set()


def frame(element_id: str, html: str) -> bytes:
    """Build one uncompressed <hx-partial> SSE event payload."""
    html = f'<hx-partial id="{element_id}" hx-swap="outerMorph">{html}</hx-partial>'
    body = "".join(f"data: {line}\n" for line in html.split("\n")) + "\n"
    return body.encode()


_KEEPALIVE = b": keepalive\n\n"


async def sse_stream(token: str) -> AsyncIterator[bytes]:
    # TODO: per-connection compression. The browser only decodes one continuous
    # zstd frame, so each stream owns its compressor and recompresses identical
    # broadcasts per client. Restore compress-once (shared bytes, client-side
    # decode) once we find a clean way the browser still decodes natively.
    # A shared zstd dictionary (trained on our fragment HTML) would cut the
    # per-connection cost and shrink frames without giving up native decode.
    cobj = zstd.compressobj()

    def compress(payload: bytes) -> bytes:
        return cobj.compress(payload) + cobj.flush(zstandard.COMPRESSOBJ_FLUSH_BLOCK)

    for _, eid, template, var, provider in REGIONS:
        yield compress(frame(eid, render(template, {var: await provider()})))

    queue: asyncio.Queue = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
    sse_clients[token] = queue
    try:
        while True:
            try:
                payloads = await asyncio.wait_for(queue.get(), timeout=30)
                for payload in payloads:
                    yield compress(payload)
            except asyncio.TimeoutError:
                yield compress(_KEEPALIVE)
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        sse_clients.pop(token, None)


class Profiler:
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
    profiler = Profiler()

    while True:
        await _wake.wait()
        _wake.clear()
        changed = set(_changed)
        _changed.clear()

        started = time.monotonic()
        rendered = []
        for model, eid, template, var, provider in REGIONS:
            if model._meta.db_table in changed:
                rendered.append((eid, render(template, {var: await provider()})))
        built = time.monotonic()

        payloads = [frame(eid, html) for eid, html in rendered]

        for queue in list(sse_clients.values()):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payloads)
        sent = time.monotonic()

        profiler.record(
            build_ms=(built - started) * 1000,
            compress_ms=0.0,  # compression moved per-connection (see sse_stream)
            send_ms=(sent - built) * 1000,
            blob_bytes=sum(len(p) for p in payloads),
            client_count=len(sse_clients),
        )
        await asyncio.sleep(TICK)
