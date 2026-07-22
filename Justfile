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

# Benchmark one worker with external players, PostgreSQL stats, and a CPU profile.
bench:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'docker compose --profile benchmark down >/dev/null 2>&1' EXIT
    docker compose up -d --wait postgres
    uv run python -m bench.run
