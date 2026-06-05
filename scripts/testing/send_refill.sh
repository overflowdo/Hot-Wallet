#!/usr/bin/env bash

set -e

INTENT_ID=${1:-test-$(date +%s)}
AMOUNT=${2:-10000}

echo "Sending refill intent..."
echo "intent_id=$INTENT_ID"
echo "amount_sats=$AMOUNT"

docker exec nats nats pub intent.refill.created \
"{\"intent_id\":\"$INTENT_ID\",\"amount_sats\":$AMOUNT}"

echo "Done."