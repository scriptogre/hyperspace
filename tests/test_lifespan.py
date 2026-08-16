import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock

from app import lifespan
from tests import run_async


class Postgres:
    def __init__(self):
        self.notify = None

    async def add_listener(self, _, notify):
        self.notify = notify

    async def remove_listener(self, _, __):
        self.notify = None


def test_postgres_listener_coalesces_named_changes():
    async def collect():
        postgres = Postgres()
        changes = lifespan.listen_for_postgres_notifications(postgres)
        pending = asyncio.create_task(anext(changes))
        await asyncio.sleep(0)
        postgres.notify(None, None, None, "bricks_changed")
        postgres.notify(None, None, None, "cursors_changed")
        result = await pending
        await changes.aclose()
        return result

    assert run_async(collect()) == {"bricks_changed", "cursors_changed"}


def test_cursor_changes_only_query_and_publish_cursors(monkeypatch):
    async def notifications(_):
        yield {"cursors_changed"}
        await asyncio.Event().wait()

    get_cursors = AsyncMock(return_value=[])
    get_world_context = AsyncMock()
    render = MagicMock(return_value="<div id='cursors'></div>")
    publish = MagicMock()
    monkeypatch.setattr(lifespan, "listen_for_postgres_notifications", notifications)
    monkeypatch.setattr(lifespan, "get_cursors", get_cursors)
    monkeypatch.setattr(lifespan, "get_world_context", get_world_context)
    monkeypatch.setattr(lifespan, "render", render)
    monkeypatch.setattr(lifespan.broadcast, "publish", publish)

    async def forward():
        task = asyncio.create_task(lifespan.forward_world_changes(MagicMock()))
        while not publish.called:
            await asyncio.sleep(0)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    run_async(forward())

    get_cursors.assert_awaited_once_with()
    get_world_context.assert_not_awaited()
    render.assert_called_once_with("_cursors.html", {"cursors": []})
    publish.assert_called_once_with("_cursors.html", "<div id='cursors'></div>")
