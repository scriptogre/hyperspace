import asyncpg
from app.config import settings
from playwright.sync_api import Page, expect

from tests import run_async


async def update_world(theme: str | None, size: int, announcement: str | None) -> None:
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


def test_world_rejects_coordinates_outside_its_bounds(joined_page: Page):
    response = joined_page.context.request.patch(
        "/cursor",
        form={"x": "99", "y": "99", "z": "-1"},
    )

    assert response.status == 422


def test_world_changes_reach_browser(joined_page: Page):
    page = joined_page
    app = page.locator("#app")
    world = page.locator("#world")

    try:
        page.emulate_media(color_scheme="dark")
        run_async(update_world(None, 12, None))

        expect(app).to_have_css("color-scheme", "light dark")
        expect(world).to_have_css("background-color", "oklch(0.157 0 0)")
        expect(world).to_have_css("color", "oklch(0.985 0 0)")
        assert world.get_attribute("data-theme") is None

        run_async(update_world("light", 13, "World notice"))

        expect(world).to_have_attribute("data-theme", "light")
        expect(app).to_have_css("color-scheme", "light")
        expect(world).to_have_css("background-color", "oklch(0.985 0 0)")
        expect(world).to_have_css("color", "oklch(0.205 0 0)")
        expect(page.locator("#announcement")).to_have_text("World notice")
        expect(page.locator(".grid-cell")).to_have_count(169)
        grid = page.locator("#grid")
        expect(grid).to_have_css("--world-size", "13")
        expect(grid).to_have_css("transition-property", "scale")
        expect(grid).to_have_css("transition-duration", "0.75s")
        expect(grid).to_have_css("transition-delay", "0.35s")
        assert (
            grid.evaluate("element => getComputedStyle(element).backgroundImage")
            != "none"
        )
        assert (
            page.locator("#grid-cell-12-12").evaluate(
                "element => getComputedStyle(element, '::before').content"
            )
            == "none"
        )

        page.emulate_media(color_scheme="light")
        run_async(update_world("dark", 13, "World notice"))

        expect(world).to_have_attribute("data-theme", "dark")
        expect(app).to_have_css("color-scheme", "dark")
        expect(world).to_have_css("background-color", "oklch(0.157 0 0)")
        expect(world).to_have_css("color", "oklch(0.985 0 0)")
    finally:
        run_async(update_world(None, 12, None))
