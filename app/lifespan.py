"""Application lifespan: DB init and Postgres notification forwarding."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app.broadcast import broadcast
from app.config import settings
from app.dependencies import get_cursors, get_world_context
from app.jinja import render
from app.models import Brick, Cursor, Player


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """Start the DB and render the complete world after each change."""
    async with RegisterTortoise(
        app, config=settings.TORTOISE_ORM, generate_schemas=False
    ):
        await Brick.all().update(dragged_by_id=None)
        await Player.all().update(is_online=False)
        await Cursor.all().delete()

        postgres = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
        )

        forwarder = asyncio.create_task(forward_world_changes(postgres))

        try:
            yield
        finally:
            forwarder.cancel()
            try:
                await forwarder
            except asyncio.CancelledError:
                pass
            await postgres.close()


async def forward_world_changes(postgres: asyncpg.Connection) -> None:
    """Render and publish changed templates at most 60 times per second."""
    loop = asyncio.get_running_loop()
    next_render = 0.0

    async for changes in listen_for_postgres_notifications(postgres):
        wait = next_render - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        next_render = loop.time() + (1 / 60)  # 60 Hz

        if changes == {"cursors_changed"}:
            broadcast.publish(
                "_cursors.html",
                render("_cursors.html", {"cursors": await get_cursors()}),
            )
            continue

        context = await get_world_context()
        if "worlds_changed" in changes:
            broadcast.publish(
                "_world_settings.html", render("_world_settings.html", context)
            )
            broadcast.publish(
                "_announcement.html", render("_announcement.html", context)
            )
        if "players_changed" in changes:
            broadcast.publish("_players.html", render("_players.html", context))
        if changes & {"worlds_changed", "bricks_changed"}:
            broadcast.publish("_bricks.html", render("_bricks.html", context))

        broadcast.publish(
            "_cursors.html",
            render("_cursors.html", {"cursors": await get_cursors()}),
        )


async def listen_for_postgres_notifications(
    postgres: asyncpg.Connection,
) -> AsyncIterator[set[str]]:
    """
    Yield coalesced change names from PostgreSQL.
    """

    notified = asyncio.Event()
    changes: set[str] = set()

    def notify(_, __, ___, payload: str) -> None:
        changes.add(payload)
        notified.set()

    await postgres.add_listener("hyperspace", notify)
    try:
        while True:
            await notified.wait()
            notified.clear()
            pending = changes.copy()
            changes.clear()
            yield pending
    finally:
        await postgres.remove_listener("hyperspace", notify)
