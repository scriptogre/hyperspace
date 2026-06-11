"""
Live end-to-end echo latency against the running server.

Measures what a user actually feels: time from sending a cursor move to
receiving the broadcast round that reflects it, while N-1 other connections
generate background cursor load. Run the server on :8001 first, then:
    uv run python -m bench.echo_latency
"""

import asyncio
import os
import statistics
import time
import uuid

import websockets

URL = os.environ.get("HS_WS_URL", "ws://127.0.0.1:8001/ws")


def _conn(session_id: str):
    return websockets.connect(
        URL,
        additional_headers={"Cookie": f"hyperspace_id={session_id}"},
        open_timeout=10,
        max_size=None,
    )


async def _drain(ws) -> None:
    """Discard any buffered broadcasts so the next recv reflects our own action."""
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.001)
        except (asyncio.TimeoutError, Exception):
            return


async def _setup_player(ws) -> None:
    """Drain the initial render, then register a name/color so renders are realistic."""
    await ws.recv()
    await ws.send('{"fn":"complete_setup","args":["Bench","Cyan"]}')
    await ws.recv()


async def _seed_bricks(ws, count: int) -> None:
    for i in range(count):
        await ws.send(f'{{"fn":"create_brick","args":[{i % 12},{(i // 12) % 12}]}}')
        await ws.recv()


async def _load(session_id: str, stop: asyncio.Event, connected: list) -> None:
    """Background connection: spam cursor moves until told to stop. Failures are non-fatal."""
    try:
        async with _conn(session_id) as ws:
            await _setup_player(ws)
            connected.append(session_id)
            i = 0
            while not stop.is_set():
                await ws.send(f'{{"fn":"update_cursor","args":[{i % 12},{(i * 5) % 12},0]}}')
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.01)
                except asyncio.TimeoutError:
                    pass
                i += 1
                await asyncio.sleep(0.02)  # ~50 moves/sec, a fast mouse
    except Exception:
        return  # server too saturated to accept/keep this connection


async def _measure(n_load: int, n_samples: int = 80):
    stop = asyncio.Event()
    connected: list = []
    loaders = [asyncio.create_task(_load(f"load-{i}-{uuid.uuid4()}", stop, connected))
               for i in range(n_load)]
    await asyncio.sleep(1.0)  # let loaders connect

    latencies = []
    async with _conn(f"probe-{uuid.uuid4()}") as ws:
        await _setup_player(ws)
        for i in range(n_samples):
            await _drain(ws)  # causal: clear buffered broadcasts first
            t = time.perf_counter()
            await ws.send(f'{{"fn":"update_cursor","args":[{i % 12},{i % 12},0]}}')
            await ws.recv()
            latencies.append((time.perf_counter() - t) * 1000)
            await asyncio.sleep(0.02)

    live = len(connected)
    stop.set()
    await asyncio.gather(*loaders, return_exceptions=True)
    return latencies, live


async def main() -> None:
    # Seed a realistic ~100-brick room from one connection.
    async with _conn(f"seed-{uuid.uuid4()}") as ws:
        await _setup_player(ws)
        await _seed_bricks(ws, 100)
    print("Seeded 100 bricks.\n")

    print(f"{'target users':>13} {'connected':>10}   {'mean':>8} {'p50':>8} {'p99':>8}   room refresh")
    for n_total in (1, 2, 5, 10, 20):
        lat, live = await _measure(n_load=n_total - 1)
        lat.sort()
        mean = statistics.mean(lat)
        p50 = lat[len(lat) // 2]
        p99 = lat[int(len(lat) * 0.99)]
        print(f"{n_total:>13} {live + 1:>10}   {mean:7.1f}ms {p50:7.1f}ms {p99:7.1f}ms   ~{1000 / mean:.0f} Hz")


if __name__ == "__main__":
    asyncio.run(main())
