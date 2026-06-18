"""
Live end-to-end echo latency against the running server.

Measures user-felt round-trip: time from sending a cursor move to receiving
the broadcast that reflects it, while N-1 other connections generate
background cursor load.

Both transports use identical workload: ~50Hz cursor updates, same warmup,
same sample count, same inter-sample sleep. GC is disabled during measurement.

    uv run --with httpx python -m bench.echo_latency                         # WS (default)
    HS_TRANSPORT=sse uv run --with httpx python -m bench.echo_latency        # SSE+POST
    HS_TRANSPORT=both uv run --with httpx python -m bench.echo_latency       # side-by-side
    HS_HTTP2=1 HS_TRANSPORT=sse uv run --with 'httpx[http2]' python -m ...   # SSE+POST H2
"""

import asyncio
import gc
import json
import os
import ssl
import statistics
import sys
import time
import urllib.parse
import urllib.request
import uuid

import websockets

WS_URL = os.environ.get("HS_WS_URL", "ws://127.0.0.1:8001/ws")
_default_base = (
    WS_URL.replace("wss://", "https://").replace("ws://", "http://").rsplit("/", 1)[0]
)
BASE_URL = os.environ.get("HS_BASE_URL", _default_base)
TRANSPORT = os.environ.get("HS_TRANSPORT", "ws").lower()
HTTP2 = os.environ.get("HS_HTTP2", "") == "1"
INSECURE = os.environ.get("HS_INSECURE", "") == "1"
N_SAMPLES = int(os.environ.get("HS_SAMPLES", "200"))
N_WARMUP = 50
TICK = 0.02  # 50 Hz, same for both transports

_TLS_CTX = None
if INSECURE:
    _TLS_CTX = ssl.create_default_context()
    _TLS_CTX.check_hostname = False
    _TLS_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Setup helpers (sync HTTP, no external deps)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_handlers = [_NoRedirect]
if INSECURE:
    _handlers.append(urllib.request.HTTPSHandler(context=_TLS_CTX))
_opener = urllib.request.build_opener(*_handlers)


def _create_player(session_id, name=None):
    """Register a player via POST /join."""
    if name is None:
        name = f"B-{session_id[:6]}"
    data = urllib.parse.urlencode({"name": name, "color": "cyan"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/join",
        data=data,
        headers={
            "Cookie": f"hyperspace_id={session_id}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        _opener.open(req, timeout=10)
    except Exception:
        pass


def _post_action_sync(session_id, fn, args):
    """Send one action via POST /action. For setup only."""
    data = json.dumps({"fn": fn, "args": args}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/action",
        data=data,
        headers={
            "Cookie": f"hyperspace_id={session_id}",
            "Content-Type": "application/json",
        },
    )
    try:
        _opener.open(req, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# WS transport
# ---------------------------------------------------------------------------


def _ws_conn(session_id):
    kw = {}
    if WS_URL.startswith("wss://") and _TLS_CTX:
        kw["ssl"] = _TLS_CTX
    return websockets.connect(
        WS_URL,
        additional_headers={"Cookie": f"hyperspace_id={session_id}"},
        open_timeout=10,
        max_size=None,
        compression=None,
        **kw,
    )


async def _ws_drain(ws):
    """Discard buffered broadcasts so the next recv is fresh."""
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.005)
        except (asyncio.TimeoutError, Exception):
            return


async def _ws_load(session_id, stop, connected):
    """Background WS client: spam cursor moves until stopped."""
    try:
        async with _ws_conn(session_id) as ws:
            for _ in range(4):
                await asyncio.wait_for(ws.recv(), timeout=5)

            # Consume broadcasts continuously so buffers don't fill
            async def bg_drain():
                try:
                    while True:
                        await ws.recv()
                except Exception:
                    pass

            drain_task = asyncio.create_task(bg_drain())
            connected.append(session_id)

            i = 0
            try:
                while not stop.is_set():
                    await ws.send(
                        f'{{"fn":"update_cursor","args":[{i % 12},{(i * 5) % 12},0]}}'
                    )
                    i += 1
                    await asyncio.sleep(TICK)
            finally:
                drain_task.cancel()
    except Exception:
        return


async def _ws_measure(n_load):
    stop = asyncio.Event()
    connected = []

    probe_id = f"probe-ws-{uuid.uuid4()}"
    load_ids = [f"load-{i}-{uuid.uuid4()}" for i in range(n_load)]

    for sid in [probe_id] + load_ids:
        _create_player(sid)

    loaders = [asyncio.create_task(_ws_load(sid, stop, connected)) for sid in load_ids]
    await asyncio.sleep(1.0)

    latencies = []
    async with _ws_conn(probe_id) as ws:
        for _ in range(4):
            await asyncio.wait_for(ws.recv(), timeout=5)

        for i in range(N_WARMUP):
            await _ws_drain(ws)
            await ws.send(f'{{"fn":"update_cursor","args":[{i % 12},{i % 12},0]}}')
            await asyncio.wait_for(ws.recv(), timeout=5)
            await asyncio.sleep(TICK)

        gc.collect()
        gc.disable()
        for i in range(N_SAMPLES):
            await _ws_drain(ws)
            t = time.perf_counter()
            await ws.send(f'{{"fn":"update_cursor","args":[{i % 12},{i % 12},0]}}')
            await asyncio.wait_for(ws.recv(), timeout=5)
            latencies.append((time.perf_counter() - t) * 1000)
            await asyncio.sleep(TICK)
        gc.enable()

    live = len(connected)
    stop.set()
    await asyncio.gather(*loaders, return_exceptions=True)
    return latencies, live


# ---------------------------------------------------------------------------
# SSE+POST transport
# ---------------------------------------------------------------------------


async def _sse_load(session_id, stop, connected, httpx):
    """Background SSE+POST client: spam cursor moves until stopped."""
    cookies = {"hyperspace_id": session_id}
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        verify=False,
        http2=HTTP2,
        timeout=120,
    ) as client:
        reader_done = asyncio.Event()

        async def bg_reader():
            try:
                async with client.stream("GET", "/sse", cookies=cookies) as r:
                    async for _ in r.aiter_bytes():
                        if reader_done.is_set():
                            return
            except Exception:
                pass

        reader_task = asyncio.create_task(bg_reader())
        await asyncio.sleep(0.5)
        connected.append(session_id)

        # Fire-and-forget POSTs to match ws.send() semantics (no await on response)
        pending = set()
        i = 0
        try:
            while not stop.is_set():
                t = asyncio.create_task(
                    client.post(
                        "/action",
                        json={"fn": "update_cursor", "args": [i % 12, (i * 5) % 12, 0]},
                        cookies=cookies,
                    )
                )
                pending.add(t)
                t.add_done_callback(pending.discard)
                i += 1
                await asyncio.sleep(TICK)
        finally:
            reader_done.set()
            reader_task.cancel()
            for t in pending:
                t.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass


def _parse_base_url():
    from urllib.parse import urlparse

    parsed = urlparse(BASE_URL)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    use_ssl = parsed.scheme == "https"
    ssl_ctx = _TLS_CTX if (use_ssl and INSECURE) else (True if use_ssl else None)
    return host, port, ssl_ctx


def _build_post(host, port, cookie, x, y):
    body = json.dumps({"fn": "update_cursor", "args": [x, y, 0]}).encode()
    return (
        f"POST /action HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Cookie: {cookie}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
    ).encode() + body


async def _sse_measure(n_load):
    import httpx

    stop = asyncio.Event()
    connected = []

    probe_id = f"probe-sse-{uuid.uuid4()}"
    load_ids = [f"load-{i}-{uuid.uuid4()}" for i in range(n_load)]

    for sid in [probe_id] + load_ids:
        _create_player(sid)

    loaders = [
        asyncio.create_task(_sse_load(sid, stop, connected, httpx)) for sid in load_ids
    ]
    await asyncio.sleep(1.5)

    host, port, ssl_ctx = _parse_base_url()
    cookie = f"hyperspace_id={probe_id}"
    latencies = []
    http_version = "?"

    # SSE reader via httpx (background task, reads events into a queue)
    sse_client = httpx.AsyncClient(
        base_url=BASE_URL,
        verify=False,
        http2=HTTP2,
        timeout=120,
    )
    event_queue: asyncio.Queue = asyncio.Queue()
    reader_done = asyncio.Event()

    async def bg_reader():
        nonlocal http_version
        try:
            async with sse_client.stream(
                "GET",
                "/sse",
                cookies={"hyperspace_id": probe_id},
            ) as r:
                http_version = r.http_version
                buf = ""
                async for chunk in r.aiter_text():
                    if reader_done.is_set():
                        return
                    buf += chunk
                    while "\n\n" in buf:
                        evt, buf = buf.split("\n\n", 1)
                        if any(ln.startswith("data:") for ln in evt.split("\n")):
                            await event_queue.put(True)
        except (asyncio.CancelledError, Exception):
            pass

    reader_task = asyncio.create_task(bg_reader())

    for _ in range(4):
        await asyncio.wait_for(event_queue.get(), timeout=5)

    # Raw POST connection: write bytes directly like ws.send(),
    # no httpx task competing with the SSE reader for event loop time.
    post_r, post_w = await asyncio.open_connection(host, port, ssl=ssl_ctx)

    async def _drain_204():
        while (await post_r.readline()) != b"\r\n":
            pass

    for i in range(N_WARMUP):
        while not event_queue.empty():
            event_queue.get_nowait()
        post_w.write(_build_post(host, port, cookie, i % 12, i % 12))
        await post_w.drain()
        await asyncio.wait_for(event_queue.get(), timeout=5)
        await _drain_204()
        await asyncio.sleep(TICK)

    gc.collect()
    gc.disable()
    for i in range(N_SAMPLES):
        while not event_queue.empty():
            event_queue.get_nowait()
        t = time.perf_counter()
        post_w.write(_build_post(host, port, cookie, i % 12, i % 12))
        await post_w.drain()
        await asyncio.wait_for(event_queue.get(), timeout=5)
        latencies.append((time.perf_counter() - t) * 1000)
        await _drain_204()
        await asyncio.sleep(TICK)
    gc.enable()

    reader_done.set()
    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass
    post_w.close()
    await sse_client.aclose()

    live = len(connected)
    stop.set()
    await asyncio.gather(*loaders, return_exceptions=True)
    return latencies, live, http_version


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _stats(lat):
    lat = sorted(lat)
    n = len(lat)
    return {
        "mean": statistics.mean(lat),
        "p50": lat[n // 2],
        "p99": lat[int(n * 0.99)],
        "stdev": statistics.stdev(lat) if n > 1 else 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    run_sse = TRANSPORT in ("sse", "both")

    if run_sse:
        try:
            import httpx  # noqa: F401
        except ImportError:
            print(
                "SSE transport needs httpx: uv run --with httpx python -m bench.echo_latency"
            )
            sys.exit(1)

    # Seed a realistic room from one session
    seed_id = f"seed-{uuid.uuid4()}"
    _create_player(seed_id, "Seeder")
    for i in range(100):
        _post_action_sync(seed_id, "create_brick", [i % 12, (i // 12) % 12])
    print("Seeded 100 bricks.\n")

    if TRANSPORT == "both":
        label = f"WS vs SSE+POST {'H2' if HTTP2 else 'H1'}"
    elif TRANSPORT == "sse":
        label = f"SSE+POST {'H2' if HTTP2 else 'H1'}"
    else:
        label = "WS"
    print(
        f"Transport: {label}  |  {N_SAMPLES} samples  |  {N_WARMUP} warmup  |  GC off\n"
    )

    if TRANSPORT == "both":
        hdr = (
            f"{'target':>7} {'live':>5}"
            f"   {'WS p50':>8} {'WS p99':>8}"
            f"   {'SSE p50':>9} {'SSE p99':>9}"
            f"   {'gap':>7}"
        )
        print(hdr)
        print("-" * len(hdr))

        for n_total in (1, 2, 5, 10, 20):
            ws_lat, ws_live = await _ws_measure(n_load=n_total - 1)
            sse_lat, sse_live, proto = await _sse_measure(n_load=n_total - 1)

            ws = _stats(ws_lat)
            sse = _stats(sse_lat)
            gap = sse["p50"] - ws["p50"]

            print(
                f"{n_total:>7} {ws_live + 1:>5}"
                f"   {ws['p50']:>7.1f}ms {ws['p99']:>7.1f}ms"
                f"   {sse['p50']:>8.1f}ms {sse['p99']:>8.1f}ms"
                f"   {gap:>+6.1f}ms"
            )

        print(f"\ngap = SSE p50 − WS p50 at same user count  [{proto}]")
    else:
        hdr = (
            f"{'target':>7} {'live':>5}"
            f"   {'mean':>8} {'p50':>8} {'p99':>8} {'stdev':>8}"
            f"   {'~Hz':>6}"
        )
        print(hdr)
        print("-" * len(hdr))

        for n_total in (1, 2, 5, 10, 20):
            if TRANSPORT == "sse":
                lat, live, proto = await _sse_measure(n_load=n_total - 1)
            else:
                lat, live = await _ws_measure(n_load=n_total - 1)
                proto = "H1>WS"

            s = _stats(lat)
            print(
                f"{n_total:>7} {live + 1:>5}"
                f"   {s['mean']:>7.1f}ms {s['p50']:>7.1f}ms {s['p99']:>7.1f}ms {s['stdev']:>7.1f}ms"
                f"   ~{1000 / s['mean']:>5.0f}"
            )

        print(f"\nProtocol: {proto}")


if __name__ == "__main__":
    asyncio.run(main())
