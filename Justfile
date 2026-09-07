default: up

# Start the stack
up *args:
    docker compose up {{ args }}

# Run the production stack on this Mac for the live demo
demo:
    #!/usr/bin/env bash
    set -euo pipefail
    interface="$(route -n get default | awk '/interface:/{print $2}')"
    lan_ip="$(ipconfig getifaddr "$interface")"
    DOMAIN="http://${lan_ip}:8000" docker compose \
        --env-file .env \
        -f docker-compose.production.yml \
        -f docker-compose.demo.yml \
        up -d --build --wait
    echo "Demo: http://${lan_ip}:8000"

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

# Push and deploy the committed main branch to the ThinkCentre.
deploy:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -n "$(git status --porcelain)" ]]; then
        echo "Commit the working tree before deploying." >&2
        exit 1
    fi
    git push origin main
    ssh thinkcentre '
      set -eu
      git -C /home/chris/Projects/hyperspace pull --ff-only origin main
      sudo systemctl restart compose-hyperspace.service
    '
    curl --fail --retry 12 --retry-all-errors --retry-delay 5 \
      https://hyperspace.christiantanul.com/health

# Benchmark one worker with external players, PostgreSQL stats, and a CPU profile.
bench:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'docker compose --profile benchmark down >/dev/null 2>&1' EXIT
    docker compose up -d --wait postgres
    uv run python -m bench.run
