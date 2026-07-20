import asyncio
from concurrent.futures import ThreadPoolExecutor

from multipart_response.fastapi import MultipartResponse

from app import routes


def test_updates_endpoint_emits_a_multipart_part(monkeypatch):
    monkeypatch.setattr(routes, "render", lambda name, context: "<p>Ready</p>")

    async def get_brick_stacks():
        return {1: {1: []}}

    monkeypatch.setattr(routes, "get_brick_stacks", get_brick_stacks)

    async def collect_part():
        queue = asyncio.Queue()
        queue.put_nowait("bricks")
        stream = routes.updates_endpoint(queue)
        part = await anext(stream)
        await stream.aclose()
        return part

    with ThreadPoolExecutor(max_workers=1) as executor:
        part = executor.submit(asyncio.run, collect_part()).result()

    response = MultipartResponse([part], boundary="test-boundary")
    body = response.body

    assert b"content-type: text/html; charset=utf-8\r\n" in body
    assert b"content-length: 12\r\n" in body
    assert b"hx-target: #brick-list\r\n" in body
    assert b"hx-swap: outerMorph\r\n" in body
    assert b"\r\n<p>Ready</p>\r\n--test-boundary--\r\n" in body
