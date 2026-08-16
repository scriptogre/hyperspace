import asyncpg
from app.config import settings
from playwright.sync_api import Page, expect

from tests import run_async


async def get_world() -> tuple[str | None, int, str | None]:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        row = await connection.fetchrow(
            "SELECT theme, size, announcement FROM worlds WHERE id = 1"
        )
        assert row is not None
        return row["theme"], row["size"], row["announcement"]
    finally:
        await connection.close()


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


def test_world_is_live_before_join(page: Page, browser_errors):
    browser_errors(page)
    original = run_async(get_world())

    try:
        page.goto("/")
        expect(page.locator("#player-form")).to_be_visible()
        expect(page.locator("#world")).to_be_visible()
        expect(page.locator("#app")).to_have_attribute("inert", "")

        run_async(update_world(original[0], original[1], "Live before joining"))

        expect(page.locator("#announcement")).to_have_text("Live before joining")
    finally:
        run_async(update_world(*original))


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
        run_async(update_world("light", 13, "World notice"))

        expect(app).to_have_css("color-scheme", "light")
        expect(world).to_have_css("background-color", "oklch(0.985 0 0)")
        expect(world).to_have_css("color", "oklch(0.205 0 0)")
        expect(page.locator("#announcement")).to_have_text("World notice")
        expect(page.locator("[id^=grid-cell-]")).to_have_count(169)
        grid = page.locator("#grid")
        expect(grid).to_have_css("--world-size", "13")
        expect(grid).to_have_css("transition-property", "scale, translate")
        expect(grid).to_have_css("transition-duration", "0.75s, 0.75s")
        expect(grid).to_have_css("transition-delay", "0.15s, 0.15s")
        new_tile = page.locator("#grid-cell-12-12")
        assert new_tile.evaluate(
            "element => getComputedStyle(element, '::before').transitionProperty"
        ) == ("opacity")
        assert new_tile.evaluate(
            "element => getComputedStyle(element, '::before').transitionDuration"
        ) == ("0.18s")
        assert new_tile.evaluate(
            "element => getComputedStyle(element, '::before').transitionDelay"
        ) == ("0.072s")

        page.emulate_media(color_scheme="light")
        run_async(update_world("dark", 13, "World notice"))

        expect(app).to_have_css("color-scheme", "dark")
        expect(world).to_have_css("background-color", "oklch(0.157 0 0)")
        expect(world).to_have_css("color", "oklch(0.985 0 0)")
    finally:
        run_async(update_world(None, 12, None))
