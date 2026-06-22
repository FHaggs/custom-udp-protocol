#!/usr/bin/env bash
set -euo pipefail

TX_NS="rtp-tx"
RX_NS="rtp-rx"
TX_IF="veth-tx"
RX_IF="veth-rx"
TX_IP="10.20.0.1/24"
RX_IP="10.20.0.2/24"

command="${1:-}"

case "$command" in
  up)
    ip netns add "$TX_NS" 2>/dev/null || true
    ip netns add "$RX_NS" 2>/dev/null || true
    ip link add "$TX_IF" type veth peer name "$RX_IF" 2>/dev/null || true
    ip link set "$TX_IF" netns "$TX_NS"
    ip link set "$RX_IF" netns "$RX_NS"

    ip -n "$TX_NS" link set lo up
    ip -n "$RX_NS" link set lo up
    ip -n "$TX_NS" addr add "$TX_IP" dev "$TX_IF" 2>/dev/null || true
    ip -n "$RX_NS" addr add "$RX_IP" dev "$RX_IF" 2>/dev/null || true
    ip -n "$TX_NS" link set "$TX_IF" up
    ip -n "$RX_NS" link set "$RX_IF" up

    echo "Namespaces criados."
    echo "Sender namespace: $TX_NS ($TX_IF -> 10.20.0.1)"
    echo "Receiver namespace: $RX_NS ($RX_IF -> 10.20.0.2)"
    ;;
  down)
    ip netns del "$TX_NS" 2>/dev/null || true
    ip netns del "$RX_NS" 2>/dev/null || true
    ;;
  status)
    ip netns list
    echo
    ip -n "$TX_NS" addr show 2>/dev/null || true
    echo
    ip -n "$RX_NS" addr show 2>/dev/null || true
    ;;
  ping)
    ip netns exec "$TX_NS" ping -c 2 10.20.0.2
    ;;
  *)
    echo "Uso: sudo scripts/netns_lab.sh {up|down|status|ping}" >&2
    exit 1
    ;;
esac