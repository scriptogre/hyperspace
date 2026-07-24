import re

import asyncpg
from app.config import settings
from playwright.sync_api import Page, expect

from tests import run_async


async def update_world(theme: str, size: int, announcement: str | None) -> None:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        await connection.execute(
            """
            UPDATE worlds
               SET theme = $1,
                   size = $2,
                   announcement = $3
             WHERE id = 1
            """,
            theme,
            size,
            announcement,
        )
    finally:
        await connection.close()


def test_world_changes_reach_browser(joined_page: Page):
    page = joined_page

    try:
        run_async(update_world("dark", 13, "World notice"))

        expect(page.locator("#world")).to_have_attribute(
            "style",
            re.compile(r"color-scheme: dark"),
        )
        expect(page.locator("#announcement")).to_have_text("World notice")
        expect(page.locator(".grid-cell")).to_have_count(169)
        expect(page.locator("#grid")).to_have_css("--world-size", "13")
    finally:
        run_async(update_world("light", 12, None))
