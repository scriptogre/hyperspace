"""Broadcast rendered templates to connected subscribers."""

import asyncio
from collections.abc import AsyncIterator, Mapping
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
    """Serialize and broadcast rendered templates."""

    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._latest: dict[str, bytes] = {}
        self._snapshot = b""
        self._snapshot_zstd = b""
        self._compressor = ZstdStreamCompressor()
        self._writer = MultipartWriter(BOUNDARY)
        self._templates: dict[str, dict[str, str]] | None = None

    def publish(self, template_name: str, html: str) -> None:
        """
        Publish a complete rendered template.
        """
        encoded = html.encode()
        self._latest[template_name] = encoded
        if self._templates is None or template_name not in self._templates:
            return

        identity = b"".join(
            self._writer.iterate_part(
                Part(
                    encoded,
                    headers=self._templates[template_name],
                    media_type="text/html",
                )
            )
        )
        self._snapshot = b""
        self._snapshot_zstd = b""
        self._send(identity)

    async def stream(
        self,
        templates: Mapping[str, Mapping[str, str]],
        *,
        compressed: bool,
    ) -> AsyncIterator[bytes]:
        """Replay the latest templates, then stream new renderings."""
        configured_templates = {
            template_name: dict(headers) for template_name, headers in templates.items()
        }
        if not configured_templates:
            raise ValueError("At least one template is required")
        if self._templates is None:
            self._templates = configured_templates
            self._snapshot = self._serialize_snapshot(self._writer)
        elif self._templates != configured_templates:
            raise ValueError("Broadcast is already configured for different templates")

        if compressed:
            self._start_epoch()

        subscriber = Subscriber(asyncio.Queue(QUEUE_SIZE), compressed)
        self._subscribers.add(subscriber)
        if not self._snapshot:
            self._snapshot = self._serialize_snapshot(MultipartWriter(BOUNDARY))
        if self._snapshot:
            if compressed:
                if not self._snapshot_zstd:
                    self._snapshot_zstd = compress_frame(self._snapshot)
                subscriber.queue.put_nowait(self._snapshot_zstd)
            else:
                subscriber.queue.put_nowait(self._snapshot)

        try:
            while True:
                data = await subscriber.queue.get()
                if data is None:
                    return
                yield data
        finally:
            self._subscribers.discard(subscriber)

    def _serialize_snapshot(self, writer: MultipartWriter) -> bytes:
        assert self._templates is not None
        snapshot = bytearray()
        for template_name, headers in self._templates.items():
            html = self._latest.get(template_name)
            if html is not None:
                snapshot.extend(
                    b"".join(
                        writer.iterate_part(
                            Part(html, headers=headers, media_type="text/html")
                        )
                    )
                )
        return bytes(snapshot)

    def _start_epoch(self) -> None:
        if self._compressor.has_open_frame:
            frame_end = self._compressor.finish_frame()
            self._fan_out(b"", frame_end, compressed_only=True)

    def _send(self, identity: bytes) -> None:
        zstd = (
            self._compressor.compress(identity)
            if any(subscriber.compressed for subscriber in self._subscribers)
            else b""
        )
        self._fan_out(identity, zstd)

    def _fan_out(
        self,
        identity: bytes,
        zstd: bytes,
        compressed_only: bool = False,
    ) -> None:
        for subscriber in tuple(self._subscribers):
            if compressed_only and not subscriber.compressed:
                continue
            if subscriber.queue.full():
                self._subscribers.discard(subscriber)
                while not subscriber.queue.empty():
                    subscriber.queue.get_nowait()
                subscriber.queue.put_nowait(None)
            else:
                subscriber.queue.put_nowait(zstd if subscriber.compressed else identity)


broadcast = Broadcast()
