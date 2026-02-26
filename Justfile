spacetime := env('HOME') / ".local/bin/spacetime"
module_name := "hyperspace"

# Start SpacetimeDB + publish module + run Rocket server
default: spacetimedb generate
    cargo run

# Ensure SpacetimeDB is installed, running, and module is deployed
spacetimedb:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v "{{spacetime}}" &>/dev/null || \
        (echo "Installing SpacetimeDB..." && curl -sSf https://install.spacetimedb.com | sh)
    if nc -z 127.0.0.1 3000 2>/dev/null; then
        echo "SpacetimeDB already running on port 3000"
    else
        "{{spacetime}}" start 2>/dev/null &
        echo "Waiting for SpacetimeDB..."
        for i in $(seq 1 30); do
            if nc -z 127.0.0.1 3000 2>/dev/null; then break; fi
            sleep 0.5
        done
        if ! nc -z 127.0.0.1 3000 2>/dev/null; then
            echo "ERROR: SpacetimeDB failed to start"
            exit 1
        fi
    fi
    "{{spacetime}}" publish {{module_name}} --project-path . --yes --delete-data

# Regenerate client bindings after module changes
generate:
    "{{spacetime}}" generate --lang rust --project-path . --out-dir src/module_bindings --yes

# Wipe database and redeploy
reset:
    "{{spacetime}}" publish {{module_name}} --project-path . --yes --delete-data

# Run Playwright tests (server must be running)
test:
    npx playwright test

# Lint
check:
    cargo clippy -- -D warnings
    cargo fmt --all -- --check
