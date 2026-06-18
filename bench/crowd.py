"""Load generator: spawn synthetic users against a running server.

Each user connects, completes setup, and parks a cursor. Roles:
  movers  spam update_cursor (~50/s, like a fast mouse)
  slow    stay connected but read broadcasts slowly (a phone on a bad link),
          which fills the server's send buffer and exposes backpressure
  idle    connected, reading fast, not moving

Work is split across processes so a single GIL-bound interpreter doesn't cap it.

    uv run --with httpx python -m bench.crowd 1000 30 400 50
    # 1000 users for 30s: 400 moving, 50 slow readers, rest idle

    HS_TRANSPORT=sse uv run --with httpx python -m bench.crowd 1000 30 400 50
    # Same workload over SSE+POST instead of WebSocket

Read capacity from the server's BCAST line (run it with HS_BCAST_LOG=1): when
slow readers are present, watch `send` and `total` climb.
"""

import asyncio
import json
import os
import random
import sys
import urllib.parse
import urllib.request
import uuid
from multiprocessing import Process

import websockets

WS_URL = os.environ.get("HS_WS_URL", "ws://127.0.0.1:8001/ws")
_default_base = (
    WS_URL.replace("wss://", "https://").replace("ws://", "http://").rsplit("/", 1)[0]
)
BASE_URL = os.environ.get("HS_BASE_URL", _default_base)
TRANSPORT = os.environ.get("HS_TRANSPORT", "ws").lower()
HTTP2 = os.environ.get("HS_HTTP2", "") == "1"
SLOW_READ = float(os.environ.get("HS_SLOW_READ", "0.25"))
COLORS = ["cyan", "pink", "purple", "yellow", "green", "orange"]
PER_PROC = 250


# ---------------------------------------------------------------------------
# Setup helper (sync HTTP, no external deps beyond stdlib)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _create_player(session_id, name="Bench"):
    data = urllib.parse.urlencode(
        {
            "name": name,
            "color": random.choice(COLORS),
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/join",
        data=data,
        headers={
            "Cookie": f"hyperspace_id={session_id}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        _opener.open(req, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# WS client
# ---------------------------------------------------------------------------


async def ws_client(sid, duration, moves, slow):
    try:
        ws = await websockets.connect(
            WS_URL,
            additional_headers={"Cookie": f"hyperspace_id={sid}"},
            max_size=None,
            compression=None,
            open_timeout=15,
            max_queue=8 if slow else 32,
        )
    except Exception:
        return False

    # Drain initial state (bricks, players, events, cursors)
    for _ in range(4):
        try:
            await asyncio.wait_for(ws.recv(), timeout=5)
        except Exception:
            break

    async def drain():
        try:
            while True:
                await ws.recv()
                if slow:
                    await asyncio.sleep(SLOW_READ)
        except Exception:
            pass

    drain_task = asyncio.create_task(drain())
    x, y = random.randint(0, 10), random.randint(0, 10)
    loop = asyncio.get_event_loop()
    try:
        await ws.send(json.dumps({"fn": "update_cursor", "args": [x, y, 0]}))
        end = loop.time() + duration
        while loop.time() < end:
            if not moves:
                await asyncio.sleep(0.25)
                continue
            x = max(0, min(10, x + random.choice([-1, 0, 1])))
            y = max(0, min(10, y + random.choice([-1, 0, 1])))
            await ws.send(json.dumps({"fn": "update_cursor", "args": [x, y, 0]}))
            await asyncio.sleep(random.uniform(0.05, 0.09))
    except Exception:
        pass
    finally:
        drain_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass
    return True


# ---------------------------------------------------------------------------
# SSE+POST client
# ---------------------------------------------------------------------------


async def sse_client(sid, duration, moves, slow, http_client, post_errors):
    cookies = {"hyperspace_id": sid}
    reader_done = asyncio.Event()

    async def reader():
        try:
            async with http_client.stream("GET", "/sse", cookies=cookies) as r:
                buf = ""
                async for chunk in r.aiter_text():
                    if reader_done.is_set():
                        return
                    buf += chunk
                    while "\n\n" in buf:
                        _, buf = buf.split("\n\n", 1)
                        if slow:
                            await asyncio.sleep(SLOW_READ)
        except Exception:
            pass

    def _on_done(t):
        pending.discard(t)
        if not t.cancelled() and t.exception():
            post_errors.append(1)

    reader_task = asyncio.create_task(reader())
    x, y = random.randint(0, 10), random.randint(0, 10)
    loop = asyncio.get_event_loop()

    # Fire-and-forget POSTs to match ws.send() semantics
    pending = set()
    try:
        t = asyncio.create_task(
            http_client.post(
                "/action",
                json={"fn": "update_cursor", "args": [x, y, 0]},
                cookies=cookies,
            )
        )
        pending.add(t)
        t.add_done_callback(_on_done)

        end = loop.time() + duration
        while loop.time() < end:
            if not moves:
                await asyncio.sleep(0.25)
                continue
            x = max(0, min(10, x + random.choice([-1, 0, 1])))
            y = max(0, min(10, y + random.choice([-1, 0, 1])))
            t = asyncio.create_task(
                http_client.post(
                    "/action",
                    json={"fn": "update_cursor", "args": [x, y, 0]},
                    cookies=cookies,
                )
            )
            pending.add(t)
            t.add_done_callback(_on_done)
            await asyncio.sleep(random.uniform(0.05, 0.09))
    except Exception:
        pass
    finally:
        reader_done.set()
        reader_task.cancel()
        for t in pending:
            t.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass
    return True


# ---------------------------------------------------------------------------
# Process workers
# ---------------------------------------------------------------------------


async def run_chunk(sessions, duration, pid):
    if TRANSPORT == "sse":
        import httpx

        max_conn = len(sessions) * 2 + 10
        limits = httpx.Limits(
            max_connections=max_conn,
            max_keepalive_connections=max_conn,
        )
        post_errors = []
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            verify=False,
            http2=HTTP2,
            timeout=duration + 60,
            limits=limits,
        ) as client:
            tasks = []
            for i, (sid, moves, slow) in enumerate(sessions):
                tasks.append(
                    asyncio.create_task(
                        sse_client(sid, duration, moves, slow, client, post_errors)
                    )
                )
                if i % 25 == 0:
                    await asyncio.sleep(0.05)
            results = await asyncio.gather(*tasks, return_exceptions=True)

        connected = sum(1 for r in results if r is True)
        errs = len(post_errors)
        err_str = f"  post_errors={errs}" if errs else ""
        print(
            f"  proc {pid}: {connected}/{len(sessions)} connected{err_str}", flush=True
        )
    else:
        tasks = []
        for i, (sid, moves, slow) in enumerate(sessions):
            tasks.append(asyncio.create_task(ws_client(sid, duration, moves, slow)))
            if i % 25 == 0:
                await asyncio.sleep(0.05)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        connected = sum(1 for r in results if r is True)
        print(f"  proc {pid}: {connected}/{len(sessions)} connected", flush=True)


def worker(sessions_spec, duration, pid):
    """Create players (sync), then run the async crowd."""
    sessions = []
    for sid, label, moves, slow in sessions_spec:
        _create_player(sid, label)
        sessions.append((sid, moves, slow))
    asyncio.run(run_chunk(sessions, duration, pid))


def _split(total, parts):
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def main():
    total = int(sys.argv[1])
    duration = float(sys.argv[2])
    movers = int(sys.argv[3]) if len(sys.argv) > 3 else total
    slow = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    nproc = max(1, -(-total // PER_PROC))
    counts = _split(total, nproc)
    mover_counts = _split(movers, nproc)
    slow_counts = _split(slow, nproc)

    # Build session specs per process
    all_specs = []
    for pid in range(nproc):
        specs = []
        for i in range(counts[pid]):
            sid = f"crowd-{uuid.uuid4().hex[:10]}"
            is_mover = i < mover_counts[pid]
            is_slow = mover_counts[pid] <= i < mover_counts[pid] + slow_counts[pid]
            specs.append((sid, f"C{pid}-{i}", is_mover, is_slow))
        all_specs.append(specs)

    transport_label = (
        f"SSE+POST {'H2' if HTTP2 else 'H1'}" if TRANSPORT == "sse" else "WS"
    )
    print(
        f"{total} users ({movers} moving, {slow} slow) × {nproc} procs"
        f" for {duration:.0f}s  [{transport_label}]  -> {BASE_URL if TRANSPORT == 'sse' else WS_URL}",
        flush=True,
    )
    procs = [
        Process(target=worker, args=(all_specs[i], duration, i)) for i in range(nproc)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
