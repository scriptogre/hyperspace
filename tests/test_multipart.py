import asyncio
from concurrent.futures import ThreadPoolExecutor

from multipart_response.fastapi import MultipartResponse

from app import routes


def test_stream_endpoint_emits_a_multipart_part(monkeypatch):
    monkeypatch.setattr(routes, "render", lambda name, context: "<p>Ready</p>")

    async def get_brick_stacks():
        return {1: {1: []}}

    monkeypatch.setattr(routes, "get_brick_stacks", get_brick_stacks)

    async def postgres_updates():
        yield "bricks"

    async def collect_part():
        parts = [part async for part in routes.stream_endpoint(postgres_updates())]
        assert len(parts) == 1
        return parts[0]

    with ThreadPoolExecutor(max_workers=1) as executor:
        part = executor.submit(asyncio.run, collect_part()).result()

    response = MultipartResponse([part], boundary="test-boundary")
    body = response.body

    assert b"content-type: text/html; charset=utf-8\r\n" in body
    assert b"content-length: 12\r\n" in body
    assert b"hx-target: #bricks\r\n" in body
    assert b"hx-swap: outerMorph\r\n" in body
    assert b"\r\n<p>Ready</p>\r\n--test-boundary--\r\n" in body


def test_cursor_notification_emits_only_the_cursor_part(monkeypatch):
    monkeypatch.setattr(routes, "render", lambda name, context: "<p>Cursors</p>")

    async def get_cursors():
        return []

    monkeypatch.setattr(routes, "get_cursors", get_cursors)

    async def postgres_updates():
        yield "cursors"

    async def collect_parts():
        return [part async for part in routes.stream_endpoint(postgres_updates())]

    with ThreadPoolExecutor(max_workers=1) as executor:
        parts = executor.submit(asyncio.run, collect_parts()).result()

    response = MultipartResponse(parts, boundary="test-boundary")

    assert len(parts) == 1
    assert b"hx-target: #cursors\r\n" in response.body
    assert b"hx-target: #bricks\r\n" not in response.body
