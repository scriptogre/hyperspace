import asyncio

from multipart_response.fastapi import MultipartResponse

from app import routes, updates


def test_table_update_renders_its_own_partial(monkeypatch):
    monkeypatch.setattr(updates, "render", lambda name, context: name)

    async def get_brick_stacks():
        return {}

    async def get_players():
        return []

    async def get_cursors():
        return []

    monkeypatch.setattr(updates, "get_brick_stacks", get_brick_stacks)
    monkeypatch.setattr(updates, "get_players", get_players)
    monkeypatch.setattr(updates, "get_cursors", get_cursors)

    async def render_all():
        return [
            await updates.render_update("bricks"),
            await updates.render_update("players"),
            await updates.render_update("cursors"),
            await updates.render_update("events"),
        ]

    assert asyncio.run(render_all()) == [
        ("_bricks.html", "#bricks", "outerMorph"),
        ("_players.html", "#players", "innerHTML"),
        ("_cursors.html", "#cursors", "outerMorph"),
        None,
    ]


def test_stream_wraps_rendered_update_in_a_multipart_part(monkeypatch):
    async def rendered_updates():
        yield "<p>Ready</p>", "#bricks", "outerMorph"

    monkeypatch.setattr(routes, "get_rendered_updates", rendered_updates)

    async def collect_part():
        parts = [part async for part in routes.stream_endpoint()]
        assert len(parts) == 1
        return parts[0]

    part = asyncio.run(collect_part())
    response = MultipartResponse([part], boundary="test-boundary")

    assert b"content-type: text/html; charset=utf-8\r\n" in response.body
    assert b"content-length: 12\r\n" in response.body
    assert b"hx-target: #bricks\r\n" in response.body
    assert b"hx-swap: outerMorph\r\n" in response.body
    assert b"\r\n<p>Ready</p>\r\n--test-boundary--\r\n" in response.body
