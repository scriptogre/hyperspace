"""
Head-to-head render speed: Jinja2 (#grid block) vs a hyper component.

Both produce the same grid HTML from the same context. The hyper component is
written in the exact shape the hyper transpiler emits: a generator yielding
f-strings, with escape() on every interpolated value, joined by @html. We report
output size for both so any difference is visible, then time each over N renders.

Run: uv run python -m bench.compare_render
"""

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/chris/Projects/hyper/python")
from hyper import html, escape  # noqa: E402

from tortoise import Tortoise  # noqa: E402

from app import services  # noqa: E402
from app.fasthtml import Jinja2Templates  # noqa: E402
from app.models import Brick, Cursor, Event, User  # noqa: E402

N_USERS = 10
N_BRICKS = 100
N_EVENTS = 40
ITERATIONS = 300

_EVENT_LABELS = {
    "UserConnected": "joined",
    "UserDisconnected": "left",
    "BrickCreated": "placed a brick",
    "BrickDeleted": "removed a brick",
    "DragStarted": "started dragging",
    "DragEnded": "stopped dragging",
}

_jinja = Jinja2Templates(str(Path(__file__).parent.parent / "templates"))


@html
def Grid(*, blocks, users, online_count, cursors, logs, grid_size,
         current_session_id, show_player_setup):
    cell = 64
    half = grid_size * cell // 2
    depth = 12

    yield f"""
    <div class="flex-1 relative overflow-hidden bg-background select-none w-full h-full" id="grid-viewport">
      <div id="grid-perspective" class="absolute top-[40%] left-1/2 -translate-x-1/2 -translate-y-1/2 scale-[0.4] sm:scale-100"
           style="perspective: 1000px">
        <div id="grid-container" class="grid rotate-x-[60deg] -rotate-z-45 transform-3d"
             style="grid-template-columns: repeat({escape(grid_size)}, 4rem); grid-template-rows: repeat({escape(grid_size)}, 4rem)">
"""

    for row in range(grid_size):
        for col in range(grid_size):
            yield f"""\
            <button id="cell-{escape(col)}-{escape(row)}"
                    class="size-16 border border-foreground/[0.08] bg-foreground/[0.02] dark:border-foreground/[0.05] dark:bg-foreground/[0.015] cursor-pointer
                           transition-colors hover:bg-foreground/15 hover:border-foreground/40
                           focus:outline-none"
                    data-cell-x="{escape(col)}" data-cell-y="{escape(row)}"
                    hx-on="
                      mouseenter -> {{
                        hyperspace.call('update_cursor', [{escape(col)}, {escape(row)}, 0]);
                        var c = document.getElementById('self-cursor');
                        if (c) {{
                          var half = {escape(half)};
                          var px = {escape(col)} * 64 + 32 - half;
                          var py = {escape(row)} * 64 + 32 - half;
                          var diff = py - px, sum = px + py, denom = 1000000 - 612 * diff;
                          c.dataset.predSx = Math.round(707000 * sum / denom);
                          c.dataset.predSy = Math.round(354000 * diff / denom);
                        }}
                      }};
                      click      -> hyperspace.call('create_brick',  [{escape(col)}, {escape(row)}])"
                    style="grid-column: {escape(col + 1)}; grid-row: {escape(row + 1)}">
            </button>
"""

    for b in blocks:
        grabbing = "data-server-grabbing" if b["is_being_dragged"] else ""
        yield f"""\
          <div id="block-{escape(b['id'])}"
               data-x="{escape(b['grid_x'])}" data-y="{escape(b['grid_y'])}" data-z="{escape(b['grid_z'])}"
               data-brick-id="{escape(b['id'])}"
               {grabbing}
               :data-grabbing="(data.dragBrick == data.brickId && data.dragMoved == '1') || this.hasAttribute('data-server-grabbing') ? '' : null"
               :data-pred-x="data.predX != null && data.x === data.predX ? null : data.predX"
               :data-pred-y="data.predY != null && data.y === data.predY ? null : data.predY"
               :style="{{
                 gridColumn: (data.predX != null ? +data.predX : +data.x) + 1,
                 gridRow:    (data.predY != null ? +data.predY : +data.y) + 1,
                 zIndex: ((data.dragBrick == data.brickId && data.dragMoved == '1') || this.hasAttribute('data-server-grabbing'))
                           ? 1000
                           : ((+data.x + +data.y) * 10 + +data.z * 100 + 1)
               }}"
               class="group/brick relative cursor-grab transition-[opacity,transform]
                      data-[grabbing]:cursor-grabbing
                      group-data-[delete-mode=true]/body:cursor-crosshair
                      data-[pending-delete]:opacity-0 data-[pending-delete]:scale-90"
               hx-on="pointerdown -> {{
                 event.preventDefault(); event.stopPropagation();
                 var id = parseInt(data.brickId);
                 if (event.shiftKey) {{ attr('data-pending-delete', ''); hyperspace.call('delete_brick', [id]); return; }}
                 var b = document.body;
                 b.dataset.dragBrick = id;
                 b.dataset.dragStartX = event.clientX;
                 b.dataset.dragStartY = event.clientY;
                 b.dataset.dragMoved = '0';
               }}"
               style="--color: var(--color-brick-{escape(b['color'])});
                      transform-style: preserve-3d;
                      transform: translateZ({escape(b['grid_z'] * depth)}px)">
            <div class="size-16 border-2 border-white/25 relative overflow-hidden
                        transition-[opacity,border-color,background-color]
                        group-data-[grabbing]/brick:opacity-40
                        group-hover/brick:border-foreground/70
                        group-data-[delete-mode=true]/body:group-hover/brick:border-red-500"
                 style="background: var(--color);
                        transform: translateZ({escape(depth)}px)">
              <div class="absolute inset-0 opacity-0 group-hover/brick:opacity-100 transition-opacity bg-foreground/40 group-data-[delete-mode=true]/body:group-hover/brick:bg-red-500/50"></div>
            </div>
            <div class="absolute bottom-0 left-0 border-2 border-white/15
                        transition-[opacity,border-color,background-color,box-shadow]
                        group-data-[grabbing]/brick:opacity-40
                        group-hover/brick:border-foreground/70
                        group-data-[delete-mode=true]/body:group-hover/brick:border-red-500
                        group-data-[delete-mode=true]/body:group-hover/brick:[box-shadow:inset_0_0_0_9999px_rgba(239,68,68,0.45)]"
                 style="width: 64px; height: {escape(depth)}px;
                        background: color-mix(in srgb, var(--color) 65%, black);
                        transform-origin: bottom; transform: rotateX(-90deg)">
            </div>
            <div class="absolute top-0 left-0 border-2 border-white/15
                        transition-[opacity,border-color,background-color,box-shadow]
                        group-data-[grabbing]/brick:opacity-40
                        group-hover/brick:border-foreground/70
                        group-data-[delete-mode=true]/body:group-hover/brick:border-red-500
                        group-data-[delete-mode=true]/body:group-hover/brick:[box-shadow:inset_0_0_0_9999px_rgba(239,68,68,0.45)]"
                 style="width: {escape(depth)}px; height: 64px;
                        background: color-mix(in srgb, var(--color) 45%, black);
                        transform-origin: left; transform: rotateY(-90deg)">
            </div>
          </div>
"""

    yield """
        </div>
      </div>
"""

    for c in cursors:
        is_self = c["session_id"] == current_session_id
        px = c["grid_x"] * cell + cell // 2 - half
        py = c["grid_y"] * cell + cell // 2 - half
        diff = py - px
        total = px + py
        denom = 1000000 - 612 * diff
        sx = 707000 * total // denom
        sy = 354000 * diff // denom
        elem_id = "self-cursor" if is_self else f"cursor-{c['session_id']}"
        opacity = "opacity-100" if is_self else "opacity-60"
        reactive = ""
        if is_self:
            reactive = """:data-pred-sx="data.predSx != null && +data.sx === +data.predSx ? null : data.predSx"
           :data-pred-sy="data.predSy != null && +data.sy === +data.predSy ? null : data.predSy"
           :style="{
             left: 'calc(50% + ' + (data.predSx != null ? +data.predSx : +data.sx) + 'px)',
             top:  'calc(40% + ' + ((data.predSy != null ? +data.predSy : +data.sy) - 40) + 'px)'
           }"
           """
        yield f"""\
      <div id="{escape(elem_id)}"
           data-session="{escape(c['session_id'])}"
           data-sx="{escape(sx)}" data-sy="{escape(sy)}"
           {reactive}class="absolute pointer-events-none flex flex-col items-center -translate-x-1/2
                  {opacity}"
           style="left: calc(50% + {escape(sx)}px); top: calc(40% + {escape(sy)}px - 40px); --color: var(--color-brick-{escape(c['color'])})">
        <span class="whitespace-nowrap text-[10px] px-2 py-0.5 rounded-full mb-1
                     font-semibold border"
              style="background: var(--color);
                     color: color-mix(in srgb, var(--color), black 75%);
                     border-color: color-mix(in srgb, var(--color), white 30%)">
          {escape(c['name'])}
        </span>
        <div class="rounded-full border size-2.5"
             style="background: var(--color);
                    border-color: color-mix(in srgb, var(--color), white 30%)">
        </div>
      </div>
"""

    yield """
    </div>

    <button id="logout-btn"
            hx-on="click -> { document.cookie = 'hyperspace_id=; Max-Age=0; Path=/; SameSite=Lax'; location.reload(); }"
            title="Log out"
            class="absolute bottom-12 sm:bottom-4 left-4 z-50 p-2 rounded-lg bg-card border border-border text-muted-foreground hover:text-foreground cursor-pointer font-sans">
      <span class="icon-[lucide--log-out] size-4 block"></span>
    </button>
"""

    if online_count > 0:
        yield f"""\
    <div id="hud-players" class="absolute top-16 sm:top-4 left-4 pointer-events-none z-50 font-sans text-xs">
      <div class="rounded-xl bg-card/80 backdrop-blur-md border border-border shadow-iso-sm px-3 py-2 space-y-1.5 min-w-[120px] max-w-[200px]">
        <div class="text-[10px] uppercase tracking-widest font-medium text-muted-foreground">
          Online · {escape(online_count)}
        </div>
        <div class="space-y-1">
"""
        for i, user in enumerate([u for u in users if u["online"]][:5]):
            yield f"""\
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--color-brick-{escape(user['color'])})"></span>
              <span class="text-foreground truncate">{escape(user['name'])}</span>
            </div>
"""
        if online_count > 5:
            yield f"""<div class="text-muted-foreground text-[10px] pl-4 pt-0.5">+ {escape(online_count - 5)} more</div>"""
        yield """
        </div>
      </div>
    </div>
"""

    yield """
    <div id="console-log" class="absolute top-4 right-5 z-50 pointer-events-none
                                  w-52 h-[200px] hidden sm:flex flex-col justify-end items-end gap-1.5 font-sans text-xs text-muted-foreground overflow-hidden">
"""
    for entry in logs:
        yield f"""\
      <div id="log-{escape(entry['id'])}" class="flex items-center gap-1.5 whitespace-nowrap">
        <span class="shrink-0 w-1.5 h-1.5 rounded-full" style="background: var(--color-brick-{escape(entry['user_color'])})"></span>
        <span>{escape(entry['user_name'])} {escape(_EVENT_LABELS[entry['kind']])}</span>
      </div>
"""
    yield """    </div>
"""
    # Welcome modal omitted: only shown to brand-new visitors, never during a busy
    # broadcast, so it is not part of the steady-state render cost being measured.


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

    jinja_html = await _jinja.render("index.html.j2#grid", ctx)
    hyper_html = Grid(**ctx)

    print(f"\nRoom: {N_USERS} users, {N_BRICKS} bricks, {N_EVENTS} events")
    print(f"Output size:  Jinja {len(jinja_html) / 1024:6.1f} KB    hyper {len(hyper_html) / 1024:6.1f} KB\n")

    jinja_t, hyper_t = [], []
    for _ in range(ITERATIONS):
        t = time.perf_counter()
        await _jinja.render("index.html.j2#grid", ctx)
        jinja_t.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        Grid(**ctx)
        hyper_t.append((time.perf_counter() - t) * 1000)

    print(f"  Jinja2   {_stats(jinja_t)}")
    print(f"  hyper    {_stats(hyper_t)}")
    speedup = statistics.mean(jinja_t) / statistics.mean(hyper_t)
    faster = "faster" if speedup > 1 else "slower"
    print(f"\n  hyper is {speedup:.1f}x {faster} (render only, same context)")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
