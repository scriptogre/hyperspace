#!/usr/bin/env bash
# Shape this container's link with netem, then run the given bench command.
set -e

IFACE="${NETEM_IFACE:-eth0}"
DELAY="${NETEM_DELAY:-80ms}"
JITTER="${NETEM_JITTER:-20ms}"
LOSS="${NETEM_LOSS:-1%}"
RATE="${NETEM_RATE:-10mbit}"

# Egress (uplink): the cursor updates we send to the server.
tc qdisc add dev "$IFACE" root netem delay "$DELAY" "$JITTER" loss "$LOSS" rate "$RATE"

# Ingress (downlink): the broadcasts from the server, redirected through ifb.
# Best-effort: needs the ifb kernel module, falls back to uplink-only if absent.
if ip link add ifb0 type ifb 2>/dev/null; then
  ip link set ifb0 up
  tc qdisc add dev "$IFACE" handle ffff: ingress
  tc filter add dev "$IFACE" parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0
  tc qdisc add dev ifb0 root netem delay "$DELAY" "$JITTER" loss "$LOSS" rate "$RATE"
  echo "netem both directions: delay=$DELAY jitter=$JITTER loss=$LOSS rate=$RATE"
else
  echo "netem uplink only (ifb unavailable): delay=$DELAY jitter=$JITTER loss=$LOSS rate=$RATE"
fi

exec "$@"
