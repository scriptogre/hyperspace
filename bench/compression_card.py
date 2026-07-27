"""Render the compression benchmark as a shareable card."""

import math
import statistics
from pathlib import Path

WIDTH = 1200
HEIGHT = 675
CHECKPOINTS = (0, 1, 5, 10, 25, 100, 1000, 5000, 10000)


def render_card(measurements, size: int, players: int, moves: int) -> str:
    checkpoints = [value for value in CHECKPOINTS if value <= moves]
    if moves not in checkpoints:
        checkpoints.append(moves)

    rows = []
    for checkpoint in checkpoints:
        decoded = sum(measurements.decoded[: checkpoint + 1])
        standalone = sum(measurements.standalone[: checkpoint + 1])
        compressed = sum(measurements.compressed[: checkpoint + 1])
        rows.append((checkpoint, decoded / standalone, decoded / compressed))

    warm_decoded = round(statistics.median(measurements.decoded[2:]))
    warm_compressed = round(statistics.median(measurements.compressed[2:]))
    warm_ratio = statistics.median(
        decoded / compressed
        for decoded, compressed in zip(
            measurements.decoded[2:], measurements.compressed[2:], strict=True
        )
    )

    chart_left = 92
    chart_right = 1110
    chart_top = 352
    chart_bottom = 566
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top
    ceiling = max(500, math.ceil(max(row[2] for row in rows) / 500) * 500)

    def x(index: int) -> float:
        return chart_left + index * chart_width / max(1, len(rows) - 1)

    def y(value: float) -> float:
        return chart_bottom - value / ceiling * chart_height

    long_points = " ".join(
        f"{x(index):.1f},{y(row[2]):.1f}" for index, row in enumerate(rows)
    )
    standalone_points = " ".join(
        f"{x(index):.1f},{y(row[1]):.1f}" for index, row in enumerate(rows)
    )

    grid = []
    for tick in (0, ceiling // 2, ceiling):
        position = y(tick)
        grid.append(
            f'<line x1="{chart_left}" y1="{position:.1f}" x2="{chart_right}" '
            f'y2="{position:.1f}" stroke="#2b3342" stroke-width="1"/>'
            f'<text x="{chart_left - 18}" y="{position + 6:.1f}" text-anchor="end" '
            f'class="axis">{tick:,}:1</text>'
        )

    labels = []
    dots = []
    for index, (checkpoint, _, ratio) in enumerate(rows):
        position_x = x(index)
        position_y = y(ratio)
        labels.append(
            f'<text x="{position_x:.1f}" y="600" text-anchor="middle" '
            f'class="axis">{checkpoint:,}</text>'
        )
        dots.append(
            f'<circle cx="{position_x:.1f}" cy="{position_y:.1f}" r="6" '
            f'fill="#67e8f9" stroke="#0f172a" stroke-width="3"/>'
        )

    final_x = x(len(rows) - 1)
    final_y = y(rows[-1][2])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">Hyperspace stream compression benchmark</title>
<desc id="desc">A median warm update compresses {warm_decoded:,} bytes of HTML to {warm_compressed} bytes. After {moves} updates the cumulative ratio is {rows[-1][2]:,.1f} to one.</desc>
<style>
  text {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
  .muted {{ fill: #94a3b8; }}
  .axis {{ fill: #94a3b8; font-size: 16px; font-weight: 600; }}
</style>
<rect width="1200" height="675" rx="28" fill="#0b1120"/>
<circle cx="1090" cy="70" r="150" fill="#312e81" opacity="0.35"/>
<circle cx="1160" cy="160" r="110" fill="#0e7490" opacity="0.25"/>

<text x="72" y="72" fill="#67e8f9" font-size="22" font-weight="800" letter-spacing="2">HYPERSPACE · ZSTD STREAM</text>
<text x="72" y="158" fill="#f8fafc" font-size="66" font-weight="900">{warm_decoded / 1000:.0f} KB OF HTML</text>
<text x="72" y="226" fill="#94a3b8" font-size="48" font-weight="700">compresses to</text>
<text x="438" y="226" fill="#67e8f9" font-size="70" font-weight="900">{warm_compressed} BYTES</text>
<text x="72" y="275" class="muted" font-size="22">median warm cursor update per stream · {warm_ratio:,.0f}:1</text>

<text x="72" y="326" fill="#e2e8f0" font-size="18" font-weight="800" letter-spacing="1.5">CUMULATIVE COMPRESSION RATIO</text>
{"".join(grid)}
<polyline points="{standalone_points}" fill="none" stroke="#64748b" stroke-width="3" stroke-dasharray="9 9"/>
<polyline points="{long_points}" fill="none" stroke="#67e8f9" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
{"".join(dots)}
{"".join(labels)}
<text x="{chart_right}" y="326" text-anchor="end" class="muted" font-size="17">updates</text>
<text x="{final_x - 10:.1f}" y="{max(chart_top + 22, final_y - 18):.1f}" text-anchor="end" fill="#67e8f9" font-size="23" font-weight="900">{rows[-1][2]:,.0f}:1</text>

<line x1="72" y1="630" x2="1128" y2="630" stroke="#273449"/>
<text x="72" y="658" class="muted" font-size="17">{size}×{size} world · {players} cursors · 0 bricks · no joins · application body bytes</text>
<text x="1128" y="658" text-anchor="end" fill="#cbd5e1" font-size="17" font-weight="700">github.com/scriptogre/hyperspace</text>
</svg>'''


def write_card(
    measurements,
    size: int,
    players: int,
    moves: int,
    svg_path: Path | None,
    png_path: Path | None,
) -> None:
    svg = render_card(measurements, size, players, moves)

    if svg_path:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg)
        print(f"SVG: {svg_path}")

    if png_path:
        from playwright.sync_api import sync_playwright

        png_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            page.set_content(
                f"<style>html,body{{margin:0;background:#0b1120}}</style>{svg}"
            )
            page.screenshot(path=png_path)
            browser.close()
        print(f"PNG: {png_path}")
