"""Load generator: spawn synthetic users against a running server.

Each user connects, completes setup, and parks a cursor. Roles:
  movers  spam update_cursor (~50/s, like a fast mouse)
  slow    stay connected but read broadcasts slowly (a phone on a bad link),
          which fills the server's send buffer and exposes the sequential-send
          backpressure that a loopback test otherwise hides
  idle    connected, reading fast, not moving

Work is split across processes so a single GIL-bound interpreter doesn't cap it.

    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.crowd 1000 30 400 50
    # 1000 users for 30s: 400 moving, 50 slow readers, rest idle

Read capacity from the server's BCAST line (run it with HS_BCAST_LOG=1): when
slow readers are present, watch `send` and `total` climb.
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
SLOW_READ = float(
    os.environ.get("HS_SLOW_READ", "0.25")
)  # seconds between reads for slow clients
COLORS = ["Cyan", "Pink", "Purple", "Yellow", "Green", "Orange"]
PER_PROC = 250  # clients per worker process


async def client(label: str, duration: float, moves: bool, slow: bool) -> bool:
    sid = f"crowd-{uuid.uuid4().hex[:10]}"
    try:
        ws = await websockets.connect(
            URL,
            additional_headers={"Cookie": f"hyperspace_id={sid}"},
            max_size=None,
            compression=None,
            open_timeout=15,
            # Small inbound queue so a slow reader applies TCP backpressure to the
            # server instead of buffering everything in the client.
            max_queue=8 if slow else 32,
        )
        await ws.recv()  # initial stage frame
        await ws.recv()  # initial cursors frame
        await ws.send(
            json.dumps({"fn": "join", "args": [label, random.choice(COLORS)]})
        )
    except Exception:
        return False

    async def drain():
        try:
            while True:
                await ws.recv()
                if slow:
                    await asyncio.sleep(SLOW_READ)  # read the feed slowly
        except Exception:
            pass

    drain_task = asyncio.create_task(drain())
    x, y = random.randint(0, 10), random.randint(0, 10)
    loop = asyncio.get_event_loop()
    try:
        await ws.send(
            json.dumps({"fn": "update_cursor", "args": [x, y, 0]})
        )  # park one cursor
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


async def run_chunk(
    count: int, movers: int, slow: int, duration: float, pid: int
) -> None:
    tasks = []
    for i in range(count):
        is_mover = i < movers
        is_slow = movers <= i < movers + slow
        tasks.append(
            asyncio.create_task(client(f"C{pid}-{i}", duration, is_mover, is_slow))
        )
        if i % 25 == 0:
            await asyncio.sleep(0.05)  # stagger connects so the accept queue keeps up
    results = await asyncio.gather(*tasks, return_exceptions=True)
    connected = sum(1 for r in results if r is True)
    print(f"  proc {pid}: {connected}/{count} connected", flush=True)


def worker(count: int, movers: int, slow: int, duration: float, pid: int) -> None:
    asyncio.run(run_chunk(count, movers, slow, duration, pid))


def _split(total: int, parts: int) -> list[int]:
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def main() -> None:
    total = int(sys.argv[1])
    duration = float(sys.argv[2])
    movers = int(sys.argv[3]) if len(sys.argv) > 3 else total
    slow = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    nproc = max(1, -(-total // PER_PROC))
    counts = _split(total, nproc)
    mover_counts = _split(movers, nproc)
    slow_counts = _split(slow, nproc)

    print(
        f"{total} users ({movers} moving, {slow} slow) across {nproc} processes for {duration:.0f}s -> {URL}",
        flush=True,
    )
    procs = [
        Process(
            target=worker,
            args=(counts[i], mover_counts[i], slow_counts[i], duration, i),
        )
        for i in range(nproc)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
