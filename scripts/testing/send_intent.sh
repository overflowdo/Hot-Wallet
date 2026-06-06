#!/usr/bin/env bash

NATS_CONTAINER="nats-box"
NATS_SERVER="nats://nats:4222"

INTENT_ID="${1:-t1}"
AMOUNT_SATS="${2:-10000}"

PAYLOAD=$(printf '{"intent_id":"%s","amount_sats":%s}' \
  "$INTENT_ID" \
  "$AMOUNT_SATS")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"