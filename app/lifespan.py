"""Application lifespan: DB init and shared update renderer."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import settings
from app.models import Brick, Cursor, Player

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
        await pg.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
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


async def listen_to_postgres(
    postgres: asyncpg.Connection,
) -> AsyncIterator[str]:
    """
    Yield table names received through PostgreSQL notifications.
    """
    notified = asyncio.Event()
    tables: set[str] = set()

    def notify(conn, pid, channel, payload):
        tables.add(payload)
        notified.set()

    await postgres.add_listener("hyperspace", notify)
    try:
        while True:
            await notified.wait()
            notified.clear()
            pending, tables = tables, set()
            for table in sorted(pending):
                yield table
    finally:
        await postgres.remove_listener("hyperspace", notify)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[dict[str, object]]:
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

        # Delay the import to avoid the app startup cycle.
        from app.routes import render_fragment

        fragments: dict[str, bytes] = {}
        changed = asyncio.Condition()
        for table in (Brick.Meta.table, Player.Meta.table, Cursor.Meta.table):
            html = await render_fragment(table)
            if html is not None:
                fragments[table] = html

        async def refresh_fragments() -> None:
            """
            Refresh each fragment PostgreSQL says may have changed.
            """
            async for table in listen_to_postgres(pg):
                html = await render_fragment(table)
                if html is None:
                    continue
                async with changed:
                    fragments[table] = html
                    changed.notify_all()

        refresher = asyncio.create_task(refresh_fragments())

        yield {
            "fragments": fragments,
            "fragments_changed": changed,
        }

        refresher.cancel()
        try:
            await refresher
        except asyncio.CancelledError:
            pass
        await pg.close()
