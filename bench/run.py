"""Measure the cost of broadcasting one shared cursor update."""

import asyncio
import json
import math
import random
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx

from app.config import settings

BASE_URL = "http://127.0.0.1:8001"
BENCHMARK_DB = "hyperspace_bench"
CLIENT_COUNTS = (1, 10, 50, 100)
MOVES = 15
MOVE_INTERVAL = 0.2
RESULTS_DIR = Path(__file__).parent / "results"
PROFILE_PATH = RESULTS_DIR / "cpu.speedscope.json"
REPORT_PATH = RESULTS_DIR / "latest.md"
SERVER_LOG = RESULTS_DIR / "server.log"


@dataclass
class Result:
    clients: int
    patch_ms: list[float] = field(default_factory=list)
    fanout_ms: list[float] = field(default_factory=list)
    bytes_per_move: float = 0
    sql_calls_per_move: float = 0
    sql_ms_per_move: float = 0
    error: str = ""


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1]


def format_bytes(value: float) -> str:
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MiB"
    return f"{value / 1024:.1f} KiB"


def postgres_kwargs(database: str) -> dict:
    return {
        "host": "127.0.0.1",
        "port": settings.POSTGRES_PORT,
        "user": settings.POSTGRES_USER,
        "password": settings.POSTGRES_PASSWORD,
        "database": database,
    }


async def recreate_database() -> None:
    connection = await asyncpg.connect(**postgres_kwargs("postgres"))
    try:
        libraries = await connection.fetchval("SHOW shared_preload_libraries")
        if "pg_stat_statements" not in libraries:
            raise RuntimeError("PostgreSQL did not preload pg_stat_statements")
        await connection.execute(
            f'DROP DATABASE IF EXISTS "{BENCHMARK_DB}" WITH (FORCE)'
        )
        await connection.execute(f'CREATE DATABASE "{BENCHMARK_DB}"')
    finally:
        await connection.close()


async def drop_database() -> None:
    connection = await asyncpg.connect(**postgres_kwargs("postgres"))
    try:
        await connection.execute(
            f'DROP DATABASE IF EXISTS "{BENCHMARK_DB}" WITH (FORCE)'
        )
    finally:
        await connection.close()


def start_server() -> tuple[subprocess.Popen, object]:
    RESULTS_DIR.mkdir(exist_ok=True)
    PROFILE_PATH.unlink(missing_ok=True)
    SERVER_LOG.unlink(missing_ok=True)
    log = SERVER_LOG.open("w")
    process = subprocess.Popen(
        [
            "docker",
            "compose",
            "--profile",
            "benchmark",
            "up",
            "--build",
            "--force-recreate",
            "--no-deps",
            "benchmark",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return process, log


async def wait_for_server(process: subprocess.Popen) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(240):
            if process.poll() is not None:
                raise RuntimeError(SERVER_LOG.read_text())
            try:
                response = await client.get(f"{BASE_URL}/health", timeout=1)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("Benchmark server did not start within two minutes")


def stop_server(process: subprocess.Popen, log: object) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "benchmark",
            "kill",
            "--signal",
            "SIGINT",
            "benchmark",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    subprocess.run(
        ["docker", "compose", "--profile", "benchmark", "rm", "-f", "benchmark"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.close()


async def stream_reader(
    client: httpx.AsyncClient,
    ready: asyncio.Event,
    cursor_parts: asyncio.Queue[tuple[float, int]],
) -> None:
    buffer = b""
    content_length: int | None = None
    target = ""
    try:
        async with client.stream("GET", "/stream") as response:
            response.raise_for_status()
            ready.set()
            async for chunk in response.aiter_bytes():
                buffer += chunk
                while True:
                    if content_length is None:
                        header_end = buffer.find(b"\r\n\r\n")
                        if header_end < 0:
                            break
                        headers = buffer[:header_end].decode(errors="replace")
                        buffer = buffer[header_end + 4 :]
                        parsed = {}
                        for line in headers.split("\r\n"):
                            if ":" in line:
                                name, value = line.split(":", 1)
                                parsed[name.lower()] = value.strip()
                        content_length = int(parsed["content-length"])
                        target = parsed.get("hx-target", "")
                    if len(buffer) < content_length:
                        break
                    buffer = buffer[content_length:]
                    if target == "#cursors":
                        cursor_parts.put_nowait((time.perf_counter(), content_length))
                    content_length = None
    except asyncio.CancelledError:
        raise
    finally:
        ready.set()


async def open_players(
    count: int,
) -> tuple[list[httpx.AsyncClient], list[asyncio.Queue], list[asyncio.Task]]:
    clients = [
        httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"HX-Request": "true"},
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            timeout=httpx.Timeout(10, read=None),
        )
        for _ in range(count)
    ]

    async def join(index: int, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/join",
            data={
                "name": f"Bench {count} {index} {uuid.uuid4().hex[:6]}",
                "color_seed": index % 100 + 1,
            },
        )
        response.raise_for_status()

    await asyncio.gather(*(join(index, client) for index, client in enumerate(clients)))

    # Build a real N-player world before opening streams. Setup traffic is not measured.
    await asyncio.gather(
        *(
            client.patch(
                "/cursor",
                data={
                    "x": index % settings.GRID_SIZE,
                    "y": index // settings.GRID_SIZE % settings.GRID_SIZE,
                    "z": -1,
                },
            )
            for index, client in enumerate(clients)
        )
    )

    queues = [asyncio.Queue() for _ in clients]
    ready = [asyncio.Event() for _ in clients]
    tasks = [
        asyncio.create_task(stream_reader(client, ready[index], queues[index]))
        for index, client in enumerate(clients)
    ]
    await asyncio.wait_for(
        asyncio.gather(*(event.wait() for event in ready)),
        timeout=10,
    )
    return clients, queues, tasks


async def close_players(
    clients: list[httpx.AsyncClient],
    tasks: list[asyncio.Task],
) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.gather(*(client.aclose() for client in clients))
    await asyncio.sleep(0.5)


def clear(queues: list[asyncio.Queue]) -> None:
    for queue in queues:
        while not queue.empty():
            queue.get_nowait()


async def move_and_wait(
    client: httpx.AsyncClient,
    queues: list[asyncio.Queue],
    x: int,
) -> tuple[float, float, int]:
    clear(queues)
    sent_at = time.perf_counter()
    response = await client.patch("/cursor", data={"x": x, "y": 0, "z": -1})
    patch_ms = (time.perf_counter() - sent_at) * 1000
    response.raise_for_status()
    arrivals = await asyncio.gather(
        *(asyncio.wait_for(queue.get(), timeout=10) for queue in queues)
    )
    return (
        patch_ms,
        (max(arrival for arrival, _ in arrivals) - sent_at) * 1000,
        sum(length for _, length in arrivals),
    )


async def sql_cost(connection: asyncpg.Connection) -> tuple[float, float]:
    row = await connection.fetchrow(
        """
        SELECT coalesce(sum(calls), 0) AS calls,
               coalesce(sum(total_exec_time), 0) AS total_exec_time
          FROM pg_stat_statements
         WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
           AND query NOT ILIKE '%pg_stat_statements%'
        """
    )
    return float(row["calls"]), float(row["total_exec_time"])


async def run_scenario(connection: asyncpg.Connection, count: int) -> Result:
    result = Result(clients=count)
    await connection.execute(
        "TRUNCATE events, cursors, bricks, players RESTART IDENTITY CASCADE"
    )
    clients, queues, tasks = await open_players(count)
    try:
        await asyncio.sleep(1)
        await move_and_wait(clients[0], queues, 1)
        await connection.execute("SELECT pg_stat_statements_reset()")

        total_bytes = 0
        for step in range(MOVES):
            started = time.perf_counter()
            patch_ms, fanout_ms, body_bytes = await move_and_wait(
                clients[0], queues, step % settings.GRID_SIZE
            )
            result.patch_ms.append(patch_ms)
            result.fanout_ms.append(fanout_ms)
            total_bytes += body_bytes
            remaining = MOVE_INTERVAL - (time.perf_counter() - started)
            if remaining > 0:
                await asyncio.sleep(remaining)

        calls, sql_ms = await sql_cost(connection)
        result.bytes_per_move = total_bytes / MOVES
        result.sql_calls_per_move = calls / MOVES
        result.sql_ms_per_move = sql_ms / MOVES
        return result
    finally:
        await close_players(clients, tasks)


def cpu_summary() -> list[tuple[str, float]]:
    if not PROFILE_PATH.exists():
        return []
    profile = json.loads(PROFILE_PATH.read_text())
    frames = profile["shared"]["frames"]
    weights: dict[str, float] = {}
    total = 0.0
    for item in profile["profiles"]:
        if item.get("type") != "sampled":
            continue
        item_weights = item.get("weights") or [1] * len(item["samples"])
        for sample, weight in zip(item["samples"], item_weights, strict=True):
            for frame_index in reversed(sample):
                frame = frames[frame_index]
                filename = frame.get("file", "")
                if "/app/" not in filename or frame["name"] == "<module>":
                    continue
                name = f"{frame['name']} ({Path(filename).name})"
                weights[name] = weights.get(name, 0) + weight
                total += weight
                break
    if not total:
        return []
    return sorted(
        ((name, weight / total * 100) for name, weight in weights.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:5]


def write_report(results: list[Result], cpu: list[tuple[str, float]]) -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    lines = [
        "# Cursor fanout benchmark",
        "",
        f"Commit: `{commit}`",
        "",
        "One player moves at 5 Hz in an N-player world. Each move completes when every stream receives the cursor part.",
        "",
        "| Players | PATCH p95 | Fanout p50 | Fanout p95 | SQL calls/move | SQL ms/move | HTML/move |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        if result.error:
            lines.append(
                f"| {result.clients} | timeout | timeout | timeout | n/a | n/a | n/a |"
            )
            continue
        lines.append(
            f"| {result.clients} | {percentile(result.patch_ms, 0.95):.1f} ms | "
            f"{percentile(result.fanout_ms, 0.50):.1f} ms | "
            f"{percentile(result.fanout_ms, 0.95):.1f} ms | "
            f"{result.sql_calls_per_move:.1f} | {result.sql_ms_per_move:.2f} | "
            f"{format_bytes(result.bytes_per_move)} |"
        )

    lines.extend(["", "Hot application CPU:", ""])
    for name, percentage in cpu:
        lines.append(f"- {percentage:.0f}% `{name}`")
    REPORT_PATH.write_text("\n".join(lines) + "\n")


async def run() -> None:
    random.seed(1)
    await recreate_database()
    process, log = start_server()
    results: list[Result] = []
    try:
        await wait_for_server(process)
        connection = await asyncpg.connect(**postgres_kwargs(BENCHMARK_DB))
        try:
            for count in CLIENT_COUNTS:
                try:
                    result = await asyncio.wait_for(
                        run_scenario(connection, count), timeout=45
                    )
                except TimeoutError:
                    result = Result(clients=count, error="timeout")
                results.append(result)
                if result.error:
                    print(f"{count:3} players: timed out", flush=True)
                else:
                    print(
                        f"{count:3} players: fanout p95 "
                        f"{percentile(result.fanout_ms, 0.95):.1f}ms, "
                        f"SQL {result.sql_calls_per_move:.1f}/move, "
                        f"HTML {format_bytes(result.bytes_per_move)}/move",
                        flush=True,
                    )
        finally:
            await connection.close()
    finally:
        stop_server(process, log)
        await drop_database()

    write_report(results, cpu_summary())
    print(f"\n{REPORT_PATH.read_text()}")


if __name__ == "__main__":
    asyncio.run(run())
