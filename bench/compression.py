"""Measure cold and long-lived stream compression with a cursor workload."""

import argparse
import asyncio
import platform
import re
import statistics
import subprocess
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from compression.zstd import ZstdDecompressor, decompress, zstd_version

from app.broadcast import SharedStream
from app.colors import calculate_player_color
from app.compression import compress_frame
from app.dependencies import player_initials
from app.jinja import render

DEFAULT_CHECKPOINTS = (0, 1, 5, 10, 25, 100)


@dataclass
class Measurements:
    decoded: list[int]
    compressed: list[int]
    standalone: list[int]
    frame_end: int


def make_context(size: int, player_count: int) -> dict:
    player_rows = []
    for index in range(1, player_count + 1):
        name = f"Player {index}"
        player_rows.append(
            {
                "id": index,
                "name": name,
                "initials": player_initials(name),
                "color": calculate_player_color(index % 100 + 1),
                "is_online": True,
            }
        )

    cursors = [
        {
            "player_id": player["id"],
            "grid_x": (player["id"] - 1) % size,
            "grid_y": ((player["id"] - 1) // size) % size,
            "grid_z": -1,
            "offset": 0.0,
            "name": player["name"],
            "initials": player["initials"],
            "color": player["color"],
        }
        for player in player_rows
    ]
    return {
        "world": SimpleNamespace(
            size=size,
            theme=None,
            announcement=None,
        ),
        "brick_stacks": {x: {y: [] for y in range(size)} for x in range(size)},
        "players": sorted(player_rows, key=lambda player: player["name"]),
        "cursors": cursors,
    }


def render_updates(size: int, players: int, moves: int) -> Iterator[bytes]:
    context = make_context(size, players)
    for move in range(moves + 1):
        cursor = context["cursors"][0]
        cursor["grid_x"] = move % size
        cursor["grid_y"] = (move // size) % size

        counts = Counter(
            (item["grid_x"], item["grid_y"], item["grid_z"])
            for item in context["cursors"]
        )
        indexes = Counter()
        for item in context["cursors"]:
            position = (item["grid_x"], item["grid_y"], item["grid_z"])
            item["offset"] = indexes[position] - (counts[position] - 1) / 2
            indexes[position] += 1

        html = render("_world.html", context).encode()
        yield re.sub(rb">\s+<", b"><", html)


async def measure(frames: Iterable[bytes]) -> Measurements:
    frames = iter(frames)
    stream = SharedStream()
    stream.publish(next(frames))

    identity_subscription = stream.subscribe(compressed=False)
    compressed_subscription = stream.subscribe(compressed=True)
    identity = await anext(identity_subscription)
    compressed = await anext(compressed_subscription)

    assert decompress(compressed) == identity
    decoded_sizes = [len(identity)]
    compressed_sizes = [len(compressed)]
    standalone_sizes = [len(compress_frame(identity))]
    decompressor = ZstdDecompressor()

    for frame in frames:
        stream.publish(frame)
        identity = await anext(identity_subscription)
        compressed = await anext(compressed_subscription)
        assert decompressor.decompress(compressed) == identity
        decoded_sizes.append(len(identity))
        compressed_sizes.append(len(compressed))
        standalone_sizes.append(len(compress_frame(identity)))

    # Starting another epoch closes the measured update frame. Use its terminator
    # only to prove that the compressed stream decodes byte-for-byte.
    next_subscription = stream.subscribe(compressed=True)
    next_snapshot_pending = asyncio.create_task(anext(next_subscription))
    frame_end = await anext(compressed_subscription)
    await next_snapshot_pending

    assert decompressor.decompress(frame_end) == b""
    assert decompressor.eof

    await identity_subscription.aclose()
    await compressed_subscription.aclose()
    await next_subscription.aclose()

    return Measurements(
        decoded=decoded_sizes,
        compressed=compressed_sizes,
        standalone=standalone_sizes,
        frame_end=len(frame_end),
    )


def print_report(
    measurements: Measurements,
    size: int,
    players: int,
    moves: int,
) -> None:
    checkpoints = [value for value in DEFAULT_CHECKPOINTS if value <= moves]
    if moves not in checkpoints:
        checkpoints.append(moves)

    revision = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    )

    print("Hyperspace stream compression benchmark")
    print(f"Revision: {revision}{' (dirty)' if dirty else ''}")
    print(f"Runtime: Python {platform.python_version()}, Zstd {zstd_version}")
    print(
        f"Packages: minijinja {version('minijinja')}, "
        f"multipart-response {version('multipart-response')}"
    )
    print(
        f"Workload: {size}x{size} world, {players} players, 0 bricks, one cursor moving"
    )
    print("History: no new subscribers during measured updates")
    print("Bytes: application body only; HTTP headers and framing excluded")
    print(f"Open epoch terminator: {measurements.frame_end} B, verification only")
    print("Verification: decoded output matches the multipart input byte-for-byte")
    print()
    print("updates    decoded B  standalone B     ratio  long-lived B     ratio")
    for checkpoint in checkpoints:
        decoded = sum(measurements.decoded[: checkpoint + 1])
        standalone = sum(measurements.standalone[: checkpoint + 1])
        compressed = sum(measurements.compressed[: checkpoint + 1])
        print(
            f"{checkpoint:>7}  {decoded:>11,}  {standalone:>12,}  "
            f"{decoded / standalone:>7.1f}:1  {compressed:>12,}  "
            f"{decoded / compressed:>7.1f}:1"
        )

    if moves >= 2:
        warm_sizes = measurements.compressed[2:]
        warm_ratios = [
            decoded / compressed
            for decoded, compressed in zip(
                measurements.decoded[2:], warm_sizes, strict=True
            )
        ]
        print()
        print(
            f"Cold snapshot: {measurements.decoded[0]:,} / {measurements.compressed[0]:,} = "
            f"{measurements.decoded[0] / measurements.compressed[0]:.1f}:1"
        )
        print(
            f"Warm update median: {statistics.median(warm_sizes):.0f} B, "
            f"{statistics.median(warm_ratios):.1f}:1"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure Zstd history reuse across full-world cursor updates."
    )
    parser.add_argument("--size", type=int, default=16)
    parser.add_argument("--players", type=int, default=100)
    parser.add_argument("--moves", type=int, default=100)
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--png", type=Path)
    args = parser.parse_args()

    if args.size < 1 or args.players < 1 or args.moves < 1:
        parser.error("size, players, and moves must be positive")

    frames = render_updates(args.size, args.players, args.moves)
    measurements = asyncio.run(measure(frames))
    print_report(measurements, args.size, args.players, args.moves)

    if args.svg or args.png:
        from bench.compression_card import write_card

        write_card(
            measurements,
            args.size,
            args.players,
            args.moves,
            args.svg,
            args.png,
        )


if __name__ == "__main__":
    main()
