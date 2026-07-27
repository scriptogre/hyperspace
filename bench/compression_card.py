"""Render the compression benchmark as a shareable card."""

import base64
import math
import statistics
from pathlib import Path

WIDTH = 1200
HEIGHT = 675
CHECKPOINTS = (0, 1, 5, 10, 25, 100, 1000, 5000, 10000)
FONT_DIR = Path(__file__).parents[1] / "app" / "static" / "fonts"


def font_data(name: str) -> str:
    return base64.b64encode((FONT_DIR / name).read_bytes()).decode()


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

    chart_left = 84
    chart_right = 1120
    chart_top = 340
    chart_bottom = 555
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
            f'y2="{position:.1f}" stroke="#e7e7e5"/>'
            f'<text x="{chart_left - 16}" y="{position + 5:.1f}" text-anchor="end" '
            f'class="axis">{tick:,}:1</text>'
        )

    labels = []
    dots = []
    for index, (checkpoint, _, ratio) in enumerate(rows):
        position_x = x(index)
        position_y = y(ratio)
        labels.append(
            f'<text x="{position_x:.1f}" y="585" text-anchor="middle" '
            f'class="axis">{checkpoint:,}</text>'
        )
        dots.append(
            f'<circle cx="{position_x:.1f}" cy="{position_y:.1f}" r="5" '
            f'fill="#ffffff" stroke="#4f46e5" stroke-width="3"/>'
        )

    final_x = x(len(rows) - 1)
    final_y = y(rows[-1][2])
    space_grotesk = font_data("space-grotesk.woff2")
    jetbrains_mono = font_data("jetbrains-mono.woff2")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">Hyperspace stream compression benchmark</title>
<desc id="desc">A median warm update compresses {warm_decoded:,} bytes of HTML to {warm_compressed} bytes. After {moves} updates the cumulative ratio is {rows[-1][2]:,.1f} to one.</desc>
<style>
  @font-face {{ font-family: "Space Grotesk"; src: url(data:font/woff2;base64,{space_grotesk}); }}
  @font-face {{ font-family: "JetBrains Mono"; src: url(data:font/woff2;base64,{jetbrains_mono}); }}
  .sans {{ font-family: "Space Grotesk", sans-serif; }}
  .mono, .axis {{ font-family: "JetBrains Mono", monospace; }}
  .axis {{ fill: #8c8c89; font-size: 14px; font-weight: 500; }}
</style>
<rect width="1200" height="675" rx="24" fill="#fafaf9"/>
<rect x="1" y="1" width="1198" height="673" rx="23" fill="none" stroke="#e7e7e5" stroke-width="2"/>

<text x="64" y="55" class="mono" fill="#777773" font-size="16" font-weight="600" letter-spacing="1.5">HYPERSPACE / STREAM COMPRESSION</text>
<text x="64" y="145" class="sans" fill="#343432" font-size="76" font-weight="600">{warm_decoded / 1000:.0f} KB</text>
<text x="300" y="145" class="sans" fill="#b1b1ad" font-size="68">→</text>
<text x="378" y="145" class="sans" fill="#4f46e5" font-size="76" font-weight="600">{warm_compressed} bytes</text>
<text x="66" y="185" class="sans" fill="#777773" font-size="23">median warm cursor update per stream</text>

<rect x="875" y="80" width="260" height="128" rx="14" fill="#e7e7e5"/>
<rect x="869" y="74" width="260" height="128" rx="14" fill="#ffffff" stroke="#dededb"/>
<text x="899" y="132" class="sans" fill="#343432" font-size="42" font-weight="600">{warm_ratio:,.0f}:1</text>
<text x="900" y="168" class="mono" fill="#777773" font-size="14">warm update ratio</text>

<text x="64" y="282" class="mono" fill="#555552" font-size="15" font-weight="600" letter-spacing="1">CUMULATIVE RATIO</text>
<line x1="830" y1="277" x2="866" y2="277" stroke="#4f46e5" stroke-width="4"/>
<text x="876" y="282" class="mono" fill="#777773" font-size="13">long-lived</text>
<line x1="984" y1="277" x2="1020" y2="277" stroke="#a3a3a0" stroke-width="2" stroke-dasharray="7 7"/>
<text x="1030" y="282" class="mono" fill="#777773" font-size="13">standalone</text>

{"".join(grid)}
<polyline points="{standalone_points}" fill="none" stroke="#a3a3a0" stroke-width="2" stroke-dasharray="7 7"/>
<polyline points="{long_points}" fill="none" stroke="#4f46e5" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
{"".join(dots)}
{"".join(labels)}
<text x="{final_x - 8:.1f}" y="{max(chart_top + 20, final_y - 16):.1f}" text-anchor="end" class="sans" fill="#4f46e5" font-size="22" font-weight="600">{rows[-1][2]:,.0f}:1</text>

<line x1="64" y1="620" x2="1136" y2="620" stroke="#dededb"/>
<text x="64" y="651" class="mono" fill="#777773" font-size="14">{size}×{size} world · {players} cursors · 0 bricks · no joins · body bytes</text>
<text x="1136" y="651" text-anchor="end" class="sans" fill="#555552" font-size="15" font-weight="600">github.com/scriptogre/hyperspace</text>
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
                f"<style>html,body{{margin:0;background:#fafaf9}}</style>{svg}"
            )
            page.screenshot(path=png_path)
            browser.close()
        print(f"PNG: {png_path}")
