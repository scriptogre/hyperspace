"""Measure browser work for full-World morphs and cursor movement."""

import argparse
import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import asyncpg
from playwright.sync_api import Page, sync_playwright

from app.config import settings

BASE_URL = "http://fastapi:8000"
METRICS = {
    "LayoutDuration",
    "RecalcStyleDuration",
    "ScriptDuration",
    "TaskDuration",
}


@dataclass
class Result:
    size: int
    players: int
    mode: str
    elements: int
    listeners: int
    response_kib: float
    p50_ms: float
    p95_ms: float
    frames_per_second: float
    long_tasks: int
    script_ms: float
    style_ms: float
    layout_ms: float
    task_ms: float


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1]


async def seed_world(size: int, players: int) -> None:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        async with connection.transaction():
            await connection.execute("DELETE FROM events")
            await connection.execute("DELETE FROM bricks")
            await connection.execute("DELETE FROM cursors")
            await connection.execute("DELETE FROM players")
            await connection.execute("UPDATE worlds SET size = $1 WHERE id = 1", size)
            await connection.execute(
                """
                INSERT INTO players (id, token, name, color_seed, is_online)
                SELECT i,
                       'browser-bench-' || i,
                       'Player ' || i,
                       1 + ((i * 17) % 100),
                       TRUE
                  FROM generate_series(1, $1) AS i
                """,
                players,
            )
            await connection.execute(
                """
                INSERT INTO cursors (player_id, x, y, z)
                SELECT i,
                       (i - 1) % $2,
                       ((i - 1) / $2) % $2,
                       -1
                  FROM generate_series(1, $1) AS i
                """,
                players,
                size,
            )
    finally:
        await connection.close()


def performance_metrics(cdp) -> dict[str, float]:
    return {
        item["name"]: item["value"]
        for item in cdp.send("Performance.getMetrics")["metrics"]
    }


def make_snapshots(page: Page) -> dict[str, list[str]]:
    return page.locator("#world").evaluate(
        """world => {
            const make = preserveRuntime => [0, 1].map(x => {
                const clone = world.cloneNode(true)
                if (!preserveRuntime) {
                    for (const element of [clone, ...clone.querySelectorAll('*')]) {
                        element.removeAttribute('data-htmx-powered')
                        element.removeAttribute('data-local-cursor')
                        element.removeAttribute('data-local-dragging')
                        element.removeAttribute('data-drag-over')
                    }
                }
                const cursor = clone.querySelector('#cursor-1')
                cursor.dataset.x = x
                cursor.style.setProperty('--x', x)
                return clone.outerHTML
            })
            const snapshots = {server: make(false), runtime: make(true)}
            snapshots.compact = snapshots.server.map(html => html.replace(/>\\s+</g, '><'))
            snapshots.skipBricks = snapshots.server.map(html =>
                html.replace('id="bricks"', 'id="bricks" hx-morph-skip'))
            snapshots.skipBricksCompact = snapshots.skipBricks.map(html =>
                html.replace(/>\\s+</g, '><'))
            snapshots.lean = snapshots.server.map(html => {
                const template = document.createElement('template')
                template.innerHTML = html
                for (const element of template.content.querySelectorAll(
                    '[id^=grid-cell-], [id^=grid-cell-] > button[aria-label="Add brick"]'
                )) {
                    for (const name of element.getAttributeNames()) {
                        if (name.startsWith('hx-') || name === 'data-htmx-powered') {
                            element.removeAttribute(name)
                        }
                    }
                }
                return template.content.firstElementChild.outerHTML
            })
            return snapshots
        }"""
    )


def run_updates(
    page: Page, snapshots: dict[str, list[str]], iterations: int, mode: str
) -> dict:
    return page.evaluate(
        """async ({snapshots, iterations, mode}) => {
            const durations = []
            const frameTimes = []
            const longTasks = []
            const observer = new PerformanceObserver(list => {
                longTasks.push(...list.getEntries().map(entry => entry.duration))
            })
            observer.observe({type: 'longtask', buffered: false})

            const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve))
            await nextFrame()
            let previousFrame = performance.now()
            const wallStart = previousFrame

            for (let index = 0; index < iterations; index++) {
                await nextFrame()
                const frame = performance.now()
                frameTimes.push(frame - previousFrame)
                previousFrame = frame
                const start = performance.now()

                if (mode.startsWith('morph')) {
                    const kind = mode === 'morph-runtime'
                        ? 'runtime'
                        : mode.includes('skip-bricks')
                            ? mode.includes('compact') ? 'skipBricksCompact' : 'skipBricks'
                            : mode.includes('compact')
                                ? 'compact'
                                : mode === 'morph-lean' ? 'lean' : 'server'
                    const process = htmx.process
                    if (mode.includes('no-process')) htmx.process = () => {}
                    try {
                        await htmx.swap(snapshots[kind][index % 2], '#world', {
                            source: document.body,
                            swap: 'outerMorph',
                        })
                    } finally {
                        htmx.process = process
                    }
                } else if (mode === 'parse') {
                    const template = document.createElement('template')
                    template.innerHTML = snapshots.server[index % 2]
                } else if (mode === 'process') {
                    htmx.process(document.querySelector('#world'))
                } else {
                    const cursor = document.querySelector('#cursor-1')
                    const x = index % 2
                    cursor.dataset.x = x
                    cursor.style.setProperty('--x', x)
                }

                document.querySelector('#grid').getBoundingClientRect()
                durations.push(performance.now() - start)
            }

            await nextFrame()
            await nextFrame()
            observer.disconnect()
            return {
                durations,
                frameTimes,
                longTasks,
                wallMs: performance.now() - wallStart,
            }
        }""",
        {"snapshots": snapshots, "iterations": iterations, "mode": mode},
    )


def benchmark(
    page: Page, cdp, size: int, players: int, iterations: int
) -> list[Result]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, seed_world(size, players)).result()
    page.context.add_cookies(
        [{"name": "hyperspace", "value": "browser-bench-1", "url": BASE_URL}]
    )
    response = page.goto("/", wait_until="domcontentloaded")
    if not response or response.status != 200:
        raise RuntimeError(
            f"Page returned {response.status if response else 'no response'}"
        )
    try:
        page.locator("#cursor-1").wait_for(state="attached")
    except Exception as error:
        raise RuntimeError(
            f"World has {page.locator('.cursor').count()} cursors and "
            f"{page.locator('[id^=grid-cell-]').count()} cells"
        ) from error
    if page.locator("#player-form").count():
        page.locator("#player-form").evaluate("element => element.remove()")
    page.wait_for_timeout(750)

    snapshots = make_snapshots(page)
    elements = page.locator("#world *").count() + 1
    metrics = performance_metrics(cdp)
    listeners = round(metrics.get("JSEventListeners", 0))
    results = []

    for mode in (
        "cursor",
        "parse",
        "process",
        "morph-runtime",
        "morph",
        "morph-no-process",
        "morph-compact",
        "morph-compact-no-process",
        "morph-skip-bricks",
        "morph-skip-bricks-no-process",
        "morph-skip-bricks-compact-no-process",
    ):
        if mode.startswith("morph"):
            kind = (
                "runtime"
                if mode == "morph-runtime"
                else "skipBricksCompact"
                if "skip-bricks" in mode and "compact" in mode
                else "skipBricks"
                if "skip-bricks" in mode
                else "compact"
                if "compact" in mode
                else "server"
            )
            for index in range(3):
                page.evaluate(
                    """async ({html, index}) => htmx.swap(html[index % 2], '#world', {
                        source: document.body,
                        swap: 'outerMorph',
                    })""",
                    {"html": snapshots[kind], "index": index},
                )
            page.wait_for_timeout(100)

        cdp.send("HeapProfiler.collectGarbage")
        before = performance_metrics(cdp)
        measured = run_updates(page, snapshots, iterations, mode)
        after = performance_metrics(cdp)
        durations = measured["durations"]
        wall_seconds = measured["wallMs"] / 1000
        results.append(
            Result(
                size=size,
                players=players,
                mode=mode,
                elements=elements,
                listeners=listeners,
                response_kib=len(
                    snapshots["compact" if "compact" in mode else "server"][0].encode()
                )
                / 1024,
                p50_ms=percentile(durations, 0.50),
                p95_ms=percentile(durations, 0.95),
                frames_per_second=iterations / wall_seconds,
                long_tasks=len(measured["longTasks"]),
                script_ms=(after["ScriptDuration"] - before["ScriptDuration"]) * 1000,
                style_ms=(after["RecalcStyleDuration"] - before["RecalcStyleDuration"])
                * 1000,
                layout_ms=(after["LayoutDuration"] - before["LayoutDuration"]) * 1000,
                task_ms=(after["TaskDuration"] - before["TaskDuration"]) * 1000,
            )
        )

    return results


def print_results(results: list[Result], iterations: int) -> None:
    print(
        "size players mode          elements listeners response  p50     p95     fps   "
        "long  script/update style/update layout/update task/update"
    )
    for result in results:
        print(
            f"{result.size:>4} {result.players:>7} {result.mode:<13} "
            f"{result.elements:>8} {result.listeners:>9} "
            f"{result.response_kib:>7.0f}K "
            f"{result.p50_ms:>6.1f}ms {result.p95_ms:>6.1f}ms "
            f"{result.frames_per_second:>5.1f} "
            f"{result.long_tasks:>4} "
            f"{result.script_ms / iterations:>10.1f}ms "
            f"{result.style_ms / iterations:>10.1f}ms "
            f"{result.layout_ms / iterations:>11.1f}ms "
            f"{result.task_ms / iterations:>9.1f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--sizes", type=int, nargs="+", default=[12, 32])
    parser.add_argument("--players", type=int, nargs="+", default=[50, 100])
    args = parser.parse_args()

    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            base_url=BASE_URL, viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("Performance.enable")
        for size in args.sizes:
            for players in args.players:
                results.extend(benchmark(page, cdp, size, players, args.iterations))
        browser.close()

    print_results(results, args.iterations)


if __name__ == "__main__":
    main()
