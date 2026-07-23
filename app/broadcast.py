"""Broadcast rendered templates to connected subscribers."""

import asyncio
from collections.abc import AsyncIterator
from compression.zstd import ZstdCompressor
from dataclasses import dataclass

from multipart_response import MultipartWriter
from multipart_response.starlette import Part
from starlette.responses import StreamingResponse

BOUNDARY = b"hyperspace-4b8f7c2d1e6a9035"
QUEUE_SIZE = 16

_PART_HEADERS = {
    "_bricks.html": {"HX-Target": "#bricks", "HX-Swap": "outerMorph"},
    "_players.html": {"HX-Target": "#players", "HX-Swap": "innerHTML"},
    "_cursors.html": {"HX-Target": "#cursors", "HX-Swap": "outerMorph"},
}


@dataclass(frozen=True)
class StreamChunk:
    identity: bytes
    zstd: bytes = b""


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[StreamChunk | None]
    compressed: bool


# TODO: Replace this with MultipartResponse
class SharedStream:
    """Serialize and compress each update once for every subscriber."""

    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self.queue_size = queue_size
        self.subscribers: set[Subscriber] = set()
        self.latest: dict[str, bytes] = {}
        self.compressor = ZstdCompressor(level=6)
        self.compressor_started = False

    def publish(self, template_name: str, html: bytes) -> None:
        part = Part(html, headers=_PART_HEADERS[template_name], media_type="text/html")
        multipart_part = part.as_multipart_part()
        writer = MultipartWriter(BOUNDARY)
        identity = b"\r\n" + writer.start_part(multipart_part.headers)
        identity += bytes(writer.write_body(html))
        self.latest[template_name] = identity
        self._send(identity)

    async def subscribe(self, compressed: bool) -> AsyncIterator[bytes]:
        if compressed:
            self._start_epoch()

        subscriber = Subscriber(asyncio.Queue(self.queue_size), compressed)
        self.subscribers.add(subscriber)

        if compressed:
            for identity in self.latest.values():
                self._send(identity, compressed_only=True)
        else:
            for identity in self.latest.values():
                subscriber.queue.put_nowait(StreamChunk(identity))

        try:
            while True:
                chunk = await subscriber.queue.get()
                if chunk is None:
                    return
                data = chunk.zstd if compressed else chunk.identity
                if data:
                    yield data
        finally:
            self.subscribers.discard(subscriber)

    def _start_epoch(self) -> None:
        if self.compressor_started:
            frame_end = self.compressor.flush(ZstdCompressor.FLUSH_FRAME)
            self._fan_out(StreamChunk(b"", frame_end), compressed_only=True)
            self.compressor = ZstdCompressor(level=6)
            self.compressor_started = False

    def _send(self, identity: bytes, compressed_only: bool = False) -> None:
        zstd = b""
        if any(subscriber.compressed for subscriber in self.subscribers):
            zstd = self.compressor.compress(
                identity,
                mode=ZstdCompressor.FLUSH_BLOCK,
            )
            self.compressor_started = True
        self._fan_out(StreamChunk(identity, zstd), compressed_only)

    def _fan_out(self, chunk: StreamChunk, compressed_only: bool = False) -> None:
        for subscriber in tuple(self.subscribers):
            if compressed_only and not subscriber.compressed:
                continue
            if subscriber.queue.full():
                self.subscribers.discard(subscriber)
                while not subscriber.queue.empty():
                    subscriber.queue.get_nowait()
                subscriber.queue.put_nowait(None)
            else:
                subscriber.queue.put_nowait(chunk)


shared_stream = SharedStream()


def publish_template(template_name: str, html: bytes) -> None:
    shared_stream.publish(template_name, html)


def create_streaming_response(compressed: bool) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if compressed:
        headers["Content-Encoding"] = "zstd"

    return StreamingResponse(
        shared_stream.subscribe(compressed),
        media_type=f"multipart/mixed; boundary={BOUNDARY.decode()}",
        headers=headers,
    )
