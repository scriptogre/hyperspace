"""Application lifespan: DB init, NOTIFY listener, broadcast + cursor-flush loops."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app import routes, services
from app.config import settings

_NOTIFY_FN = """
CREATE OR REPLACE FUNCTION hyperspace_notify() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('hyperspace', TG_TABLE_NAME);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

_TABLES = ("brick", "user", "cursor", "event")
_TRIGGER_LOCK = 0x68797073  # serialize trigger DDL across workers

# Postgres stamps every cursor write with a monotonic version, so "what changed
# since X" is a single indexed WHERE clause. The database is the change feed.
_CURSOR_VERSION = """
CREATE SEQUENCE IF NOT EXISTS cursor_version_seq;
CREATE OR REPLACE FUNCTION stamp_cursor_version() RETURNS trigger AS $$
BEGIN
  NEW.version := nextval('cursor_version_seq');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS cursor_version ON cursor;
CREATE TRIGGER cursor_version BEFORE INSERT OR UPDATE ON cursor
  FOR EACH ROW EXECUTE FUNCTION stamp_cursor_version();
CREATE INDEX IF NOT EXISTS cursor_version_idx ON cursor (version);
"""


async def _install_triggers(pg: asyncpg.Connection) -> None:
    """NOTIFY 'hyperspace' with the table name on every write statement.

    Workers boot concurrently, so guard the DDL with an advisory lock to avoid
    racing DROP/CREATE TRIGGER on the same tables.
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
        await pg.execute(_CURSOR_VERSION)
    finally:
        await pg.execute("SELECT pg_advisory_unlock($1)", _TRIGGER_LOCK)


async def _cursor_flusher() -> None:
    """Batch-upsert buffered cursor writes on a fixed interval."""
    while True:
        await asyncio.sleep(services.CURSOR_FLUSH_INTERVAL)
        try:
            await services.flush_cursors()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with RegisterTortoise(app, config=settings.TORTOISE_ORM, generate_schemas=True):
        pg = await asyncpg.connect(settings.DATABASE_URL)
        await _install_triggers(pg)
        await services.load_players()

        async def on_notify(conn, pid, channel, payload):
            routes.mark_dirty(payload)

        await pg.add_listener("hyperspace", on_notify)

        task = asyncio.create_task(routes.broadcast_loop())
        flush_task = asyncio.create_task(_cursor_flusher())
        yield

        for running in (task, flush_task):
            running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass
        await pg.remove_listener("hyperspace", on_notify)
        await pg.close()
