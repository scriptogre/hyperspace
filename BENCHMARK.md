# Compression benchmark

Measure Zstd compression across repeated cursor template updates.

## Run it

```bash
uv run python -m bench.compression
```

Default result:

| Updates | Decoded | Standalone | Long-lived |
| ---: | ---: | ---: | ---: |
| 0 | 42,161 B | 22.9:1 | 22.9:1 |
| 1 | 84,325 B | 22.8:1 | 22.9:1 |
| 5 | 252,981 B | 22.7:1 | 67.0:1 |
| 10 | 463,803 B | 22.6:1 | 119.0:1 |
| 25 | 1,096,273 B | 22.6:1 | 257.4:1 |
| 100 | 4,258,632 B | 22.6:1 | **717.1:1** |

```text
cold snapshot      = 42,161 / 1,843 = 22.9:1
100-update stream  = 4,258,632 / 5,939 = 717.1:1
warm update median = 21 B, 2,007.8:1
```

## Workload

| Input | Value |
| --- | ---: |
| World | 16 × 16 cells |
| Players and cursors | 100 |
| Bricks | 0 |
| Updates | 100 cursor moves |
| New subscribers | 0 |

```text
_cursors.html
  → compact HTML
  → multipart body
  → Broadcast
  → Zstd FLUSH_BLOCK
```

`standalone` compresses every update alone. `long-lived` keeps Zstd history.

```text
ratio = decoded multipart bytes / compressed body bytes
```

The benchmark counts application body bytes. It excludes HTTP, TLS, TCP, and IP overhead.

## Push history reuse

```bash
uv run python -m bench.compression --size 32 --players 100 --moves 5000
```

The total ratio approaches the warm-update ratio as the cold snapshot becomes a smaller share of the stream.

Regenerate the GitHub SVG and shareable PNG:

```bash
uv run python -m bench.compression \
  --svg docs/images/compression-benchmark.svg \
  --png docs/images/compression-benchmark.png
```

## Reproduce it

The output includes its Git revision and dependency versions.

```bash
git clone https://github.com/scriptogre/hyperspace.git
cd hyperspace
git checkout <revision-from-result>
uv sync --locked
uv run python -m bench.compression
```

Change the workload:

```bash
uv run python -m bench.compression --size 32
uv run python -m bench.compression --players 10
uv run python -m bench.compression --moves 1000
```

## Limits

- This is a compression benchmark, not a production traffic benchmark.
- Cursor moves change little HTML. Other actions compress less.
- Seeded players add unchanged HTML. Live joins reset Zstd history.
- Zstd history is limited to 8 MiB.

Compare only runs with the same payload, updates, duration, and connection schedule.

## Verify it

Every compressed chunk must decode to its identity multipart body.

```bash
uv run pytest \
  tests/test_compression.py \
  tests/test_compression_benchmark.py \
  tests/test_multipart.py \
  -q
```
