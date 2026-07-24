"""Shared Zstandard compression helpers."""

from compression.zstd import CompressionParameter, ZstdCompressor, compress

_OPTIONS = {
    CompressionParameter.compression_level: 6,
    CompressionParameter.window_log: 23,
}


class ZstdStreamCompressor:
    """Compress one shared stream in immediately readable blocks."""

    def __init__(self) -> None:
        self._compressor = ZstdCompressor(options=_OPTIONS)

    @property
    def has_open_frame(self) -> bool:
        return self._compressor.last_mode != ZstdCompressor.FLUSH_FRAME

    def compress(self, data: bytes) -> bytes:
        """Compress data into a block that can be read immediately."""
        return self._compressor.compress(data, mode=ZstdCompressor.FLUSH_BLOCK)

    def finish_frame(self) -> bytes:
        """Finish the current frame and return its remaining compressed data."""
        if not self.has_open_frame:
            return b""
        return self._compressor.flush(ZstdCompressor.FLUSH_FRAME)


def compress_frame(data: bytes) -> bytes:
    """Compress data as one complete, standalone frame."""
    return compress(data, options=_OPTIONS)
