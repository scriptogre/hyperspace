"""Application lifespan: DB init and shared update renderer."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import settings
from app.models import Brick, Cursor, Player


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
        app, config=settings.TORTOISE_ORM, generate_schemas=False
    ):
        # Release drags and sessions orphaned by ungraceful shutdown
        await Brick.all().update(dragged_by_id=None)
        await Player.all().update(is_online=False)

        pg = await asyncpg.connect(settings.DATABASE_URL)

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
