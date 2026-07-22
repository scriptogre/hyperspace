import asyncio

import pytest
from multipart_response.fastapi import MultipartResponse

from app import routes


def test_table_notification_renders_its_fragment(monkeypatch):
    monkeypatch.setattr(routes, "render", lambda name, context: name)

    async def get_brick_stacks():
        return {}

    async def get_players():
        return []

    async def get_cursors():
        return []

    monkeypatch.setattr(routes, "get_brick_stacks", get_brick_stacks)
    monkeypatch.setattr(routes, "get_players", get_players)
    monkeypatch.setattr(routes, "get_cursors", get_cursors)

    async def render_all():
        return [
            await routes.render_fragment("bricks"),
            await routes.render_fragment("players"),
            await routes.render_fragment("cursors"),
            await routes.render_fragment("events"),
        ]

    assert asyncio.run(render_all()) == [
        b"_bricks.html",
        b"_players.html",
        b"_cursors.html",
        None,
    ]


@pytest.mark.parametrize(
    ("table", "target", "swap"),
    [
        ("bricks", "#bricks", "outerMorph"),
        ("players", "#players", "innerHTML"),
        ("cursors", "#cursors", "outerMorph"),
    ],
)
def test_stream_routes_fragment(table, target, swap):
    async def fragments():
        yield table, b"<p>Ready</p>"

    async def collect_part():
        parts = [part async for part in routes.stream(fragments())]
        assert len(parts) == 1
        return parts[0]

    part = asyncio.run(collect_part())
    response = MultipartResponse([part], boundary="test-boundary")

    assert b"content-type: text/html; charset=utf-8\r\n" in response.body
    assert b"content-length: 12\r\n" in response.body
    assert f"hx-target: {target}\r\n".encode() in response.body
    assert f"hx-swap: {swap}\r\n".encode() in response.body
    assert b"\r\n<p>Ready</p>\r\n--test-boundary--\r\n" in response.body
