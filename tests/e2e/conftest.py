"""
Shared fixtures for Playwright e2e tests.

Assumes the stack is running via: just test
"""

import uuid

import pytest
from playwright.sync_api import Page, expect


def join_board(page: Page, name: str | None = None) -> None:
    """
    Join the board through the overlay form and wait for it to close.
    """
    page.goto("/")
    form = page.locator("#player-form")
    expect(form).to_be_visible(timeout=10_000)
    form.locator("input[name=name]").fill(name or f"e2e_{uuid.uuid4().hex[:6]}")
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0, timeout=10_000)


@pytest.fixture
def browser_errors():
    errors = []

    def watch(page: Page) -> None:
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}")
                if message.type in {"error", "warning"}
                else None
            ),
        )

    yield watch
    assert errors == []


@pytest.fixture
def joined_page(page: Page, browser_errors) -> Page:
    """Join the board with browser errors treated as test failures."""
    page.set_default_timeout(10_000)
    browser_errors(page)
    join_board(page)
    return page
