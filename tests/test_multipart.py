import asyncio
from compression.zstd import ZstdDecompressor
from unittest.mock import MagicMock, call

import pytest

from app import routes
from app.broadcast import BOUNDARY, QUEUE_SIZE, Broadcast
from tests import run_async

BRICKS_STREAM = {"_bricks.html": {"HX-Target": "#bricks"}}
APP_STREAM = {
    "_world_settings.html": {"HX-Target": "#world-settings"},
    "_announcement.html": {"HX-Target": "#announcement"},
    "_players.html": {"HX-Target": "#players"},
    "_bricks.html": {"HX-Target": "#bricks"},
    "_cursors.html": {"HX-Target": "#cursors"},
}


def test_identity_stream_serializes_template_part():
    async def collect():
        broadcast = Broadcast()
        subscription = broadcast.stream(BRICKS_STREAM, compressed=False)
        pending = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        broadcast.publish("_bricks.html", "<div id='bricks'>Ready</div>")
        chunk = await pending
        await subscription.aclose()
        return chunk

    chunk = run_async(collect())

    assert chunk.startswith(b"--" + BOUNDARY + b"\r\n")
    assert chunk.endswith(b"\r\n\r\n<div id='bricks'>Ready</div>")


def test_stream_composes_templates_with_route_headers():
    async def collect():
        broadcast = Broadcast()
        broadcast.publish("_bricks.html", "Bricks")
        broadcast.publish("_cursors.html", "Cursors")
        subscription = broadcast.stream(
            {
                "_bricks.html": {"HX-Target": "#bricks"},
                "_cursors.html": {"HX-Target": "#cursors"},
            },
            compressed=False,
        )
        snapshot = await anext(subscription)
        await subscription.aclose()
        return snapshot

    snapshot = run_async(collect())

    assert snapshot.count(b"--" + BOUNDARY) == 2
    assert b"hx-target: #bricks" in snapshot
    assert b"hx-target: #cursors" in snapshot
    assert b"Bricks" in snapshot
    assert b"Cursors" in snapshot


def test_zstd_stream_keeps_history_between_template_updates():
    async def collect():
        broadcast = Broadcast()
        subscription = broadcast.stream(
            {
                "_bricks.html": {"HX-Target": "#bricks"},
                "_cursors.html": {"HX-Target": "#cursors"},
            },
            compressed=True,
        )
        first = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        broadcast.publish("_bricks.html", "<div id='bricks'>First</div>")
        first_chunk = await first

        second = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        broadcast.publish("_cursors.html", "<div id='cursors'>Second</div>")
        second_chunk = await second
        await subscription.aclose()
        return first_chunk, second_chunk

    first, second = run_async(collect())
    decompressor = ZstdDecompressor()

    assert b"First" in decompressor.decompress(first)
    assert b"Second" in decompressor.decompress(second)
    assert not decompressor.eof


def test_late_join_replays_latest_template_only_to_new_subscriber():
    async def collect():
        broadcast = Broadcast()
        first_subscription = broadcast.stream(BRICKS_STREAM, compressed=True)
        first_pending = asyncio.create_task(anext(first_subscription))
        await asyncio.sleep(0)
        broadcast.publish("_bricks.html", "<div id='bricks'>Current</div>")
        first_chunk = await first_pending

        second_subscription = broadcast.stream(BRICKS_STREAM, compressed=True)
        second_pending = asyncio.create_task(anext(second_subscription))
        await asyncio.sleep(0)
        frame_end = await anext(first_subscription)
        second_snapshot = await second_pending

        first_next_pending = asyncio.create_task(anext(first_subscription))
        second_next_pending = asyncio.create_task(anext(second_subscription))
        await asyncio.sleep(0)
        assert not first_next_pending.done()
        assert not second_next_pending.done()

        broadcast.publish("_bricks.html", "<div id='bricks'>Next</div>")
        first_next = await first_next_pending
        second_next = await second_next_pending
        await first_subscription.aclose()
        await second_subscription.aclose()
        return first_chunk, frame_end, second_snapshot, first_next, second_next

    first, frame_end, second_snapshot, first_next, second_next = run_async(collect())

    old_epoch = ZstdDecompressor()
    assert b"Current" in old_epoch.decompress(first)
    assert old_epoch.decompress(frame_end) == b""
    assert old_epoch.eof

    snapshot = ZstdDecompressor()
    assert b"Current" in snapshot.decompress(second_snapshot)
    assert snapshot.eof

    assert first_next == second_next
    new_epoch = ZstdDecompressor()
    assert b"Next" in new_epoch.decompress(first_next)


def test_queue_overflow_disconnects_and_replay_catches_up():
    async def collect():
        broadcast = Broadcast()
        subscription = broadcast.stream(BRICKS_STREAM, compressed=False)
        first_pending = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        broadcast.publish("_bricks.html", "<div id='bricks'>First</div>")
        await first_pending

        for index in range(QUEUE_SIZE):
            broadcast.publish("_bricks.html", f"<div>Pending {index}</div>")
        broadcast.publish("_bricks.html", "<div id='bricks'>Latest</div>")
        with pytest.raises(StopAsyncIteration):
            await anext(subscription)

        reconnected = broadcast.stream(BRICKS_STREAM, compressed=False)
        latest = await anext(reconnected)
        await reconnected.aclose()
        return latest

    assert b"Latest" in run_async(collect())


def test_stream_sets_template_targets_and_negotiates_zstd(monkeypatch):
    stream = MagicMock(side_effect=lambda *_args, **_kwargs: iter(()))
    monkeypatch.setattr(routes.broadcast, "stream", stream)

    compressed = run_async(routes.stream("gzip, deflate, br, zstd"))
    identity = run_async(routes.stream("gzip, deflate, br"))

    assert stream.call_args_list == [
        call(APP_STREAM, compressed=True),
        call(APP_STREAM, compressed=False),
    ]
    assert compressed.headers["content-encoding"] == "zstd"
    assert "content-encoding" not in identity.headers
    assert "hx-target" not in compressed.headers
    assert "hx-target" not in identity.headers
    assert compressed.headers["hx-swap"] == identity.headers["hx-swap"] == "outerMorph"
    assert compressed.headers["content-type"] == (
        f"multipart/mixed; boundary={BOUNDARY.decode()}"
    )
    assert compressed.headers["vary"] == "Accept-Encoding"
