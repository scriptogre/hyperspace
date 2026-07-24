import time
from urllib.parse import parse_qs

from playwright.sync_api import Page


def wait_until(page: Page, condition, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert condition()


def test_latest_cursor_position_wins_when_requests_finish_out_of_order(
    joined_page: Page,
):
    page = joined_page
    held = []
    requests = []
    responses = []

    def handle_cursor(route) -> None:
        values = parse_qs(route.request.post_data or "")
        requests.append((values["x"][0], values["y"][0]))
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/cursor", handle_cursor)
    page.on(
        "response",
        lambda response: (
            responses.append(response) if response.url.endswith("/cursor") else None
        ),
    )
    cells = page.locator(".grid-cell").evaluate_all(
        "cells => cells.slice(0, 2).map(cell => ({"
        "id: cell.id, x: cell.dataset.x, y: cell.dataset.y"
        "}))"
    )
    first, latest = cells

    page.locator(f"#{first['id']}").dispatch_event("pointerenter")
    wait_until(page, lambda: len(requests) == 1)

    page.locator(f"#{latest['id']}").dispatch_event("pointerenter")
    page.wait_for_timeout(100)

    assert requests == [(first["x"], first["y"])]
    held[0].continue_()

    wait_until(page, lambda: len(requests) == 2)
    wait_until(page, lambda: len(responses) == 2)
    page.wait_for_timeout(100)

    cursor = page.locator(
        f"#cursor-{page.locator('#app').get_attribute('data-player-id')}"
    )
    assert (cursor.get_attribute("data-x"), cursor.get_attribute("data-y")) == (
        latest["x"],
        latest["y"],
    )
