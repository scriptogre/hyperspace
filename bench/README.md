# Benchmarks

Tools to measure how many concurrent users one worker holds and where a broadcast
spends its time. Re-run them whenever you touch the render, broadcast, or query path.

## The catch: loopback is not the internet

`crowd.py` and `echo_latency.py` run on the same machine over loopback: no RTT, no
loss, no bandwidth limit, no TLS, and the fake clients read instantly. That
measures the server's CPU, not what 1000 real phones feel. Two things loopback
hides, and how to surface each:

- A slow client stalling the broadcast loop: `crowd.py` slow-reader mode.
- Real RTT / loss / bandwidth: the netem load container (`loadgen/`).

## Tools

- `crowd.py`        multiprocess load generator (movers, slow readers, idle)
- `echo_latency.py` user-felt round-trip latency, with background load
- `db_reads.py`     Postgres read-strategy cost (cache vs join vs N+1)
- `render.py`       cursor-fragment render cost
- `loadgen/`        run any of the above behind a netem-shaped link

## Run the instrumented server

```
just up           # postgres
just bench-serve  # app on 0.0.0.0:8001, prints a BCAST line each second
```

## Capacity + bottleneck

```
just crowd 1000 30 1000        # 1000 users, all moving
just crowd 1000 30 250         # 1000 connected, 250 moving
```

Watch the server's BCAST line:

```
BCAST n=600 rounds/s=18 build=5.0 compress=0.1 send=2.9 total=8.0 blob_bytes=8554
```

`build` = render, `compress` = zstd, `send` = fan-out. When `total` nears the
20ms round budget (`TICK`) under steady churn, that is the ceiling.

## Slow readers (server-side backpressure)

The broadcast loop sends sequentially and awaits each client:

```python
for ws in connections: await ws.send_bytes(blob)
```

A client that reads slowly fills its buffer, and that await blocks the whole loop.
Add slow readers and watch `send` spike:

```
just crowd 600 30 300 300   # 300 movers + 300 slow readers
```

## Real network (netem container)

```
just loadgen echo_latency                  # default: 80ms / 20ms jitter / 1% loss / 10mbit
NETEM_DELAY=150ms just loadgen echo_latency
just loadgen crowd 600 30 600 100          # shaped load
```

Runs the tool inside a Linux container that shapes its link with `tc netem` (both
directions when the host has the ifb module, uplink-only otherwise). Needs
`bench-serve` reachable at host.docker.internal:8001.

## Knobs

- `HS_WS_URL`   target server (default `ws://127.0.0.1:8001/ws`)
- `HS_SLOW_READ`   seconds between reads for slow clients (default 0.25)
- `NETEM_DELAY` / `NETEM_JITTER` / `NETEM_LOSS` / `NETEM_RATE`   shaping for `loadgen`
