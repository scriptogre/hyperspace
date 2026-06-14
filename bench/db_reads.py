"""How much do Postgres round-trips cost without the in-memory player cache?

Times the read strategies a cursor broadcast round could use, against the
running compose Postgres, for N connected users with M of them moved this round:

  cache    read changed cursors only; names/colors from an in-memory dict (current)
  join     read changed cursors LEFT JOIN user (no cache, still 1 round-trip)
  per_row  read changed cursors, then one user lookup per cursor (M+1 round-trips)
  full     read all four tables every round (the pre-delta, pre-cache approach)

    uv run python -m bench.db_reads

The lesson is round-trip COUNT, not "Postgres is slow": cache and join both make
one trip and cost about the same; per_row makes M+1 trips and falls off a cliff.
"""

import asyncio
import os
import statistics
import time

import asyncpg

DSN = os.environ.get(
    "HS_PG_DSN", "postgresql://hyperspace:hyperspace@127.0.0.1:5432/hyperspace"
)
COLORS = ["Cyan", "Purple", "Orange", "Green", "Pink", "Yellow"]
CUR = "identity, x, y, z, active, version"


async def seed(conn: asyncpg.Connection, n: int) -> None:
    await conn.execute('TRUNCATE brick, "user", cursor, event RESTART IDENTITY')
    await conn.executemany(
        'INSERT INTO "user" (identity, name, color, online) VALUES ($1, $2, $3, true)',
        [(f"u{i}", f"Player{i}", COLORS[i % 6]) for i in range(n)],
    )
    await conn.executemany(
        "INSERT INTO cursor (identity, x, y, z, active) VALUES ($1, $2, $3, 0, true)",
        [(f"u{i}", i % 12, (i * 2) % 12) for i in range(n)],
    )
    await conn.executemany(
        "INSERT INTO brick (x, y, z, color) VALUES ($1, $2, $3, $4)",
        [(i % 12, (i // 12) % 12, i % 5, COLORS[i % 6]) for i in range(100)],
    )
    await conn.executemany(
        "INSERT INTO event (kind, identity, timestamp) VALUES ($1, $2, now())",
        [("BrickCreated", f"u{i % n}") for i in range(40)],
    )


async def player_cache(conn: asyncpg.Connection) -> dict:
    rows = await conn.fetch('SELECT identity, name, color FROM "user"')
    return {r["identity"]: (r["name"], r["color"].lower()) for r in rows}


async def mark_moved(conn: asyncpg.Connection, m: int) -> int:
    """Bump m cursor versions (via the stamp trigger); return the watermark below them."""
    wm = await conn.fetchval("SELECT COALESCE(max(version), 0) FROM cursor")
    await conn.execute(
        "UPDATE cursor SET x = (x + 1) % 12 WHERE identity = ANY($1::text[])",
        [f"u{i}" for i in range(m)],
    )
    return wm


async def read_cache(conn, wm, cache):
    rows = await conn.fetch(
        f"SELECT {CUR} FROM cursor WHERE version > $1 ORDER BY version", wm
    )
    return [
        (r["identity"], r["x"], r["y"], cache.get(r["identity"], ("?", "cyan")))
        for r in rows
    ]


async def read_join(conn, wm, _cache):
    rows = await conn.fetch(
        "SELECT c.identity, c.x, c.y, c.z, c.active, c.version, u.name, u.color "
        'FROM cursor c LEFT JOIN "user" u ON u.identity = c.identity '
        "WHERE c.version > $1 ORDER BY c.version",
        wm,
    )
    return [(r["identity"], r["x"], r["y"], (r["name"], r["color"])) for r in rows]


async def read_per_row(conn, wm, _cache):
    rows = await conn.fetch(
        f"SELECT {CUR} FROM cursor WHERE version > $1 ORDER BY version", wm
    )
    out = []
    for r in rows:
        u = await conn.fetchrow(
            'SELECT name, color FROM "user" WHERE identity = $1', r["identity"]
        )
        out.append((r["identity"], r["x"], r["y"], (u["name"], u["color"])))
    return out


async def read_full(conn, _wm, _cache):
    bricks = await conn.fetch(
        "SELECT id, x, y, z, color, dragged_by FROM brick ORDER BY id"
    )
    users = await conn.fetch('SELECT identity, name, color, online FROM "user"')
    cursors = await conn.fetch(
        "SELECT identity, x, y, z FROM cursor WHERE active ORDER BY identity"
    )
    events = await conn.fetch("SELECT id, kind, identity FROM event ORDER BY id")
    return bricks, users, cursors, events


async def timeit(fn, conn, wm, cache, rounds: int):
    await fn(conn, wm, cache)  # warm
    samples = []
    for _ in range(rounds):
        t = time.perf_counter()
        await fn(conn, wm, cache)
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    return (
        statistics.mean(samples),
        samples[len(samples) // 2],
        samples[int(len(samples) * 0.99)],
    )


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    print(
        f"{'N':>5} {'moved':>6} {'strategy':>8} {'trips':>6} {'mean':>9} {'p50':>9} {'p99':>9}"
    )
    for n, m in [(100, 100), (600, 600), (1000, 1000), (1000, 250)]:
        await seed(conn, n)
        cache = await player_cache(conn)
        wm = await mark_moved(conn, m)
        for name, fn, trips in [
            ("cache", read_cache, "1"),
            ("join", read_join, "1"),
            ("per_row", read_per_row, f"{m + 1}"),
            ("full", read_full, "4"),
        ]:
            rounds = 30 if name == "per_row" and m > 300 else 200
            mean, p50, p99 = await timeit(fn, conn, wm, cache, rounds)
            print(
                f"{n:>5} {m:>6} {name:>8} {trips:>6} {mean:>7.2f}ms {p50:>7.2f}ms {p99:>7.2f}ms"
            )
        print()
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
