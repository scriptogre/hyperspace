# Optimizations

How we took one Python worker from choking at a few dozen users to smoothly
serving 1000+, without giving up clean code or the one rule we never broke:
**Postgres is the single source of truth for everyone.**

The pattern every time: something became the bottleneck, we measured it, we fixed it.

## The setup

The server renders HTML, sends it over a WebSocket, and the browser morphs it
into place. All state lives in Postgres. There is no app state in JavaScript.

Every change follows the same path: write to Postgres, Postgres tells us
something changed, we render and broadcast.

## 1. We rendered the whole page once per person

Every change made the server build the entire screen separately for each viewer.
At 600 users that was **441ms** per update. But the screen looks nearly identical
for everyone.

Fix: build it once, send the same bytes to all 600. The few per-person bits (your
own cursor, the welcome box) moved out of the shared HTML.

Result: **441ms to 0.7ms.**

## 2. Each action hit the database too many times

Placing one brick ran 5 queries back to back: count the cell, look up your color,
insert, write a log row, trim the log. About **6ms**.

Fix: do it in one SQL statement (count, cap check, your color, and insert all at
once). Also told Postgres not to wait for the disk on every commit
(`synchronous_commit=off`).

Result: **6ms to 0.5ms.**

## 3. Cursors flooded the database

600 people moving the mouse meant thousands of tiny writes per second, and each
one woke everyone up.

Fix: hold cursor moves in memory for 33ms, then write them all in one batch.
600 writes became 1.

Result: the flood stopped, the database stayed calm.

## 4. The message itself was huge

Rendering once fixed the CPU, but each person still received the *whole* screen
every update. At 600 users that screen was **1.1MB** (it held 600 cursors). Sent
to 600 people, that is gigabytes per second.

Fix: split the screen into two parts (`#stage` and `#cursors`) and send only the
part that changed. Then slim each cursor's HTML from 1.4KB to 230 bytes by moving
its styling into CSS.

Result: **1.06MB to 135KB.**

## 5. Compression was secretly eating the CPU

Compression was on, which made the bytes small. But WebSocket compression runs
once *per connection*. So the server compressed the same message 600 separate
times. That was **57ms** per update at only 160 users.

Fix: compress it ourselves **once** with zstd, then send the same compressed
bytes to everyone. The browser unpacks it with a tiny 8KB library (fzstd). We
turned off the WebSocket's built-in compression so it would not double the work.

Result: compression **57ms to 0.1ms.** We got small bytes *and* low CPU at the
same time, which is usually a pick-one tradeoff.

## 6. The database read became the slow part

Every update re-read all four tables (bricks, users, cursors, events), even when
only a cursor moved. About **18.8ms** at 640 users.

Fix: keep the rarely-changing user list (names, colors) in memory, refreshed only
when someone joins or renames. And read only the table that actually changed.

Result: a cursor update went from 4 reads to 1. **18.8ms to 6ms.**

At this point: **1000 users on one worker, 14ms per update.**

## 7. We rendered every cursor even when few moved

With 1000 cursors, every update rebuilt all 1000, even if only 50 people moved.

Fix: let Postgres tell us exactly what changed. We added a `version` number that
the database stamps on every cursor write, then ask for "cursors newer than the
last version I saw":

```sql
SELECT ... FROM cursor WHERE version > :last_seen
```

We render only those. Idle cursors cost nothing.

Result: you pay for **movement, not for how many people are connected.** At a
realistic mix (a fraction moving at once), one worker reaches ~4000 users.

## Alternatives we ruled out

- **Postgres, not Turso.** Turso (the SQLite rewrite) only works well embedded in
  a single process, and we needed several workers. Postgres gives us the notify
  bus and multiple workers out of the box.
- **No message bus.** Each worker holds its own Postgres LISTEN, so every worker
  already hears every change directly. A bus like NATS would sit in the middle
  doing nothing.
- **uvicorn, not Granian.** Granian (a Rust server) wins on plain HTTP throughput,
  but it crosses the Python/Rust boundary once per message, which makes our
  many-tiny-WebSocket sends 5 to 9x slower.
- **Cursors stay in Postgres.** Keeping them in app memory would be faster, but it
  would make the database no longer the source of truth. Not worth breaking the rule.
- **No Redis cache.** Redis is a separate process, so a read still pays a network
  round trip. That is the same cost as reading Postgres, so it would not help.

## Aren't the database round-trips the real cost?

You might expect that, without colocating data and logic the way SpacetimeDB
does, every cursor move paying a trip to Postgres would be the bottleneck. We
measured it (`bench/db_reads.py`). It is not.

Reading the changed cursors for a round where 1000 people moved, against a normal
Postgres:

| how we read it                         | trips/round | time   |
| -------------------------------------- | ----------- | ------ |
| one query, names from the memory cache | 1           | 0.7ms  |
| one query with a JOIN, no cache        | 1           | 1.2ms  |
| read all four tables every round       | 4           | 1.3ms  |
| one user lookup per cursor             | 1001        | 125ms  |

Each round-trip is about 0.12ms. So the cost is not Postgres being slow. It is
how many trips you make.

One query is cheap, even when it reads everything. The memory cache saves about
half a millisecond over a plain JOIN, so it is a convenience, not the thing
holding the system up.

The cliff is the last row: one query per cursor, the classic N+1. A thousand
trips back to back is 125ms. That is the pattern to never write.

## So do we still need SpacetimeDB?

SpacetimeDB runs your logic inside the database, against in-memory tables, so a
read is a function call: no socket, no SQL parse, no row-to-object step. It
removes the round-trip entirely.

We reach a similar place a different way: we refuse to make more than one trip per
round. The version-column change feed, render-once, the player cache, and raw SQL
on the hot paths all exist to hold that line.

The difference is who carries the discipline. SpacetimeDB lets you write the naive
per-cursor loop and stays fast because nothing leaves the process. We have to keep
the access batched ourselves. For a simple world (cursors and bricks) that is
easy. For heavy per-entity simulation (physics, AI touching hundreds of entities
a tick) you cannot fold the logic into one query, and that is where colocation
wins and we would hit the 125ms wall.

Two honest notes. The ORM is its own tax: reading everything raw is 1.3ms, but
through Tortoise it was 18.8ms, almost all of it building objects. We dodge that
with raw SQL on the hot paths. And our remaining bottleneck is rendering HTML,
about 14ms for a thousand cursors, which SpacetimeDB sidesteps because it ships
row deltas and lets the client draw.

## The throughline

Two ideas did most of the work:

1. **Do shared work once, not per person.** Render once, compress once.
2. **Only touch what changed.** Split the screen, cache the stable parts, ask the
   database for the delta.

And the rule we kept the whole way: **the database is the source of truth for
everyone.** Postgres, used well, gets you most of the way to a real-time engine
like SpacetimeDB, with tools your ops team already runs.
