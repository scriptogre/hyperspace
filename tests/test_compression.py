from compression.zstd import ZstdDecompressor, decompress

from app.compression import ZstdStreamCompressor, compress_frame


def test_stream_compressor_emits_a_readable_frame() -> None:
    compressor = ZstdStreamCompressor()
    first = compressor.compress(b"first")
    second = compressor.compress(b"second")
    final = compressor.finish_frame()

    assert ZstdDecompressor().decompress(first + second + final) == b"firstsecond"
    assert not compressor.has_open_frame
    assert compressor.finish_frame() == b""


def test_stream_compressor_starts_a_new_frame_after_finishing() -> None:
    compressor = ZstdStreamCompressor()
    first = compressor.compress(b"first") + compressor.finish_frame()
    second = compressor.compress(b"second") + compressor.finish_frame()

    assert decompress(first + second) == b"firstsecond"


def test_compress_frame_returns_a_standalone_frame() -> None:
    assert decompress(compress_frame(b"ready")) == b"ready"
