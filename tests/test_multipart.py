import asyncio

import pytest
from multipart_response.fastapi import MultipartResponse

from app import routes
from app.broadcast import publish_template, subscribe_to_templates
from tests import run_async


def test_published_template_reaches_subscriber():
    async def publish_one():
        subscription = subscribe_to_templates()
        collector = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        publish_template("_bricks.html", b"<div></div>")
        template = await collector
        await subscription.aclose()
        return template

    assert run_async(publish_one()) == ("_bricks.html", b"<div></div>")


@pytest.mark.parametrize(
    ("template_name", "target", "swap"),
    [
        ("_bricks.html", "#bricks", "outerMorph"),
        ("_players.html", "#players", "innerHTML"),
        ("_cursors.html", "#cursors", "outerMorph"),
    ],
)
def test_stream_routes_fragment(monkeypatch, template_name, target, swap):
    async def subscribe_to_templates():
        yield template_name, b"<p>Ready</p>"

    monkeypatch.setattr(routes, "subscribe_to_templates", subscribe_to_templates)

    async def collect_part():
        parts = [part async for part in routes.stream()]
        assert len(parts) == 1
        return parts[0]

    part = run_async(collect_part())
    response = MultipartResponse([part], boundary="test-boundary")

    assert f"hx-target: {target}\r\n".encode() in response.body
    assert f"hx-swap: {swap}\r\n".encode() in response.body
    assert b"\r\n<p>Ready</p>\r\n--test-boundary--\r\n" in response.body
