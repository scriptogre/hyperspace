"""
Brick placement over the WebSocket bridge.
"""

from playwright.sync_api import Page, expect

EMPTY_CELL = """() => {
  const counts = {};
  document.querySelectorAll('[data-brick-id]').forEach((b) => {
    const k = b.dataset.x + ',' + b.dataset.y;
    counts[k] = (counts[k] || 0) + 1;
  });
  const size = +document.getElementById('grid-container').dataset.gridSize;
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++)
      if (!counts[x + ',' + y]) return { x, y };
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
        f'button.grid-cell[data-cell-x="{cell["x"]}"][data-cell-y="{cell["y"]}"]'
    ).dispatch_event("click")

    page.wait_for_timeout(1000)  # let any second broadcast land
    expect(page.locator(placed)).to_have_count(1)
