"""Broadcast rendered templates to connected subscribers."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from multipart_response import MultipartWriter
from multipart_response.starlette import Part

from app.compression import ZstdStreamCompressor, compress_frame

BOUNDARY = b"hyperspace-4b8f7c2d1e6a9035"
QUEUE_SIZE = 16


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[bytes | None]
    compressed: bool


class SharedStream:
    """Serialize and compress each update once for every subscriber."""

    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self.queue_size = queue_size
        self.subscribers: set[Subscriber] = set()
        self.latest = b""
        self.snapshot_zstd = b""
        self.compressor = ZstdStreamCompressor()
        self.writer = MultipartWriter(BOUNDARY)

    def publish(self, html: bytes) -> None:
        identity = b"".join(
            self.writer.iterate_part(Part(html, media_type="text/html"))
        )
        self.latest = identity
        self.snapshot_zstd = b""
        self._send(identity)

    async def subscribe(self, compressed: bool) -> AsyncIterator[bytes]:
        if compressed:
            self._start_epoch()

        subscriber = Subscriber(asyncio.Queue(self.queue_size), compressed)
        self.subscribers.add(subscriber)

        if compressed:
            if self.latest:
                if not self.snapshot_zstd:
                    self.snapshot_zstd = compress_frame(self.latest)
                subscriber.queue.put_nowait(self.snapshot_zstd)
        elif self.latest:
            subscriber.queue.put_nowait(self.latest)

        try:
            while True:
                data = await subscriber.queue.get()
                if data is None:
                    return
                yield data
        finally:
            self.subscribers.discard(subscriber)

    def _start_epoch(self) -> None:
        if self.compressor.has_open_frame:
            frame_end = self.compressor.finish_frame()
            self._fan_out(b"", frame_end, compressed_only=True)

    def _send(self, identity: bytes) -> None:
        zstd = (
            self.compressor.compress(identity)
            if any(subscriber.compressed for subscriber in self.subscribers)
            else b""
        )
        self._fan_out(identity, zstd)

    def _fan_out(
        self,
        identity: bytes,
        zstd: bytes,
        compressed_only: bool = False,
    ) -> None:
        for subscriber in tuple(self.subscribers):
            if compressed_only and not subscriber.compressed:
                continue
            if subscriber.queue.full():
                self.subscribers.discard(subscriber)
                while not subscriber.queue.empty():
                    subscriber.queue.get_nowait()
                subscriber.queue.put_nowait(None)
            else:
                subscriber.queue.put_nowait(zstd if subscriber.compressed else identity)


shared_stream = SharedStream()


def publish_world(html: bytes) -> None:
    shared_stream.publish(html)
