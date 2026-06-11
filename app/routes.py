"""HTTP and WebSocket routes."""

import asyncio
import json
import os
import time

import zstandard
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app import services
from app.dependencies import COOKIE_NAME, get_session_id
from app.jinja import render

# Each broadcast region is compressed once with zstd, then the identical bytes
# fan out to every client (the browser decodes with fzstd). Permessage-deflate
# must be off so frames aren't compressed a second time per connection.
_ZSTD = zstandard.ZstdCompressor(level=3)

PAGE = "index.html.j2"
STAGE = "_stage.html.j2"
CURSORS = "_cursors.html.j2"
CURSOR_FRAGMENTS = "_cursor_fragments.html.j2"

# Tables whose changes affect the structural region (everything but cursors).
_STRUCTURAL = {"brick", "user", "event"}

# Minimum gap between broadcasts. Isolated events render immediately; a burst
# coalesces into the next render after this gap, capping broadcasts at 1/TICK.
TICK = 0.02

router = APIRouter()

# A slow client may fall this many frames behind before the broadcast loop drops
# its oldest. Bounds how far one bad link can lag without stalling everyone.
SEND_QUEUE_MAX = 64

# session_id -> per-client send queue. A background writer drains each one, so a
# slow socket backs up only its own queue, never the broadcast loop.
connections: dict[str, asyncio.Queue] = {}

# Set by the Postgres listener (one table name per change) to wake the loop.
_dirty = asyncio.Event()
_dirty_tables: set[str] = set()


def mark_dirty(table: str) -> None:
    """Record a changed table and wake the broadcast loop. Called from the PG listener."""
    _dirty_tables.add(table)
    _dirty.set()


_BCAST_LOG = os.environ.get("HS_BCAST_LOG") == "1"


async def broadcast_loop() -> None:
    """Send only what changed: a cursor delta from Postgres, plus the stage region."""
    cursor_wm = await services.max_cursor_version()
    win = time.monotonic()
    rounds = 0
    build_ms = compress_ms = send_ms = 0.0
    region_bytes = 0

    while True:
        await _dirty.wait()
        _dirty.clear()
        tables = set(_dirty_tables)
        _dirty_tables.clear()

        t0 = time.monotonic()
        if "user" in tables:
            await services.load_players()
        regions = []
        if "cursor" in tables:
            delta, cursor_wm = await services.cursor_delta(cursor_wm)
            if delta:
                regions.append(render(CURSOR_FRAGMENTS, {"cursors": delta, "grid_size": services.GRID_SIZE}))
        if tables & _STRUCTURAL:
            regions.append(render(STAGE, await services.stage_state()))
        t2 = time.monotonic()
        blobs = [_ZSTD.compress(r.encode()) for r in regions]  # compress once
        t2b = time.monotonic()

        for queue in list(connections.values()):
            if queue.full():
                try:
                    queue.get_nowait()  # drop this slow client's oldest frame
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(blobs)
        t3 = time.monotonic()

        if _BCAST_LOG:
            rounds += 1
            build_ms += (t2 - t0) * 1000
            compress_ms += (t2b - t2) * 1000
            send_ms += (t3 - t2b) * 1000
            region_bytes = sum(len(b) for b in blobs)
            if t3 - win >= 1.0:
                print(
                    f"BCAST n={len(connections)} rounds/s={rounds} build={build_ms / rounds:.1f} "
                    f"compress={compress_ms / rounds:.1f} send={send_ms / rounds:.1f} "
                    f"total={(build_ms + compress_ms + send_ms) / rounds:.1f} blob_bytes={region_bytes}",
                    flush=True,
                )
                win = t3
                rounds = 0
                build_ms = compress_ms = send_ms = 0.0

        await asyncio.sleep(TICK)


@router.get("/")
async def index(session_id: str = Depends(get_session_id)):
    state = await services.page_state()
    return render(PAGE, state | {
        "current_session_id": session_id,
        "show_player_setup": session_id not in services.known_ids(),
    })


@router.get("/health")
async def health() -> str:
    """Liveness probe for the container healthcheck."""
    return "ok"


async def _client_writer(session_id: str, websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Drain one client's queue to its socket. A slow socket backs up only this
    task; the broadcast loop keeps going."""
    try:
        while True:
            blobs = await queue.get()
            for blob in blobs:
                await websocket.send_bytes(blob)
    except Exception:
        connections.pop(session_id, None)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    session_id = websocket.cookies.get(COOKIE_NAME)
    if not session_id:
        await websocket.close(code=4001)
        return

    # Send the full initial state before registering for broadcasts, so the first
    # frame a client sees is the whole stage, never a delta morphed onto nothing.
    await services.on_connect(session_id)
    await websocket.send_bytes(_ZSTD.compress(render(STAGE, await services.stage_state()).encode()))
    await websocket.send_bytes(_ZSTD.compress(render(CURSORS, await services.cursor_state()).encode()))

    queue: asyncio.Queue = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
    connections[session_id] = queue
    writer = asyncio.create_task(_client_writer(session_id, websocket, queue))

    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            await _dispatch(session_id, msg["fn"], msg.get("args", []))

    except WebSocketDisconnect:
        pass
    finally:
        connections.pop(session_id, None)
        writer.cancel()
        await services.on_disconnect(session_id)


async def _dispatch(session_id: str, fn: str, args: list) -> None:
    """Route an incoming WebSocket message to the appropriate service function."""
    match fn:
        case "complete_setup":
            await services.complete_setup(session_id, str(args[0]), str(args[1]))
        case "create_brick":
            await services.create_brick(session_id, int(args[0]), int(args[1]))
        case "delete_brick":
            await services.delete_brick(session_id, int(args[0]))
        case "set_name":
            await services.set_name(session_id, str(args[0]))
        case "set_color":
            await services.set_color(session_id, str(args[0]))
        case "update_cursor":
            await services.update_cursor(session_id, int(args[0]), int(args[1]), int(args[2]))
        case "start_drag":
            await services.start_drag(session_id, int(args[0]))
        case "end_drag":
            await services.end_drag(session_id)
        case "move_brick":
            await services.move_brick(session_id, int(args[0]), int(args[1]), int(args[2]))
