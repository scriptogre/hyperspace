set dotenv-load := true   # Load .env (COMPOSE_FILE picks local vs production)

default: up

# Start the stack. Local: app + postgres + tailwind watch. Production: app + postgres.
up *args:
    docker compose up {{ args }}

# Stop and remove containers
down:
    docker compose down --remove-orphans

# Rebuild images
build:
    docker compose build

# One-shot production CSS build (the local stack watches automatically)
css:
    bun install
    bunx tailwindcss -i app/static/css/input.css -o app/static/css/output.css --minify

# Install dependencies on the host (for editor tooling)
install:
    uv sync


# Run the instrumented server on :8001 for load testing (uses the compose postgres on :5432)
bench-serve:
    HS_BCAST_LOG=1 POSTGRES_HOST=127.0.0.1 uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --ws-per-message-deflate false

# Push N users at a running `bench-serve`: movers + slow readers (rest idle)
crowd users="500" secs="30" movers="" slow="0":
    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.crowd {{ users }} {{ secs }} {{ movers }} {{ slow }}

# Latency ladder (mean/p50/p99) against a running `bench-serve`
bench-latency:
    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.echo_latency

# Run a bench tool through a netem-shaped container (real-ish RTT/loss/bandwidth).
# Override with NETEM_DELAY/JITTER/LOSS/RATE env vars. Needs `bench-serve` running.
loadgen tool="echo_latency" *args:
    docker build -q -t hyperspace-loadgen bench/loadgen
    docker run --rm --cap-add=NET_ADMIN --add-host=host.docker.internal:host-gateway \
      -e HS_WS_URL=ws://host.docker.internal:8001/ws \
      -e NETEM_DELAY -e NETEM_JITTER -e NETEM_LOSS -e NETEM_RATE \
      -v {{ justfile_directory() }}:/app -w /app \
      hyperspace-loadgen python -m bench.{{ tool }} {{ args }}
