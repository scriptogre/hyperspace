from bench.compression import measure, render_updates
from bench.compression_card import render_card
from tests import run_async


def test_compression_benchmark_uses_history_and_verifies_round_trip() -> None:
    frames = render_updates(size=2, players=2, moves=3)
    measurements = run_async(measure(frames))

    assert len(measurements.decoded) == 4
    assert measurements.compressed[2] < measurements.standalone[2]

    card = render_card(measurements, size=2, players=2, moves=3)
    assert card.startswith("<svg")
    assert "bytes" in card
    assert ":1 compression" in card
