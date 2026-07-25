import asyncio
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from tortoise import Tortoise

from app.dependencies import get_world_context
from tests import run_async


ROOT = Path(__file__).parents[1]


def postgres_kwargs(database: str) -> dict[str, Any]:
    return {
        "host": os.environ["POSTGRES_HOST"],
        "port": int(os.environ["POSTGRES_PORT"]),
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "database": database,
    }


async def create_database(database: str) -> None:
    connection = await asyncpg.connect(**postgres_kwargs("postgres"))
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def drop_database(database: str) -> None:
    connection = await asyncpg.connect(**postgres_kwargs("postgres"))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await connection.close()


@pytest.fixture(scope="module")
def database() -> Iterator[dict[str, Any]]:
    required = {
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    }
    if missing := required - os.environ.keys():
        pytest.skip(f"PostgreSQL settings missing: {', '.join(sorted(missing))}")
    if shutil.which("tortoise") is None:
        pytest.skip("tortoise CLI is not installed")

    name = f"hyperspace_test_{uuid.uuid4().hex}"
    environment = os.environ.copy()
    environment["POSTGRES_DB"] = name
    try:
        run_async(create_database(name))
        result = subprocess.run(
            ["tortoise", "migrate"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            pytest.fail(result.stdout + result.stderr)
        yield postgres_kwargs(name)
    finally:
        run_async(drop_database(name))


async def rejected(database: dict[str, Any], statement: str) -> None:
    connection = await asyncpg.connect(**database)
    try:
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute(statement)
    finally:
        await connection.close()


def test_world_is_seeded_as_a_singleton(database):
    async def check():
        connection = await asyncpg.connect(**database)
        try:
            return await connection.fetchrow(
                "SELECT id, theme, size, announcement FROM worlds"
            )
        finally:
            await connection.close()

    row = run_async(check())
    assert dict(row) == {
        "id": 1,
        "theme": None,
        "size": 12,
        "announcement": None,
    }


def test_world_rejects_invalid_identity_and_values(database):
    run_async(rejected(database, "UPDATE worlds SET id = 2"))
    run_async(rejected(database, "INSERT INTO worlds (id) VALUES (2)"))
    run_async(rejected(database, "UPDATE worlds SET theme = 'sepia'"))
    run_async(rejected(database, "UPDATE worlds SET size = 0"))
    run_async(rejected(database, "UPDATE worlds SET size = 33"))
    run_async(rejected(database, "DELETE FROM worlds"))
    run_async(rejected(database, "TRUNCATE worlds"))


def test_coordinate_constraints_use_world_size(database):
    async def check():
        connection = await asyncpg.connect(**database)
        try:
            player_id = await connection.fetchval(
                """
                INSERT INTO players (token, name, color_seed, is_online)
                VALUES ($1, 'Coordinate test', 1, true)
                RETURNING id
                """,
                uuid.uuid4().hex,
            )
            await connection.execute(
                """
                INSERT INTO bricks (x, y, z, color_seed, created_by_id)
                VALUES (11, 11, 11, 1, $1)
                """,
                player_id,
            )
            await connection.execute(
                "INSERT INTO cursors (player_id, x, y, z) VALUES ($1, 11, 11, -1)",
                player_id,
            )
        finally:
            await connection.close()

    run_async(check())
    run_async(
        rejected(
            database,
            "INSERT INTO bricks (x, y, z, color_seed) VALUES (12, 0, 0, 1)",
        )
    )
    run_async(
        rejected(
            database,
            "INSERT INTO bricks (x, y, z, color_seed) VALUES (0, 0, -1, 1)",
        )
    )
    run_async(
        rejected(
            database,
            "INSERT INTO cursors (player_id, x, y, z) VALUES (999999, 12, 0, -1)",
        )
    )


def test_resize_shrink_deletes_out_of_bounds(database):
    async def check():
        connection = await asyncpg.connect(**database)
        try:
            await connection.execute("UPDATE worlds SET size = 13")
            await connection.execute("UPDATE worlds SET size = 12")
            survived = await connection.fetchval(
                "SELECT count(*) FROM bricks WHERE x = 11"
            )

            await connection.execute("UPDATE worlds SET size = 11")
            bricks = await connection.fetchval(
                "SELECT count(*) FROM bricks WHERE x >= 11 OR y >= 11 OR z >= 11"
            )
            cursors = await connection.fetchval(
                "SELECT count(*) FROM cursors WHERE x >= 11 OR y >= 11"
            )

            # Restore the state later tests expect.
            await connection.execute("UPDATE worlds SET size = 12")
            player_id = await connection.fetchval("SELECT id FROM players LIMIT 1")
            await connection.execute(
                """
                INSERT INTO bricks (x, y, z, color_seed, created_by_id)
                VALUES (11, 11, 11, 1, $1)
                """,
                player_id,
            )
            await connection.execute(
                "INSERT INTO cursors (player_id, x, y, z) VALUES ($1, 11, 11, -1)",
                player_id,
            )
            return survived, bricks, cursors
        finally:
            await connection.close()

    survived, bricks, cursors = run_async(check())
    assert survived == 1
    assert bricks == 0
    assert cursors == 0


def test_world_notifications_use_one_payload(database):
    async def check():
        connection = await asyncpg.connect(**database)
        payloads: asyncio.Queue[str] = asyncio.Queue()

        def notify(_, __, ___, payload):
            payloads.put_nowait(payload)

        await connection.add_listener("hyperspace", notify)
        try:
            await connection.execute("UPDATE worlds SET announcement = 'Notice'")
            return await asyncio.wait_for(payloads.get(), timeout=2)
        finally:
            await connection.remove_listener("hyperspace", notify)
            await connection.close()

    assert run_async(check()) == "world_changed"


def test_orm_snapshot_returns_complete_world(database):
    async def check():
        await Tortoise.init(
            config={
                "connections": {
                    "default": {
                        "engine": "tortoise.backends.asyncpg",
                        "credentials": database,
                    }
                },
                "apps": {
                    "models": {
                        "models": ["app.models"],
                        "default_connection": "default",
                    }
                },
            }
        )
        try:
            return await get_world_context()
        finally:
            await Tortoise.close_connections()

    context = run_async(check())
    assert context["world"].size == 12
    assert context["world"].announcement == "Notice"
    assert context["players"]
    assert context["cursors"]
    assert context["brick_stacks"][11][11]
