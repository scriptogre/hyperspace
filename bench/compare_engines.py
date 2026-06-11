"""
Render speed across engines on the same grid template + context:
Jinja2 (sync), Jinja2 (async), minijinja (Rust), and hyper.

All render templates/_grid.html (the grid block extracted as a standalone
template) so the comparison is apples-to-apples. hyper renders its equivalent
@html component from bench.compare_render. Output sizes are printed so any
divergence is visible.

Run: uv run python -m bench.compare_engines
"""

import asyncio
import statistics
import time
from pathlib import Path

import minijinja
from jinja2 import Environment, FileSystemLoader, select_autoescape
from tortoise import Tortoise

from app import services
from app.models import Brick, Cursor, Event, User
from bench.compare_render import Grid  # the hyper component

N_USERS = 10
N_BRICKS = 100
N_EVENTS = 40
ITERATIONS = 300
TEMPLATE = "_grid.html.j2"
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Jinja2, sync and async, autoescape on (matches the app's config).
_jinja_sync = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)
_jinja_async = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    enable_async=True,
)

# minijinja, forced autoescape so output matches Jinja2.
_minijinja = minijinja.Environment(
    loader=lambda name: (_TEMPLATES_DIR / name).read_text(),
    auto_escape_callback=lambda name: True,
)


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


async def main() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["app.models"]})
    await Tortoise.generate_schemas()
    session_id = await _seed()
    ctx = {**(await services.world_state()), "current_session_id": session_id, "show_player_setup": False}

    jinja_tmpl = _jinja_sync.get_template(TEMPLATE)
    jinja_async_tmpl = _jinja_async.get_template(TEMPLATE)

    sizes = {
        "jinja2-sync": len(jinja_tmpl.render(**ctx)),
        "jinja2-async": len(await jinja_async_tmpl.render_async(**ctx)),
        "minijinja": len(_minijinja.render_template(TEMPLATE, **ctx)),
        "hyper": len(Grid(**ctx)),
    }
    print(f"\nRoom: {N_USERS} users, {N_BRICKS} bricks, {N_EVENTS} events")
    for name, size in sizes.items():
        print(f"  size  {name:14s} {size / 1024:6.1f} KB")
    print()

    results: dict[str, list[float]] = {k: [] for k in ("jinja2-sync", "jinja2-async", "minijinja", "hyper")}
    for _ in range(ITERATIONS):
        t = time.perf_counter(); jinja_tmpl.render(**ctx)
        results["jinja2-sync"].append((time.perf_counter() - t) * 1000)

        t = time.perf_counter(); await jinja_async_tmpl.render_async(**ctx)
        results["jinja2-async"].append((time.perf_counter() - t) * 1000)

        t = time.perf_counter(); _minijinja.render_template(TEMPLATE, **ctx)
        results["minijinja"].append((time.perf_counter() - t) * 1000)

        t = time.perf_counter(); Grid(**ctx)
        results["hyper"].append((time.perf_counter() - t) * 1000)

    baseline = statistics.mean(results["jinja2-sync"])
    for name in ("jinja2-sync", "jinja2-async", "minijinja", "hyper"):
        mean = statistics.mean(results[name])
        rel = baseline / mean
        print(f"  {name:14s} {_stats(results[name])}   {rel:4.1f}x vs jinja2-sync")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
