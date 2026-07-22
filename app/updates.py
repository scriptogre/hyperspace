"""Render each database update once and share it with every stream."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg

from app.dependencies import get_brick_stacks, get_cursors, get_players
from app.jinja import render
from app.models import Brick, Cursor, Player

RenderedUpdate = tuple[str, str, str]
_TABLES = (Brick.Meta.table, Player.Meta.table, Cursor.Meta.table)
_condition = asyncio.Condition()
_latest: dict[str, tuple[int, RenderedUpdate]] = {}
_version = 0


async def render_update(table: str) -> RenderedUpdate | None:
    if table == Brick.Meta.table:
        return (
            render("_bricks.html", {"brick_stacks": await get_brick_stacks()}),
            "#bricks",
            "outerMorph",
        )
    if table == Player.Meta.table:
        return (
            render("_players.html", {"players": await get_players()}),
            "#players",
            "innerHTML",
        )
    if table == Cursor.Meta.table:
        return (
            render("_cursors.html", {"cursors": await get_cursors()}),
            "#cursors",
            "outerMorph",
        )
    return None


async def run_updates(postgres: asyncpg.Connection) -> None:
    """Listen once, coalesce table names, and publish one render per table."""
    global _latest, _version

    changed = set(_TABLES)
    wake = asyncio.Event()
    wake.set()

    def notify(conn, pid, channel, payload):
        changed.add(payload)
        wake.set()

    async with _condition:
        _latest = {}
        _version = 0

    await postgres.add_listener("hyperspace", notify)
    try:
        while True:
            await wake.wait()
            wake.clear()
            pending, changed = changed, set()
            for table in _TABLES:
                if table not in pending:
                    continue
                update = await render_update(table)
                if update is None:
                    continue
                async with _condition:
                    _version += 1
                    _latest[table] = (_version, update)
                    _condition.notify_all()
    finally:
        await postgres.remove_listener("hyperspace", notify)


async def get_rendered_updates() -> AsyncIterator[RenderedUpdate]:
    """Yield each unseen latest part. Slow streams skip superseded renders."""
    seen: dict[str, int] = {}
    while True:
        async with _condition:
            await _condition.wait_for(
                lambda: any(
                    version > seen.get(table, 0)
                    for table, (version, _) in _latest.items()
                )
            )
            pending = sorted(
                (
                    (version, table, update)
                    for table, (version, update) in _latest.items()
                    if version > seen.get(table, 0)
                ),
                key=lambda item: item[0],
            )
            seen.update((table, version) for version, table, _ in pending)
        for _, _, update in pending:
            yield update
