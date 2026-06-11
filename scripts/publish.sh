#!/usr/bin/env bash
# Build the wasm module and publish it to the running SpacetimeDB server.
# Runs inside a stock `rust:1` container (no custom image). The official
# server image ships no CLI, so fetch `spacetimedb-cli` from the release
# tarball once and cache it in the /opt/stdb volume.
set -euo pipefail

export PATH="/opt/stdb:$PATH"

if ! command -v spacetimedb-cli >/dev/null 2>&1; then
  case "$(uname -m)" in
    x86_64)  target=x86_64-unknown-linux-gnu ;;
    aarch64) target=aarch64-unknown-linux-gnu ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
  esac
  echo "Fetching spacetimedb-cli ($target)..."
  curl -fsSL "https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.4.1/spacetime-${target}.tar.gz" \
    | tar xz -C /opt/stdb
fi

rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown

url="${SPACETIMEDB_URL:-http://spacetimedb:3000}"
wasm=target/wasm32-unknown-unknown/release/hyperspace.wasm

publish() { spacetimedb-cli publish hyperspace --bin-path "$wasm" --server "$url" --yes; }

# A cached login token becomes invalid if the server's JWT keys changed
# (e.g. a fresh data volume). Clear creds and retry once.
if ! publish; then
  echo "publish failed; clearing cached login and retrying against the current server" >&2
  rm -rf /root/.config/spacetime /root/.local/share/spacetime 2>/dev/null || true
  publish
fi
