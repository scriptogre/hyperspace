"""Render cost of the cursor-delta fragment, the broadcast hot path.

Times rendering _cursor_fragments.html.j2 for M moved cursors. This is the
dominant term in a busy broadcast round, so re-run it when touching the cursor
template or the renderer.

The fragment lives in its own small partial on purpose: minijinja's
`import ... with context` re-instantiates the whole source template per render,
so rendering the same loop out of one big page template costs about 2x.

    uv run python -m bench.render
"""

import statistics
import time

from app.jinja import render


def cursors(m: int) -> list[dict]:
    return [
        {"session_id": f"u{i}", "grid_x": i % 12, "grid_y": (i * 2) % 12, "grid_z": 0,
         "active": True, "name": f"P{i}", "color": "cyan"}
        for i in range(m)
    ]


def timeit(fn, rounds: int = 300):
    fn()  # warm
    samples = []
    for _ in range(rounds):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    return statistics.mean(samples), samples[len(samples) // 2], samples[int(len(samples) * 0.99)]


def main() -> None:
    print(f"{'cursors':>8} {'mean':>9} {'p50':>9} {'p99':>9}")
    for m in (100, 600, 1000):
        ctx = {"cursors": cursors(m), "grid_size": 12}
        mean, p50, p99 = timeit(lambda c=ctx: render("_cursor_fragments.html.j2", c))
        print(f"{m:>8} {mean:>7.2f}ms {p50:>7.2f}ms {p99:>7.2f}ms")


if __name__ == "__main__":
    main()
