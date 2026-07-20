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
def joined_page(page: Page) -> Page:
    """
    A page that has joined the board and can place bricks.
    """
    page.set_default_timeout(10_000)
    join_board(page)
    return page
