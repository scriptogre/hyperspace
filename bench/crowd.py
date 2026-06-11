"""Load generator: spawn synthetic users against a running server.

Each user connects, completes setup, and parks a cursor. A configurable subset
are "movers" that spam update_cursor (~50/s, like a fast mouse); the rest stay
connected but idle. Work is split across processes so a single GIL-bound
interpreter doesn't cap the load.

    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.crowd 1000 30 400
    # 1000 users for 30s, 400 of them moving

Read capacity from the server's own BCAST line (run it with HS_BCAST_LOG=1):
the n=, total=, send= and rounds/s fields show where the broadcast saturates.
"""

import asyncio
import json
import os
import random
import sys
import uuid
from multiprocessing import Process

import websockets

URL = os.environ.get("HS_WS_URL", "ws://127.0.0.1:8001/ws")
COLORS = ["Cyan", "Pink", "Purple", "Yellow", "Green", "Orange"]
PER_PROC = 250  # clients per worker process


async def client(label: str, duration: float, moves: bool) -> bool:
    sid = f"crowd-{uuid.uuid4().hex[:10]}"
    try:
        ws = await websockets.connect(
            URL, additional_headers={"Cookie": f"hyperspace_id={sid}"},
            max_size=None, compression=None, open_timeout=15,
        )
        await ws.recv()  # initial stage frame
        await ws.recv()  # initial cursors frame
        await ws.send(json.dumps({"fn": "complete_setup", "args": [label, random.choice(COLORS)]}))
    except Exception:
        return False

    async def drain():
        try:
            while True:
                await ws.recv()  # discard broadcasts; keep harness CPU low
        except Exception:
            pass

    drain_task = asyncio.create_task(drain())
    x, y = random.randint(0, 10), random.randint(0, 10)
    loop = asyncio.get_event_loop()
    try:
        await ws.send(json.dumps({"fn": "update_cursor", "args": [x, y, 0]}))  # park one cursor
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


async def run_chunk(count: int, movers: int, duration: float, pid: int) -> None:
    tasks = []
    for i in range(count):
        tasks.append(asyncio.create_task(client(f"C{pid}-{i}", duration, i < movers)))
        if i % 25 == 0:
            await asyncio.sleep(0.05)  # stagger connects so the accept queue keeps up
    results = await asyncio.gather(*tasks, return_exceptions=True)
    connected = sum(1 for r in results if r is True)
    print(f"  proc {pid}: {connected}/{count} connected", flush=True)


def worker(count: int, movers: int, duration: float, pid: int) -> None:
    asyncio.run(run_chunk(count, movers, duration, pid))


def _split(total: int, parts: int) -> list[int]:
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def main() -> None:
    total = int(sys.argv[1])
    duration = float(sys.argv[2])
    movers = int(sys.argv[3]) if len(sys.argv) > 3 else total

    nproc = max(1, -(-total // PER_PROC))
    counts = _split(total, nproc)
    mover_counts = _split(movers, nproc)

    print(f"{total} users ({movers} moving) across {nproc} processes for {duration:.0f}s -> {URL}", flush=True)
    procs = [Process(target=worker, args=(counts[i], mover_counts[i], duration, i)) for i in range(nproc)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
