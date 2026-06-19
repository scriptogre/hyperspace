"""
Brick placement over the WebSocket bridge.
"""

from playwright.sync_api import Page, expect

EMPTY_CELL = """() => {
  const taken = new Set();
  document.querySelectorAll('[data-brick-id]').forEach(b => taken.add(b.dataset.x + ',' + b.dataset.y));
  for (const c of document.querySelectorAll('button.grid-cell')) {
    const k = c.dataset.x + ',' + c.dataset.y;
    if (!taken.has(k)) return { x: +c.dataset.x, y: +c.dataset.y };
  }
  return { x: 0, y: 0 };
}"""


def test_single_click_places_one_brick(joined_page: Page):
    """
    Clicking an empty cell once places exactly one brick, not two.
    """
    page = joined_page
    cell = page.evaluate(EMPTY_CELL)
    placed = f'[data-brick-id][data-x="{cell["x"]}"][data-y="{cell["y"]}"]'
    expect(page.locator(placed)).to_have_count(0)

    page.locator(
        f'button.grid-cell[data-x="{cell["x"]}"][data-y="{cell["y"]}"]'
    ).dispatch_event("click")

    page.wait_for_timeout(1000)  # let any second broadcast land
    expect(page.locator(placed)).to_have_count(1)


def test_click_shows_optimistic_placeholder(joined_page: Page):
    """
    On cell click, hx-optimistic stamps the template into #grid-container at the
    clicked cell, then removes it once the request completes.
    """
    page = joined_page
    cell = page.evaluate(EMPTY_CELL)
    cx, cy = cell["x"], cell["y"]

    # Throttle POST /bricks so the optimistic window is observable.
    page.route(
        "**/bricks",
        lambda route: page.wait_for_timeout(500) or route.continue_(),
    )
    try:
        page.locator(
            f'button.grid-cell[data-x="{cx}"][data-y="{cy}"]'
        ).dispatch_event("click")

        inner = page.locator(".hx-optimistic > div")
        expect(inner).to_have_count(1)
        placement = inner.evaluate(
            "e => { const s = getComputedStyle(e); return {col: s.gridColumnStart, row: s.gridRowStart}; }"
        )
        assert placement == {"col": str(cx + 1), "row": str(cy + 1)}, placement

        page.wait_for_timeout(1500)
        expect(page.locator(".hx-optimistic")).to_have_count(0)
        expect(
            page.locator(f'[data-brick-id][data-x="{cx}"][data-y="{cy}"]')
        ).to_have_count(1)
    finally:
        page.unroute_all(behavior="ignoreErrors")
