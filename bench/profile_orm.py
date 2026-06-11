"""
Isolate the costs SpacetimeDB replaces with native in-memory operations:
the ORM tax (Tortoise vs raw aiosqlite), the mutation path, and pure render.

Run: uv run python -m bench.profile_orm
"""

import asyncio
import statistics
import time
from pathlib import Path

import aiosqlite
from tortoise import Tortoise
from tortoise.connection import connections

from app import services
from app.fasthtml import Jinja2Templates
from app.models import Brick, Cursor, Event, User

N_USERS = 10
N_BRICKS = 100
N_EVENTS = 40
ITERATIONS = 300

_templates = Jinja2Templates(str(Path(__file__).parent.parent / "templates"))


async def _seed() -> str:
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
    samples = sorted(samples)
    return (f"mean {statistics.mean(samples):6.3f}ms   "
            f"p50 {samples[len(samples) // 2]:6.3f}ms   "
            f"p99 {samples[int(len(samples) * 0.99)]:6.3f}ms")


async def _time(fn, n=ITERATIONS) -> list[float]:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        await fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


async def main() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["app.models"]})
    await Tortoise.generate_schemas()
    session_id = await _seed()

    # Raw aiosqlite handle on the SAME in-memory DB Tortoise is using.
    conn = connections.get("default")
    raw: aiosqlite.Connection = conn._connection

    async def raw_query_bricks():
        cur = await raw.execute("SELECT id, x, y, z, color, dragged_by FROM brick ORDER BY id")
        await cur.fetchall()

    async def orm_query_bricks():
        await Brick.all().order_by("id")

    async def pre_built_render(ctx):
        await _templates.render("index.html.j2#grid", ctx)

    ctx = {**(await services.world_state()), "current_session_id": session_id, "show_player_setup": False}

    raw_q = await _time(raw_query_bricks)
    orm_q = await _time(orm_query_bricks)
    mutation = await _time(lambda: services.update_cursor(session_id, 5, 5, 0))
    render = await _time(lambda: pre_built_render(ctx))

    print(f"\nRoom: {N_USERS} users, {N_BRICKS} bricks, {N_EVENTS} events\n")
    print("Query the 100 bricks:")
    print(f"  raw aiosqlite       {_stats(raw_q)}")
    print(f"  Tortoise ORM        {_stats(orm_q)}")
    orm_tax = statistics.mean(orm_q) / statistics.mean(raw_q)
    print(f"  ORM tax: {orm_tax:.1f}x slower (SQL build + row -> Python model objects)\n")

    print("Mutation (update_cursor = 1 SELECT + 1 UPDATE through ORM):")
    print(f"  {_stats(mutation)}\n")

    print("Pure Jinja render (context pre-built, no DB):")
    print(f"  {_stats(render)}")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
