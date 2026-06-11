default: up

# Start the stack (server + publisher + caddy + tailwind)
up *ARGS: init
    docker compose up {{ ARGS }}

down *ARGS:
    docker compose down {{ ARGS }}

# Create .env from .env.example if missing
init:
    #!/usr/bin/env bash
    set -euo pipefail
    test -f .env || cp .env.example .env

# Rebuild the wasm module and republish it to the running server
publish:
    docker compose up publisher

# Run Playwright e2e against the running stack
test *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose up -d
    echo "Waiting for app on http://localhost:3000 ..."
    for i in $(seq 1 180); do
        if curl -fsS http://localhost:3000/ >/dev/null 2>&1; then break; fi
        sleep 1
    done
    bunx playwright test {{ ARGS }}

check:
    cargo clippy -- -D warnings
    cargo fmt --all -- --check
