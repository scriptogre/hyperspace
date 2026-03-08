spacetime := justfile_directory() / ".." / "SpacetimeDB" / "target" / "release" / "spacetimedb-cli"

up:
    #!/usr/bin/env bash
    set -euo pipefail
    pkill -f spacetimedb || true
    sleep 1
    rm -rf ~/.local/share/spacetime/data
    SPACETIMEDB_STATIC_DIR="$(pwd)/static" "{{spacetime}}" start &
        echo "Waiting for SpacetimeDB..."
        for i in $(seq 1 30); do
            if nc -z 127.0.0.1 3000 2>/dev/null; then break; fi
            sleep 0.5
        done
    if ! nc -z 127.0.0.1 3000 2>/dev/null; then
        echo "ERROR: SpacetimeDB failed to start on port 3000"
        exit 1
    fi
    "{{spacetime}}" publish hyperspace --yes

down:
    pkill -f spacetimedb || true

test:
    npx playwright test

check:
    cargo clippy -- -D warnings
    cargo fmt --all -- --check
