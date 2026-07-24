"""Application lifespan: DB init and Postgres notification forwarding."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from app.broadcast import publish_template
from app.config import settings
from app.dependencies import get_brick_stacks, get_cursors, get_players
from app.jinja import render
from app.models import Brick, Cursor, Player


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """
    Start the DB and NOTIFY listener for the app's lifetime.
    """
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

        # TODO: Find a more elgant way to do this
        async def forward_postgres_notifications() -> None:
            async for table_name in listen_to_postgres(postgres):
                if table_name == "bricks":
                    template_name = "_bricks.html"
                    context = {"brick_stacks": await get_brick_stacks()}
                elif table_name == "players":
                    template_name = "_players.html"
                    context = {"players": await get_players()}
                elif table_name == "cursors":
                    template_name = "_cursors.html"
                    context = {"cursors": await get_cursors()}
                else:
                    continue

                html = render(template_name, context).encode()
                publish_template(template_name, html)

        forwarder = asyncio.create_task(forward_postgres_notifications())

        try:
            yield
        finally:
            forwarder.cancel()
            try:
                await forwarder
            except asyncio.CancelledError:
                pass
            await postgres.close()


async def listen_to_postgres(
    postgres: asyncpg.Connection,
) -> AsyncIterator[str]:
    """
    Yield (coalesced) notifications from Postgres LISTEN/NOTIFY.
    """
    notified = asyncio.Event()
    pending: set[str] = set()

    def notify(_, __, ___, notification):
        pending.add(notification)
        notified.set()

    await postgres.add_listener("hyperspace", notify)
    try:
        while True:
            await notified.wait()
            notified.clear()
            while pending:
                yield pending.pop()
    finally:
        await postgres.remove_listener("hyperspace", notify)
