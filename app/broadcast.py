"""Broadcast rendered templates to connected subscribers."""

import asyncio
from collections import defaultdict
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


class Broadcast:
    """Serialize and broadcast rendered templates by name."""

    def __init__(self) -> None:
        self._subscribers: defaultdict[str, set[Subscriber]] = defaultdict(set)
        self._latest: dict[str, bytes] = {}
        self._snapshot_zstd: dict[str, bytes] = {}
        self._compressors: defaultdict[str, ZstdStreamCompressor] = defaultdict(
            ZstdStreamCompressor
        )
        self._writers: defaultdict[str, MultipartWriter] = defaultdict(
            lambda: MultipartWriter(BOUNDARY)
        )

    def publish(self, template_name: str, html: bytes) -> None:
        """Publish a complete rendered template."""
        identity = b"".join(
            self._writers[template_name].iterate_part(
                Part(html, media_type="text/html")
            )
        )
        self._latest[template_name] = identity
        self._snapshot_zstd.pop(template_name, None)
        self._send(template_name, identity)

    async def stream(
        self,
        template_name: str,
        *,
        compressed: bool,
    ) -> AsyncIterator[bytes]:
        """Replay the latest rendering, then stream new renderings."""
        if compressed:
            self._start_epoch(template_name)

        subscriber = Subscriber(asyncio.Queue(QUEUE_SIZE), compressed)
        subscribers = self._subscribers[template_name]
        subscribers.add(subscriber)
        latest = self._latest.get(template_name, b"")

        if compressed:
            if latest:
                if template_name not in self._snapshot_zstd:
                    self._snapshot_zstd[template_name] = compress_frame(latest)
                subscriber.queue.put_nowait(self._snapshot_zstd[template_name])
        elif latest:
            subscriber.queue.put_nowait(latest)

        try:
            while True:
                data = await subscriber.queue.get()
                if data is None:
                    return
                yield data
        finally:
            subscribers.discard(subscriber)

    def _start_epoch(self, template_name: str) -> None:
        compressor = self._compressors[template_name]
        if compressor.has_open_frame:
            frame_end = compressor.finish_frame()
            self._fan_out(template_name, b"", frame_end, compressed_only=True)

    def _send(self, template_name: str, identity: bytes) -> None:
        subscribers = self._subscribers[template_name]
        zstd = (
            self._compressors[template_name].compress(identity)
            if any(subscriber.compressed for subscriber in subscribers)
            else b""
        )
        self._fan_out(template_name, identity, zstd)

    def _fan_out(
        self,
        template_name: str,
        identity: bytes,
        zstd: bytes,
        compressed_only: bool = False,
    ) -> None:
        subscribers = self._subscribers[template_name]
        for subscriber in tuple(subscribers):
            if compressed_only and not subscriber.compressed:
                continue
            if subscriber.queue.full():
                subscribers.discard(subscriber)
                while not subscriber.queue.empty():
                    subscriber.queue.get_nowait()
                subscriber.queue.put_nowait(None)
            else:
                subscriber.queue.put_nowait(zstd if subscriber.compressed else identity)


broadcast = Broadcast()
