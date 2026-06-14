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

makemigrations name="auto":
    docker compose run --rm fastapi tortoise makemigrations --name {{ name }}

migrate:
    docker compose run --rm fastapi tortoise migrate

# Start bench server, run crowd load + latency ladder, then stop.
bench users="500" secs="30" movers="" slow="0":
    #!/usr/bin/env bash
    HS_BCAST_LOG=1 POSTGRES_HOST=127.0.0.1 uv run uvicorn app.main:app \
      --host 0.0.0.0 --port 8001 --ws-per-message-deflate false &
    SRV=$!
    trap "kill $SRV 2>/dev/null" EXIT
    sleep 2
    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.crowd {{users}} {{secs}} {{movers}} {{slow}}
    HS_WS_URL=ws://127.0.0.1:8001/ws uv run python -m bench.echo_latency
