"""
Decompose the per-broadcast server cost into stages.

A single mutation triggers, for every connected client:
    world_context()  ->  render(#grid)  ->  send_text()

This script seeds a realistic busy room, then times each stage in isolation
so we can see where the time actually goes. Run: uv run python -m bench.profile_broadcast
"""

import asyncio
import statistics
import time
from pathlib import Path

from tortoise import Tortoise

from app import services
from app.fasthtml import Jinja2Templates
from app.models import Brick, Cursor, Event, User

# Realistic busy room.
N_USERS = 10
N_BRICKS = 100
N_EVENTS = 40
ITERATIONS = 300

_templates = Jinja2Templates(str(Path(__file__).parent.parent / "templates"))


async def _seed() -> str:
    """Populate a busy room and return one session_id to render for."""
    colors = ["Cyan", "Purple", "Orange", "Green", "Pink", "Yellow"]
    session_ids = [f"user-{i}" for i in range(N_USERS)]

    for i, sid in enumerate(session_ids):
        await User.create(identity=sid, name=f"Player{i}", color=colors[i % 6], online=True)
        await Cursor.create(identity=sid, x=i % 12, y=(i * 2) % 12, z=0)

    for i in range(N_BRICKS):
        await Brick.create(x=i % 12, y=(i // 12) % 12, z=i % 5, color=colors[i % 6])

    for i in range(N_EVENTS):
        await Event.create(kind="BrickCreated", identity=session_ids[i % N_USERS])

    return session_ids[0]


def _stats(samples: list[float]) -> str:
    """Format a list of millisecond timings as mean / p50 / p99."""
    samples = sorted(samples)
    mean = statistics.mean(samples)
    p50 = samples[len(samples) // 2]
    p99 = samples[int(len(samples) * 0.99)]
    return f"mean {mean:6.2f}ms   p50 {p50:6.2f}ms   p99 {p99:6.2f}ms"


async def main() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["app.models"]})
    await Tortoise.generate_schemas()

    session_id = await _seed()

    # Warm up: first render compiles the template, first queries prime caches.
    ctx = {**(await services.world_state()), "current_session_id": session_id, "show_player_setup": False}
    html = await _templates.render("index.html.j2#grid", ctx)
    html_kb = len(html.encode()) / 1024

    queries, context, rendering, full = [], [], [], []

    for _ in range(ITERATIONS):
        # Stage 1a: raw DB queries (4 SELECTs in parallel).
        t = time.perf_counter()
        await asyncio.gather(
            Brick.all().order_by("id"),
            User.all().order_by("name"),
            Cursor.all().order_by("identity"),
            Event.all().order_by("id"),
        )
        queries.append((time.perf_counter() - t) * 1000)

        # Stage 1: world_context (queries + Python dict building).
        t = time.perf_counter()
        ctx = {**(await services.world_state()), "current_session_id": session_id, "show_player_setup": False}
        context.append((time.perf_counter() - t) * 1000)

        # Stage 2: Jinja render of the #grid block.
        t = time.perf_counter()
        await _templates.render("index.html.j2#grid", ctx)
        rendering.append((time.perf_counter() - t) * 1000)

        # Full per-client server cost (context + render, no socket).
        t = time.perf_counter()
        ctx = {**(await services.world_state()), "current_session_id": session_id, "show_player_setup": False}
        await _templates.render("index.html.j2#grid", ctx)
        full.append((time.perf_counter() - t) * 1000)

    print(f"\nRoom: {N_USERS} users, {N_BRICKS} bricks, {N_EVENTS} events")
    print(f"Rendered HTML size: {html_kb:.1f} KB\n")
    print(f"  DB queries (4x)     {_stats(queries)}")
    print(f"  world_context       {_stats(context)}")
    print(f"  Jinja render        {_stats(rendering)}")
    print(f"  --------------------")
    print(f"  per-client total    {_stats(full)}")

    per_client_ms = statistics.mean(full)
    print(f"\nPer-client server cost: {per_client_ms:.2f}ms")
    print(f"One worker can serve ~{1000 / per_client_ms:.0f} client-renders/sec")
    print(f"With N clients each moving the cursor, broadcasts/sec needed = N x N (fanout).")
    for n in (5, 10, 20, 50):
        renders_needed = n * n  # n movers x n recipients
        capacity = 1000 / per_client_ms
        print(f"  N={n:3d}:  {renders_needed:5d} renders/sec needed,  capacity {capacity:.0f}/sec"
              f"  ->  {'OK' if renders_needed < capacity else 'SATURATED'}")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
