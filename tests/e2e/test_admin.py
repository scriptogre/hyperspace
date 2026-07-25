import asyncpg
import pytest
from app.config import settings
from playwright.sync_api import Page

from tests import run_async
from tests.e2e.conftest import join_board


async def prepare_shrink(player_id: int) -> tuple[int, int, int, str, str]:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        world = await connection.fetchrow(
            "SELECT size, theme, announcement FROM worlds WHERE id = 1"
        )
        highest_coordinate = await connection.fetchval(
            "SELECT COALESCE(MAX(GREATEST(x, y, z)), -1) FROM bricks"
        )
        target_size = max(1, highest_coordinate + 1)
        if target_size >= 32:
            pytest.skip("The test database already uses the outer grid edge")

        await connection.execute("UPDATE worlds SET size = 32 WHERE id = 1")
        brick_id = await connection.fetchval(
            """
            INSERT INTO bricks (x, y, z, color_seed, created_by_id)
            VALUES (31, 31, 0, 1, $1)
            RETURNING id
            """,
            player_id,
        )
        await connection.execute(
            """
            INSERT INTO cursors (player_id, x, y, z)
            VALUES ($1, 31, 31, -1)
            ON CONFLICT (player_id) DO UPDATE
            SET x = EXCLUDED.x,
                y = EXCLUDED.y,
                z = EXCLUDED.z
            """,
            player_id,
        )
        return (
            world["size"],
            target_size,
            brick_id,
            world["theme"] or "system",
            world["announcement"] or "",
        )
    finally:
        await connection.close()


async def inspect_shrink(brick_id: int, player_id: int) -> tuple[int, bool, bool]:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        row = await connection.fetchrow(
            """
            SELECT (SELECT size FROM worlds WHERE id = 1) AS size,
                   EXISTS(SELECT FROM bricks WHERE id = $1) AS brick_exists,
                   EXISTS(SELECT FROM cursors WHERE player_id = $2) AS cursor_exists
            """,
            brick_id,
            player_id,
        )
        return row["size"], row["brick_exists"], row["cursor_exists"]
    finally:
        await connection.close()


@pytest.mark.parametrize(
    "through_route", [True, False], ids=["admin-route", "database"]
)
def test_world_shrink_deletes_out_of_bounds_bricks_and_cursors(
    page: Page,
    browser_errors,
    through_route: bool,
):
    browser_errors(page)
    join_board(page, "scriptogre")
    player_id = int(page.locator("#app").get_attribute("data-player-id"))
    original_size, target_size, brick_id, theme, announcement = run_async(
        prepare_shrink(player_id)
    )

    try:
        if through_route:
            response = page.context.request.patch(
                "/world",
                form={
                    "size": str(target_size),
                    "theme": theme,
                    "announcement": announcement,
                },
            )
            assert response.status == 204
        else:
            run_async(shrink_world(target_size))

        assert run_async(inspect_shrink(brick_id, player_id)) == (
            target_size,
            False,
            False,
        )
    finally:
        run_async(restore_world(original_size, brick_id, player_id))


async def shrink_world(size: int) -> None:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        await connection.execute("UPDATE worlds SET size = $1", size)
    finally:
        await connection.close()


async def restore_world(size: int, brick_id: int, player_id: int) -> None:
    connection = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
    )
    try:
        await connection.execute("DELETE FROM bricks WHERE id = $1", brick_id)
        await connection.execute("DELETE FROM cursors WHERE player_id = $1", player_id)
        await connection.execute("UPDATE worlds SET size = $1", size)
    finally:
        await connection.close()
