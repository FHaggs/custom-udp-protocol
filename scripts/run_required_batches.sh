#!/usr/bin/env bash
set -euo pipefail

RESULTS_ROOT="${RESULTS_ROOT:-results}"
RECEIVER_HOST="${RECEIVER_HOST:-10.20.0.2}"
SENDER_BIND_HOST="${SENDER_BIND_HOST:-0.0.0.0}"
RECEIVER_BIND_HOST="${RECEIVER_BIND_HOST:-0.0.0.0}"
TX_NAMESPACE="${TX_NAMESPACE:-rtp-tx}"
RX_NAMESPACE="${RX_NAMESPACE:-rtp-rx}"
TX_INTERFACE="${TX_INTERFACE:-veth-tx}"
RX_INTERFACE="${RX_INTERFACE:-veth-rx}"
IMPAIR_SIDE="${IMPAIR_SIDE:-sender}"
CAPTURE_FLAG="${CAPTURE_FLAG:---capture-pcap}"

common_args=(
  --scenario-set required
  --receiver-host "$RECEIVER_HOST"
  --sender-bind-host "$SENDER_BIND_HOST"
  --receiver-bind-host "$RECEIVER_BIND_HOST"
  --tx-namespace "$TX_NAMESPACE"
  --rx-namespace "$RX_NAMESPACE"
  --impair-side "$IMPAIR_SIDE"
)

if [[ "$IMPAIR_SIDE" == "sender" ]]; then
  common_args+=(--tx-interface "$TX_INTERFACE")
else
  common_args+=(--rx-interface "$RX_INTERFACE")
fi

if [[ -n "$CAPTURE_FLAG" ]]; then
  common_args+=("$CAPTURE_FLAG")
fi

echo "[1/3] Running stop-and-wait required battery"
uv run rtp-scenarios \
  --mode saw \
  --window 1 \
  --results-dir "$RESULTS_ROOT/saw" \
  "${common_args[@]}"

echo "[2/3] Running Go-Back-N required battery"
uv run rtp-scenarios \
  --mode gbn \
  --window 4 16 \
  --results-dir "$RESULTS_ROOT/gbn" \
  "${common_args[@]}"

echo "[3/3] Running Selective Repeat required battery"
uv run rtp-scenarios \
  --mode sr \
  --window 4 16 \
  --results-dir "$RESULTS_ROOT/sr" \
  "${common_args[@]}"

echo "All required batteries finished under: $RESULTS_ROOT"