default: up

# Start the stack
up *args:
    docker compose up {{ args }}

# Stop and remove containers
down *args:
    docker compose down {{ args }}

# Rebuild images
build *args:
    docker compose build {{ args }}

# Run the e2e tests in the test container against a healthy stack
test *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose up -d --wait fastapi
    docker compose run --rm tests {{ ARGS }}

makemigrations name="auto":
    docker compose run --rm fastapi tortoise makemigrations --name {{ name }}

migrate:
    docker compose run --rm fastapi tortoise migrate

# Run benchmarks. Suites: all, crowd, latency, transport, browser.
bench suite="all" users="500" secs="30" movers="" slow="0":
    #!/usr/bin/env bash
    set -euo pipefail
    run_crowd() {
      HS_BCAST_LOG=1 POSTGRES_HOST=127.0.0.1 uv run uvicorn app.main:app \
        --host 0.0.0.0 --port 8001 --ws-per-message-deflate false &
      SRV=$!
      trap "kill $SRV 2>/dev/null" EXIT
      sleep 2
      HS_WS_URL=ws://127.0.0.1:8001/ws uv run --with httpx python -m bench.crowd {{users}} {{secs}} {{movers}} {{slow}}
      HS_WS_URL=ws://127.0.0.1:8001/ws uv run --with httpx python -m bench.echo_latency
      kill $SRV 2>/dev/null; wait $SRV 2>/dev/null || true
      trap - EXIT
    }
    run_transport() {
      POSTGRES_HOST=127.0.0.1 uv run --with "httpx[http2]" --with hypercorn --with granian python -m bench.transport
    }
    run_browser() {
      POSTGRES_HOST=127.0.0.1 uv run python -m bench.browser
    }
    case "{{suite}}" in
      all)       run_crowd; run_transport; run_browser ;;
      crowd)     run_crowd ;;
      latency)   run_crowd ;;
      transport) run_transport ;;
      browser)   run_browser ;;
      *) echo "Unknown suite: {{suite}}. Use: all, crowd, latency, transport, browser"; exit 1 ;;
    esac
