"""Render the compression benchmark as a shareable card."""

import base64
import statistics
from pathlib import Path

WIDTH = 1200
HEIGHT = 675
FONT_DIR = Path(__file__).parents[1] / "app" / "static" / "fonts"


def font_data(name: str) -> str:
    return base64.b64encode((FONT_DIR / name).read_bytes()).decode()


def render_card(measurements, size: int, players: int, moves: int) -> str:
    warm_decoded = round(statistics.median(measurements.decoded[2:]))
    warm_compressed = round(statistics.median(measurements.compressed[2:]))
    warm_ratio = statistics.median(
        decoded / compressed
        for decoded, compressed in zip(
            measurements.decoded[2:], measurements.compressed[2:], strict=True
        )
    )
    space_grotesk = font_data("space-grotesk.woff2")
    jetbrains_mono = font_data("jetbrains-mono.woff2")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">Hyperspace stream compression benchmark</title>
<desc id="desc">A median warm cursor template update compresses {warm_decoded:,} bytes to {warm_compressed} bytes, a {warm_ratio:,.0f} to one ratio.</desc>
<style>
  @font-face {{ font-family: "Space Grotesk"; src: url(data:font/woff2;base64,{space_grotesk}); }}
  @font-face {{ font-family: "JetBrains Mono"; src: url(data:font/woff2;base64,{jetbrains_mono}); }}
  .sans {{ font-family: "Space Grotesk", sans-serif; }}
  .mono {{ font-family: "JetBrains Mono", monospace; }}
</style>
<rect width="1200" height="675" rx="24" fill="#fafaf9"/>
<rect x="1" y="1" width="1198" height="673" rx="23" fill="none" stroke="#e7e7e5" stroke-width="2"/>

<text x="64" y="62" class="mono" fill="#777773" font-size="16" font-weight="600" letter-spacing="1.5">HYPERSPACE / STREAM COMPRESSION</text>

<text x="286" y="310" text-anchor="middle" class="sans" fill="#343432" font-size="116" font-weight="600">{warm_decoded / 1000:.0f} KB</text>
<text x="570" y="302" text-anchor="middle" class="sans" fill="#b1b1ad" font-size="88">→</text>
<text x="884" y="310" text-anchor="middle" class="sans" fill="#4f46e5" font-size="116" font-weight="600">{warm_compressed} bytes</text>

<text x="600" y="415" text-anchor="middle" class="sans" fill="#343432" font-size="46" font-weight="600">{warm_ratio:,.0f}:1 compression</text>
<text x="600" y="460" text-anchor="middle" class="sans" fill="#777773" font-size="23">median warm cursor template update</text>

<line x1="64" y1="602" x2="1136" y2="602" stroke="#dededb"/>
<text x="64" y="638" class="mono" fill="#777773" font-size="14">{size}×{size} world · {players} cursors · 0 bricks · no joins · body bytes</text>
<text x="1136" y="638" text-anchor="end" class="sans" fill="#555552" font-size="15" font-weight="600">github.com/scriptogre/hyperspace</text>
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
