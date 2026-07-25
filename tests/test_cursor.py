from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import dependencies, services
from app.exceptions import PlayerRequired
from tests import run_async


def mock_cursor_query(monkeypatch, *, player_exists: bool) -> AsyncMock:
    execute = AsyncMock(return_value=[{"player_exists": player_exists}])
    connection = SimpleNamespace(execute_query_dict=execute)
    connections = SimpleNamespace(get=MagicMock(return_value=connection))
    monkeypatch.setattr(services, "connections", connections)
    return execute


def test_cursor_update_uses_one_statement(monkeypatch):
    execute = mock_cursor_query(monkeypatch, player_exists=True)

    run_async(services.update_cursor("session-token", 3, 4, -1))

    execute.assert_awaited_once_with(
        services.CURSOR_UPDATE_SQL,
        ["session-token", 3, 4, -1],
    )


def test_cursor_update_rejects_unknown_player(monkeypatch):
    mock_cursor_query(monkeypatch, player_exists=False)

    with pytest.raises(PlayerRequired):
        run_async(services.update_cursor("unknown", 3, 4, -1))


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
