"""
Browser-based transport benchmark with real HTTP/3 via Caddy + Chromium.

Measures action→DOM-morph latency in a real browser using MutationObserver.
Chromium negotiates HTTP/3 (QUIC) via --origin-to-force-quic-on.

    POSTGRES_HOST=127.0.0.1 uv run python -m bench.browser
"""

import asyncio
import os
import statistics
import subprocess
import sys
import time

import asyncpg

BACKEND_PORT = 8001
CADDY_PORT = 9443
CADDY_URL = f"https://localhost:{CADDY_PORT}"
N_SAMPLES = 80

CERT = "/tmp/hs-bench-cert.pem"
KEY = "/tmp/hs-bench-key.pem"

PG_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://hyperspace:hyperspace@127.0.0.1:5432/hyperspace",
)

CADDYFILE = f"""\
{{
    auto_https disable_redirects
    admin off
}}

localhost:{CADDY_PORT} {{
    tls internal
    reverse_proxy localhost:{BACKEND_PORT}
}}
"""

MEASURE_JS = """
async (n) => {
    const results = [];
    const app = document.getElementById('app');

    for (let i = 0; i < n; i++) {
        const morphed = new Promise(resolve => {
            const obs = new MutationObserver(() => {
                obs.disconnect();
                resolve();
            });
            obs.observe(app, { childList: true, subtree: true, characterData: true });
            setTimeout(() => { obs.disconnect(); resolve(); }, 5000);
        });

        const t0 = performance.now();
        hyperspace.post('/bricks', {x: i % 12, y: Math.floor(i / 12)});
        await morphed;
        results.push(performance.now() - t0);

        await new Promise(r => setTimeout(r, 50));
    }
    return results;
}
"""

PROTOCOL_JS = """
() => {
    const entries = performance.getEntriesByType('resource')
        .map(e => e.nextHopProtocol)
        .filter(Boolean);
    const nav = performance.getEntriesByType('navigation')
        .map(e => e.nextHopProtocol)
        .filter(Boolean);
    return [...new Set([...nav, ...entries])].join(', ') || '?';
}
"""


def wait_backend(timeout=15):
    from urllib.request import urlopen

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urlopen(f"http://127.0.0.1:{BACKEND_PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def wait_caddy(timeout=10):
    import ssl
    import urllib.request

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            req = urllib.request.Request(f"{CADDY_URL}/health")
            with urllib.request.urlopen(req, context=ctx, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


async def clear_bricks():
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute("TRUNCATE brick, event RESTART IDENTITY CASCADE")
    finally:
        await conn.close()


def fmt(lat):
    lat = sorted(lat)
    n = len(lat)
    return {
        "mean": statistics.mean(lat),
        "p50": lat[n // 2],
        "p95": lat[int(n * 0.95)],
        "p99": lat[int(n * 0.99)],
        "max": max(lat),
    }


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run: uv run playwright install chromium")
        sys.exit(1)

    # Start backend (plain HTTP, Caddy handles TLS)
    env = {**os.environ, "POSTGRES_HOST": "127.0.0.1"}
    backend = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(BACKEND_PORT),
            "--ws-per-message-deflate",
            "false",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start Caddy
    cfg_path = "/tmp/hs-bench-browser-Caddyfile"
    with open(cfg_path, "w") as f:
        f.write(CADDYFILE)
    caddy = subprocess.Popen(
        ["caddy", "run", "--config", cfg_path, "--adapter", "caddyfile"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if not wait_backend():
            print("Backend failed to start")
            return
        if not wait_caddy():
            print("Caddy failed to start")
            return

        await clear_bricks()

        async with async_playwright() as p:
            # Force QUIC for H3
            browser = await p.chromium.launch(
                args=[
                    f"--origin-to-force-quic-on=localhost:{CADDY_PORT}",
                    "--enable-quic",
                ],
            )
            context = await browser.new_context(ignore_https_errors=True)

            # --- Join as player ---
            page = await context.new_page()
            await page.goto(CADDY_URL)
            form = page.locator("#player-form")
            if await form.count() > 0:
                await page.fill("[name=name]", "BenchBot")
                # Color is a hidden input, set by clicking a color button
                await page.click("[data-color]:first-child")
                await page.click("[type=submit]")
                await page.wait_for_timeout(1500)

            # Reload to let browser discover alt-svc / settle H3
            await page.reload()
            await page.wait_for_timeout(2000)

            # --- WS benchmark ---
            print("\n  Browser via Caddy (uvicorn backend)")
            print("  ------------------------------------")
            print("    WS ...", end="", flush=True)
            ws_lat = await page.evaluate(MEASURE_JS, N_SAMPLES)
            ws_proto = await page.evaluate(PROTOCOL_JS)
            if ws_lat:
                s = fmt(ws_lat)
                print(
                    f" mean={s['mean']:.1f}ms"
                    f" p50={s['p50']:.1f}ms"
                    f" p99={s['p99']:.1f}ms"
                    f"  proto:[{ws_proto}]"
                )
            else:
                print(" FAILED (no measurements)")
                ws_lat = None

            # --- SSE benchmark ---
            await clear_bricks()
            await page.goto(f"{CADDY_URL}/?transport=sse")
            await page.wait_for_timeout(2000)

            print("    SSE+POST ...", end="", flush=True)
            sse_lat = await page.evaluate(MEASURE_JS, N_SAMPLES)
            sse_proto = await page.evaluate(PROTOCOL_JS)
            if sse_lat:
                s = fmt(sse_lat)
                print(
                    f" mean={s['mean']:.1f}ms"
                    f" p50={s['p50']:.1f}ms"
                    f" p99={s['p99']:.1f}ms"
                    f"  proto:[{sse_proto}]"
                )
            else:
                print(" FAILED (no measurements)")
                sse_lat = None

            await browser.close()

        # --- Summary ---
        print(f"\n\n{'=' * 80}")
        print(f"  BROWSER BENCHMARK  ({N_SAMPLES} samples, Caddy TLS, loopback)")
        print(f"{'=' * 80}\n")

        hdr = (
            f"{'Transport':<12} {'Proto':<16}"
            f" {'Mean':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8}"
        )
        print(hdr)
        print("-" * len(hdr))

        if ws_lat:
            s = fmt(ws_lat)
            print(
                f"{'WS':<12} {ws_proto:<16}"
                f" {s['mean']:>7.1f}ms {s['p50']:>7.1f}ms {s['p95']:>7.1f}ms"
                f" {s['p99']:>7.1f}ms {s['max']:>7.1f}ms"
            )
        if sse_lat:
            s = fmt(sse_lat)
            print(
                f"{'SSE+POST':<12} {sse_proto:<16}"
                f" {s['mean']:>7.1f}ms {s['p50']:>7.1f}ms {s['p95']:>7.1f}ms"
                f" {s['p99']:>7.1f}ms {s['max']:>7.1f}ms"
            )

        print(
            "\nChromium with --origin-to-force-quic-on bypasses alt-svc and\n"
            "uses QUIC/HTTP3 directly. 'h3' in proto confirms HTTP/3."
        )

    finally:
        caddy.terminate()
        caddy.wait(timeout=5)
        backend.terminate()
        backend.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
