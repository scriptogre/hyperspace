from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import services
from tests import run_async


def test_cursor_update_upserts_position(monkeypatch):
    bulk_create = AsyncMock()
    monkeypatch.setattr(services.Cursor, "bulk_create", bulk_create)

    run_async(services.update_cursor(SimpleNamespace(id=7), 3, 4, -1))

    bulk_create.assert_awaited_once()
    [cursor] = bulk_create.await_args.args[0]
    assert (cursor.x, cursor.y, cursor.z) == (3, 4, -1)
    assert bulk_create.await_args.kwargs == {
        "update_fields": ("x", "y", "z"),
        "on_conflict": ("player_id",),
    }
