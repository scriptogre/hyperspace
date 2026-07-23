import asyncio
from compression.zstd import ZstdDecompressor

import pytest

from app import routes
from app.broadcast import BOUNDARY, SharedStream
from tests import run_async


@pytest.mark.parametrize(
    ("template_name", "target", "swap"),
    [
        ("_bricks.html", "#bricks", "outerMorph"),
        ("_players.html", "#players", "innerHTML"),
        ("_cursors.html", "#cursors", "outerMorph"),
    ],
)
def test_identity_stream_serializes_shared_part(template_name, target, swap):
    async def collect():
        stream = SharedStream()
        subscription = stream.subscribe(compressed=False)
        pending = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        stream.publish(template_name, b"<p>Ready</p>")
        chunk = await pending
        await subscription.aclose()
        return chunk

    chunk = run_async(collect())

    assert chunk.startswith(b"\r\n--" + BOUNDARY + b"\r\n")
    assert f"hx-target: {target}\r\n".encode() in chunk
    assert f"hx-swap: {swap}\r\n".encode() in chunk
    assert chunk.endswith(b"\r\n\r\n<p>Ready</p>")


def test_zstd_stream_keeps_history_between_updates():
    async def collect():
        stream = SharedStream()
        subscription = stream.subscribe(compressed=True)
        first = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        stream.publish("_bricks.html", b"<p>First</p>")
        first_chunk = await first

        second = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        stream.publish("_bricks.html", b"<p>Second</p>")
        second_chunk = await second
        await subscription.aclose()
        return first_chunk, second_chunk

    first, second = run_async(collect())
    decompressor = ZstdDecompressor()

    assert b"<p>First</p>" in decompressor.decompress(first)
    assert b"<p>Second</p>" in decompressor.decompress(second)
    assert not decompressor.eof


def test_late_join_replays_latest_part_only_to_new_subscriber():
    async def collect():
        stream = SharedStream()
        first_subscription = stream.subscribe(compressed=True)
        first_pending = asyncio.create_task(anext(first_subscription))
        await asyncio.sleep(0)
        stream.publish("_bricks.html", b"<p>Current</p>")
        first_chunk = await first_pending

        second_subscription = stream.subscribe(compressed=True)
        second_pending = asyncio.create_task(anext(second_subscription))
        await asyncio.sleep(0)
        frame_end = await anext(first_subscription)
        second_snapshot = await second_pending

        first_next_pending = asyncio.create_task(anext(first_subscription))
        second_next_pending = asyncio.create_task(anext(second_subscription))
        await asyncio.sleep(0)
        assert not first_next_pending.done()
        assert not second_next_pending.done()

        stream.publish("_bricks.html", b"<p>Next</p>")
        first_next = await first_next_pending
        second_next = await second_next_pending
        await first_subscription.aclose()
        await second_subscription.aclose()
        return first_chunk, frame_end, second_snapshot, first_next, second_next

    first, frame_end, second_snapshot, first_next, second_next = run_async(collect())

    old_epoch = ZstdDecompressor()
    assert b"<p>Current</p>" in old_epoch.decompress(first)
    assert old_epoch.decompress(frame_end) == b""
    assert old_epoch.eof

    snapshot = ZstdDecompressor()
    assert b"<p>Current</p>" in snapshot.decompress(second_snapshot)
    assert snapshot.eof

    assert first_next == second_next
    new_epoch = ZstdDecompressor()
    assert b"<p>Next</p>" in new_epoch.decompress(first_next)


def test_queue_overflow_disconnects_and_replay_catches_up():
    async def collect():
        stream = SharedStream(queue_size=1)
        subscription = stream.subscribe(compressed=False)
        first_pending = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        stream.publish("_bricks.html", b"<p>First</p>")
        await first_pending

        stream.publish("_bricks.html", b"<p>Second</p>")
        stream.publish("_bricks.html", b"<p>Latest</p>")
        with pytest.raises(StopAsyncIteration):
            await anext(subscription)

        reconnected = stream.subscribe(compressed=False)
        latest = await anext(reconnected)
        await reconnected.aclose()
        return latest

    assert b"<p>Latest</p>" in run_async(collect())


def test_stream_negotiates_zstd_from_injected_header():
    compressed = run_async(routes.stream("gzip, deflate, br, zstd"))
    identity = run_async(routes.stream("gzip, deflate, br"))

    assert compressed.headers["content-encoding"] == "zstd"
    assert "content-encoding" not in identity.headers
    assert compressed.headers["content-type"] == (
        f"multipart/mixed; boundary={BOUNDARY.decode()}"
    )
    assert compressed.headers["vary"] == "Accept-Encoding"
