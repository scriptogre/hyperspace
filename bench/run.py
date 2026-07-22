"""Benchmark the current HTTP and multipart application from outside FastAPI."""

import asyncio
import json
import random
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx
from playwright.async_api import async_playwright

from app.config import settings

BASE_URL = "http://127.0.0.1:8001"
BENCHMARK_DB = "hyperspace_bench"
RESULTS_DIR = Path(__file__).parent / "results"
PROFILE_PATH = RESULTS_DIR / "cpu.speedscope.json"
SERVER_LOG = RESULTS_DIR / "server.log"
REPORT_PATH = RESULTS_DIR / "latest.md"
MOVE_INTERVAL = 0.15


@dataclass
class Scenario:
    name: str
    clients: int
    movers: int
    seconds: float
    patch_ms: list[float] = field(default_factory=list)
    stream_ms: list[float] = field(default_factory=list)
    parts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    sql: list[dict] = field(default_factory=list)
    browser: dict[str, list[float] | list[str]] = field(default_factory=dict)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


def latency(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (
        f"p50={percentile(values, 0.50):.1f}ms "
        f"p95={percentile(values, 0.95):.1f}ms "
        f"p99={percentile(values, 0.99):.1f}ms"
    )


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
    raise RuntimeError("Benchmark server did not start")


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


async def reset_database(connection: asyncpg.Connection) -> None:
    await connection.execute(
        "TRUNCATE events, cursors, bricks, players RESTART IDENTITY CASCADE"
    )


async def reset_query_stats(connection: asyncpg.Connection) -> None:
    await connection.execute("SELECT pg_stat_statements_reset()")


async def query_stats(connection: asyncpg.Connection) -> list[dict]:
    rows = await connection.fetch(
        """
        SELECT calls,
               total_exec_time,
               mean_exec_time,
               rows,
               shared_blks_hit,
               shared_blks_read,
               wal_bytes,
               regexp_replace(query, '\\s+', ' ', 'g') AS query
          FROM pg_stat_statements
         WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
           AND query NOT ILIKE '%pg_stat_statements%'
         ORDER BY total_exec_time DESC
         LIMIT 12
        """
    )
    return [dict(row) for row in rows]


async def stream_reader(
    client: httpx.AsyncClient,
    ready: asyncio.Event,
    cursor_parts: asyncio.Queue,
    parts: dict[str, int],
    errors: list[str],
) -> None:
    buffer = b""
    content_length: int | None = None
    target = "unknown"
    try:
        async with client.stream("GET", "/stream") as response:
            if response.status_code != 200:
                errors.append(f"stream status {response.status_code}")
                ready.set()
                return
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
                        if "content-length" not in parsed:
                            errors.append("stream part missing Content-Length")
                            return
                        content_length = int(parsed["content-length"])
                        target = parsed.get("hx-target", "unknown")
                    if len(buffer) < content_length:
                        break
                    buffer = buffer[content_length:]
                    parts[target] = parts.get(target, 0) + 1
                    if target == "#cursors":
                        cursor_parts.put_nowait(time.perf_counter())
                    content_length = None
    except asyncio.CancelledError:
        raise
    except Exception as error:
        errors.append(f"stream: {type(error).__name__}: {error}")
        ready.set()


async def open_players(
    count: int,
    scenario: Scenario,
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
                "name": f"Bench {scenario.name} {index} {uuid.uuid4().hex[:6]}",
                "color_seed": index % 100 + 1,
            },
        )
        if response.status_code != 204:
            raise RuntimeError(f"join returned {response.status_code}: {response.text}")

    await asyncio.gather(*(join(index, client) for index, client in enumerate(clients)))

    queues = [asyncio.Queue() for _ in clients]
    ready = [asyncio.Event() for _ in clients]
    tasks = [
        asyncio.create_task(
            stream_reader(
                client, ready[index], queues[index], scenario.parts, scenario.errors
            )
        )
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
    await asyncio.sleep(0.2)


async def run_fanout(
    connection: asyncpg.Connection,
    count: int,
) -> Scenario:
    scenario = Scenario(f"fanout-{count}", count, 1, 1.5)
    await reset_database(connection)
    clients, queues, tasks = await open_players(count, scenario)
    try:
        await asyncio.sleep(0.2)
        await reset_query_stats(connection)
        mover = clients[0]
        x = y = 0
        started = time.perf_counter()
        for step in range(10):
            for queue in queues:
                while not queue.empty():
                    queue.get_nowait()
            x = (x + 1) % settings.GRID_SIZE
            if x == 0:
                y = (y + 1) % settings.GRID_SIZE
            sent_at = time.perf_counter()
            response = await mover.patch("/cursor", data={"x": x, "y": y, "z": -1})
            scenario.patch_ms.append((time.perf_counter() - sent_at) * 1000)
            if response.status_code != 204:
                scenario.errors.append(f"cursor status {response.status_code}")
            arrivals = await asyncio.gather(
                *(asyncio.wait_for(queue.get(), timeout=5) for queue in queues),
                return_exceptions=True,
            )
            for arrival in arrivals:
                if isinstance(arrival, float):
                    scenario.stream_ms.append((arrival - sent_at) * 1000)
                else:
                    scenario.errors.append("cursor part timeout")
            remaining = MOVE_INTERVAL - (time.perf_counter() - sent_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        scenario.seconds = time.perf_counter() - started
        scenario.sql = await query_stats(connection)
        return scenario
    finally:
        await close_players(clients, tasks)


async def browser_probe() -> dict[str, list[float] | list[str]]:
    result: dict[str, list[float] | list[str]] = {
        "create": [],
        "drag": [],
        "delete": [],
        "errors": [],
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        page.on(
            "console",
            lambda message: (
                result["errors"].append(message.text)
                if message.type in {"error", "warning"}
                else None
            ),
        )
        await page.goto(BASE_URL)
        form = page.locator("#player-form")
        await form.locator("input[name=name]").fill("Benchmark Browser")
        await form.locator("button[type=submit]").click()
        await form.wait_for(state="detached")

        created: list[str] = []
        for _ in range(5):
            cell = page.locator(".grid-cell:not(:has(.brick))").first
            cell_id = await cell.get_attribute("id")
            started = time.perf_counter()
            await cell.locator(":scope > button[aria-label='Add brick']").click()
            await page.wait_for_function(
                "id => document.querySelector(`#${id} > .brick`)",
                arg=cell_id,
            )
            result["create"].append((time.perf_counter() - started) * 1000)
            brick_id = await page.locator(f"#{cell_id} > .brick").get_attribute("id")
            created.append(brick_id)

        brick_id = created[0]
        for _ in range(5):
            source = page.locator(f"#{brick_id}")
            target = page.locator(".grid-cell:not(:has(.brick))").first
            target_id = await target.get_attribute("id")
            source_button = source.locator(
                ":scope > button:not([hx-delete]):not([hidden])"
            )
            source_box = await source_button.bounding_box()
            target_box = await target.locator(":scope > button").bounding_box()
            await page.mouse.move(
                source_box["x"] + source_box["width"] / 2,
                source_box["y"] + source_box["height"] / 2,
            )
            started = time.perf_counter()
            await page.mouse.down()
            await page.mouse.move(
                target_box["x"] + target_box["width"] / 2,
                target_box["y"] + target_box["height"] / 2,
                steps=8,
            )
            await page.mouse.up()
            await page.wait_for_function(
                "([cell, brick]) => document.querySelector(`#${cell} > #${brick}`)",
                arg=[target_id, brick_id],
            )
            result["drag"].append((time.perf_counter() - started) * 1000)

        for brick_id in created[1:]:
            brick = page.locator(f"#{brick_id}")
            delete_button = brick.locator(":scope > button[hx-delete]")
            await page.keyboard.down("Shift")
            box = await delete_button.bounding_box()
            await page.mouse.move(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            )
            started = time.perf_counter()
            await page.mouse.down()
            await asyncio.sleep(0.12)
            await page.mouse.up()
            await page.keyboard.up("Shift")
            await page.wait_for_function(
                "id => !document.getElementById(id)",
                arg=brick_id,
            )
            result["delete"].append((time.perf_counter() - started) * 1000)

        await browser.close()
    return result


async def run_mixed(connection: asyncpg.Connection) -> Scenario:
    scenario = Scenario("mixed", 100, 20, 10)
    await reset_database(connection)
    clients, _, tasks = await open_players(scenario.clients, scenario)
    stop = asyncio.Event()

    async def move(index: int) -> None:
        client = clients[index]
        x = index % settings.GRID_SIZE
        y = index // settings.GRID_SIZE % settings.GRID_SIZE
        while not stop.is_set():
            x = max(0, min(settings.GRID_SIZE - 1, x + random.choice((-1, 0, 1))))
            y = max(0, min(settings.GRID_SIZE - 1, y + random.choice((-1, 0, 1))))
            started = time.perf_counter()
            try:
                response = await client.patch(
                    "/cursor",
                    data={"x": x, "y": y, "z": -1},
                )
                scenario.patch_ms.append((time.perf_counter() - started) * 1000)
                if response.status_code != 204:
                    scenario.errors.append(f"cursor status {response.status_code}")
            except Exception as error:
                scenario.errors.append(f"cursor: {type(error).__name__}")
            await asyncio.sleep(random.uniform(0.10, 0.25))

    async def build(index: int) -> None:
        client = clients[index]
        while not stop.is_set():
            try:
                response = await client.post(
                    "/bricks",
                    data={
                        "x": random.randrange(settings.GRID_SIZE),
                        "y": random.randrange(settings.GRID_SIZE),
                    },
                )
                if response.status_code != 204:
                    scenario.errors.append(f"brick status {response.status_code}")
            except Exception as error:
                scenario.errors.append(f"brick: {type(error).__name__}")
            await asyncio.sleep(random.uniform(1.5, 3.0))

    workers = [asyncio.create_task(move(index)) for index in range(scenario.movers)]
    workers.extend(asyncio.create_task(build(index)) for index in range(2))
    try:
        await asyncio.sleep(0.2)
        await reset_query_stats(connection)
        started = time.perf_counter()
        browser_task = asyncio.create_task(browser_probe())
        await asyncio.sleep(scenario.seconds)
        stop.set()
        await asyncio.gather(*workers, return_exceptions=True)
        scenario.browser = await asyncio.wait_for(browser_task, timeout=30)
        scenario.seconds = time.perf_counter() - started
        scenario.sql = await query_stats(connection)
        return scenario
    finally:
        stop.set()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
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
            app_frame = None
            for frame_index in reversed(sample):
                frame = frames[frame_index]
                filename = frame.get("file", "")
                if "/app/" in filename or "/bench/" in filename:
                    app_frame = frame
                    break
            if app_frame is None:
                continue
            name = f"{app_frame['name']} ({Path(app_frame.get('file', '')).name})"
            weights[name] = weights.get(name, 0) + weight
            total += weight
    return sorted(
        ((name, weight / total * 100) for name, weight in weights.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:12]


def write_report(scenarios: list[Scenario], cpu: list[tuple[str, float]]) -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        text=True,
    ).strip()
    lines = [
        "# Hyperspace benchmark",
        "",
        f"Commit: `{commit}`  ",
        f"Generated: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
        "## End-to-end results",
        "",
        "| Scenario | Clients | Movers | Duration | PATCH latency | Stream latency | Parts/s | Errors |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for scenario in scenarios:
        part_count = sum(scenario.parts.values())
        lines.append(
            f"| {scenario.name} | {scenario.clients} | {scenario.movers} | "
            f"{scenario.seconds:.1f}s | {latency(scenario.patch_ms)} | "
            f"{latency(scenario.stream_ms)} | {part_count / scenario.seconds:.1f} | "
            f"{len(scenario.errors)} |"
        )

    mixed = scenarios[-1]
    lines.extend(["", "## Browser under mixed load", ""])
    for action in ("create", "drag", "delete"):
        values = mixed.browser.get(action, [])
        lines.append(f"- **{action}:** {latency(values)}")
    browser_errors = mixed.browser.get("errors", [])
    lines.append(f"- **console errors:** {len(browser_errors)}")

    for scenario in scenarios:
        lines.extend(
            [
                "",
                f"## SQL: {scenario.name}",
                "",
                "| Calls | Total ms | Mean ms | Rows | Hits | Reads | WAL bytes | Query |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for query in scenario.sql:
            sql = query["query"].replace("|", "\\|")[:180]
            lines.append(
                f"| {query['calls']} | {query['total_exec_time']:.1f} | "
                f"{query['mean_exec_time']:.3f} | {query['rows']} | "
                f"{query['shared_blks_hit']} | {query['shared_blks_read']} | "
                f"{query['wal_bytes']} | `{sql}` |"
            )

    lines.extend(["", "## Python CPU", ""])
    if cpu:
        for name, percentage in cpu:
            lines.append(f"- **{percentage:.1f}%** {name}")
    else:
        lines.append("No application samples were recorded.")
    lines.extend(
        [
            "",
            f"Open `{PROFILE_PATH}` in https://www.speedscope.app for the full profile.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines))


async def run() -> None:
    random.seed(1)
    RESULTS_DIR.mkdir(exist_ok=True)
    await recreate_database()
    process, log = start_server()
    scenarios: list[Scenario] = []
    try:
        await wait_for_server(process)
        connection = await asyncpg.connect(**postgres_kwargs(BENCHMARK_DB))
        try:
            for count in (1, 10, 50, 100):
                scenario = await asyncio.wait_for(
                    run_fanout(connection, count),
                    timeout=30,
                )
                scenarios.append(scenario)
                print(
                    f"{scenario.name:>12}: PATCH {latency(scenario.patch_ms)}; "
                    f"stream {latency(scenario.stream_ms)}; errors={len(scenario.errors)}",
                    flush=True,
                )
            mixed = await asyncio.wait_for(run_mixed(connection), timeout=60)
            scenarios.append(mixed)
            print(
                f"{mixed.name:>12}: PATCH {latency(mixed.patch_ms)}; "
                f"parts/s={sum(mixed.parts.values()) / mixed.seconds:.1f}; "
                f"errors={len(mixed.errors)}",
                flush=True,
            )
        finally:
            await connection.close()
    finally:
        stop_server(process, log)
        await drop_database()

    cpu = cpu_summary()
    write_report(scenarios, cpu)
    print(f"\nReport: {REPORT_PATH}")
    print(f"CPU profile: {PROFILE_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
