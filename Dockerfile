FROM ghcr.io/scriptogre/spacetimedb:hypermedia AS builder

USER root
COPY . /app/hyperspace
WORKDIR /app/hyperspace

RUN cargo build --target wasm32-unknown-unknown --release     && wasm-opt -O2 target/wasm32-unknown-unknown/release/hyperspace.wasm -o /hyperspace.wasm

FROM ghcr.io/scriptogre/spacetimedb:hypermedia

COPY --from=builder /hyperspace.wasm /opt/hyperspace/hyperspace.wasm
COPY static /opt/hyperspace/static

ENV SPACETIMEDB_STATIC_DIR=/opt/hyperspace/static

COPY --chmod=755 <<'EOF' /opt/hyperspace/entrypoint.sh
#!/bin/bash
spacetime start &
sleep 3
spacetime publish hyperspace --yes -b /opt/hyperspace/hyperspace.wasm -s local
wait
EOF

ENTRYPOINT ["/opt/hyperspace/entrypoint.sh"]
