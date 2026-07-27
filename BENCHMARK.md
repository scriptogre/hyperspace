# Compression benchmark

Measure Zstd compression across repeated full-world HTML updates.

## Run it

```bash
uv run python -m bench.compression
```

Default result:

| Updates | Decoded | Standalone | Long-lived |
| ---: | ---: | ---: | ---: |
| 0 | 193,294 B | 40.8:1 | 40.8:1 |
| 1 | 386,589 B | 40.8:1 | 40.8:1 |
| 5 | 1,159,769 B | 40.7:1 | 120.0:1 |
| 10 | 2,126,246 B | 40.7:1 | 214.6:1 |
| 25 | 5,025,681 B | 40.6:1 | 472.9:1 |
| 100 | 19,522,865 B | 40.6:1 | **1,369.3:1** |

```text
cold snapshot      = 193,294 / 4,735 = 40.8:1
100-update stream  = 19,522,865 / 14,258 = 1,369.3:1
warm update median = 47 B, 4,112.7:1
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
_world.html
  → compact HTML
  → multipart body
  → SharedStream
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

```text
decoded    = 3,001,624,363 B
compressed =       492,589 B
ratio      =       6,093.6:1
warm p50   =          89 B, 6,743.9:1
```

The ratio approaches the average warm-update ratio:

| Updates | Default ratio |
| ---: | ---: |
| 100 | 1,369.3:1 |
| 1,000 | 3,015.1:1 |
| 5,000 | 3,363.5:1 |
| 10,000 | 3,405.0:1 |

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
