"""Brick placement browser tests."""

from playwright.sync_api import Page, expect

EMPTY_CELL = """() => {
  for (const cell of document.querySelectorAll('.grid-cell')) {
    if (!cell.querySelector('.brick')) {
      return {x: +cell.dataset.x, y: +cell.dataset.y};
    }
  }
  return {x: 0, y: 0};
}"""


def test_single_click_places_one_brick(joined_page: Page):
    """
    Clicking an empty cell once places exactly one brick, not two.
    """
    page = joined_page
    cell = page.evaluate(EMPTY_CELL)
    placed = f"#grid-cell-{cell['x']}-{cell['y']} > .brick"
    expect(page.locator(placed)).to_have_count(0)

    page.locator(f"#grid-cell-{cell['x']}-{cell['y']} > button").click()

    page.wait_for_timeout(1000)  # let any second update land
    expect(page.locator(placed)).to_have_count(1)


def test_deleting_an_absent_brick_succeeds(joined_page: Page):
    status = joined_page.evaluate(
        "async () => (await fetch('/bricks/2147483647', {method: 'DELETE'})).status"
    )

    assert status == 204
