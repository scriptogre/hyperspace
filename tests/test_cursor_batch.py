import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import services
from tests import run_async


def test_cursor_updates_share_one_bulk_write(monkeypatch):
    bulk_create = AsyncMock()
    monkeypatch.setattr(services.Cursor, "bulk_create", bulk_create)

    async def update_all():
        await asyncio.gather(
            *(
                services.update_cursor(
                    SimpleNamespace(id=player_id),
                    player_id % 12,
                    0,
                    -1,
                )
                for player_id in range(1, 101)
            )
        )

    run_async(update_all())

    bulk_create.assert_awaited_once()
    cursors = bulk_create.await_args.args[0]
    assert len(cursors) == 100
    assert bulk_create.await_args.kwargs == {
        "update_fields": ("x", "y", "z"),
        "on_conflict": ("player_id",),
    }


def test_cursor_batch_keeps_each_players_latest_position(monkeypatch):
    bulk_create = AsyncMock()
    monkeypatch.setattr(services.Cursor, "bulk_create", bulk_create)
    player = SimpleNamespace(id=1)

    async def update_all():
        await asyncio.gather(
            services.update_cursor(player, 1, 1, -1),
            services.update_cursor(player, 2, 2, -1),
            services.update_cursor(player, 3, 3, -1),
        )

    run_async(update_all())

    bulk_create.assert_awaited_once()
    cursors = bulk_create.await_args.args[0]
    assert len(cursors) == 1
    assert (cursors[0].x, cursors[0].y, cursors[0].z) == (3, 3, -1)
