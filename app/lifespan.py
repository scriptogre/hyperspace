"""Application lifespan: DB init and NOTIFY listener."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app import broadcast
from app.config import settings
from app.models import Brick, Player

_NOTIFY_FN = """
CREATE OR REPLACE FUNCTION hyperspace_notify() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('hyperspace', TG_TABLE_NAME);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

_TABLES = ("bricks", "players", "cursors", "events")
_TRIGGER_LOCK = 0x68797073  # serialize trigger DDL across workers


async def _install_triggers(pg: asyncpg.Connection) -> None:
    """
    Install the NOTIFY and cursor-version triggers under an advisory lock.
    """
    await pg.execute("SELECT pg_advisory_lock($1)", _TRIGGER_LOCK)
    try:
        await pg.execute(_NOTIFY_FN)
        for table in _TABLES:
            await pg.execute(
                f'DROP TRIGGER IF EXISTS {table}_notify ON "{table}";'
                f'CREATE TRIGGER {table}_notify AFTER INSERT OR UPDATE OR DELETE ON "{table}" '
                f"FOR EACH STATEMENT EXECUTE FUNCTION hyperspace_notify();"
            )
        await pg.execute("DROP TRIGGER IF EXISTS cursors_version ON cursors")
    finally:
        await pg.execute("SELECT pg_advisory_unlock($1)", _TRIGGER_LOCK)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Start the DB and NOTIFY listener for the app's lifetime.
    """
    async with RegisterTortoise(
        app, config=settings.TORTOISE_ORM, generate_schemas=True
    ):
        # Release drags and sessions orphaned by ungraceful shutdown
        await Brick.all().update(dragged_by_id=None)
        await Player.all().update(is_online=False)

        pg = await asyncpg.connect(settings.DATABASE_URL)
        await _install_triggers(pg)

        async def on_notify(conn, pid, channel, payload):
            broadcast.notify(payload)

        await pg.add_listener("hyperspace", on_notify)

        yield

        await pg.remove_listener("hyperspace", on_notify)
        await pg.close()
