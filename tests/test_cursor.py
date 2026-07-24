from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tortoise import transactions

from app import dependencies, services
from tests import run_async


def mock_cursor_transaction(monkeypatch, *, is_online: bool):
    @asynccontextmanager
    async def transaction(connection_name=None):
        yield

    get_player = AsyncMock(return_value=SimpleNamespace(id=7, is_online=is_online))
    player_query = MagicMock()
    player_query.get = get_player
    select_for_update = MagicMock(return_value=player_query)
    monkeypatch.setattr(transactions, "in_transaction", transaction)
    monkeypatch.setattr(services.Player, "select_for_update", select_for_update)
    return get_player


def test_cursor_update_upserts_position_for_online_player(monkeypatch):
    get_player = mock_cursor_transaction(monkeypatch, is_online=True)
    bulk_create = AsyncMock()
    monkeypatch.setattr(services.Cursor, "bulk_create", bulk_create)

    run_async(services.update_cursor(SimpleNamespace(id=7), 3, 4, -1))

    get_player.assert_awaited_once_with(id=7)
    bulk_create.assert_awaited_once()
    [cursor] = bulk_create.await_args.args[0]
    assert (cursor.x, cursor.y, cursor.z) == (3, 4, -1)
    assert bulk_create.await_args.kwargs == {
        "update_fields": ("x", "y", "z"),
        "on_conflict": ("player_id",),
    }


def test_cursor_update_ignores_offline_player(monkeypatch):
    mock_cursor_transaction(monkeypatch, is_online=False)
    bulk_create = AsyncMock()
    monkeypatch.setattr(services.Cursor, "bulk_create", bulk_create)

    run_async(services.update_cursor(SimpleNamespace(id=7), 3, 4, -1))

    bulk_create.assert_not_awaited()


def test_cursor_render_query_only_includes_online_players(monkeypatch):
    database = object()
    cursor_query = MagicMock()
    cursor_query.filter.return_value.order_by.return_value.values = AsyncMock(
        return_value=[]
    )
    cursor_all = MagicMock(return_value=cursor_query)
    monkeypatch.setattr(dependencies.Cursor, "all", cursor_all)

    assert run_async(dependencies.get_cursors(database, [])) == []
    cursor_all.assert_called_once_with(using_db=database)
    cursor_query.filter.assert_called_once_with(player__is_online=True)
