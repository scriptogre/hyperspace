# Benchmarks

Tools to measure how many concurrent users one worker holds, and to see which
stage of a broadcast is the bottleneck. Re-run these whenever you change the
render, broadcast, or query path.

## Setup

Start Postgres (the local stack already does), then run the app on `:8001` with
broadcast instrumentation on:

```
just up            # postgres (+ the docker app, optional)
just bench-serve   # instrumented app on :8001, prints a BCAST line each second
```

`bench-serve` runs on the host so `HS_BCAST_LOG` prints to your terminal and
there are no Docker network hops in the numbers. It talks to the compose
Postgres on `:5432`.

## Capacity + bottleneck: crowd + BCAST

In a second shell, push synthetic users at the server:

```
just crowd 600 30        # 600 users, all moving, for 30s
just crowd 1000 30 400   # 1000 connected, 400 moving
```

Watch the server's per-second line:

```
BCAST n=600 rounds/s=48 build=0.7 compress=0.2 send=11.3 total=12.2 blob_bytes=1840
```

- **n** actual connected clients
- **build / compress / send** ms per round: render, zstd, fan-out
- **total** ms per round; when it nears the round budget (`TICK`=20ms) under
  steady churn, the loop is at capacity
- **send** grows with `n` (fan-out is O(connections)) and is the usual floor

Step the user count up until `total` approaches the round budget. That is the
ceiling for that mover fraction.

## Latency feel: echo_latency

Round-trip from sending a cursor move to receiving the broadcast that reflects
it, with background load, across a small ladder:

```
just bench-latency
```

Single-process, so it is honest only to a few hundred users. For higher counts
use `crowd` and read BCAST.

## Knobs

- `HS_WS_URL` targets a different server (default `ws://127.0.0.1:8001/ws`).
- `bench.crowd <users> <secs> [movers]` splits load across processes
  (250 clients each) so the generator is not the bottleneck.
