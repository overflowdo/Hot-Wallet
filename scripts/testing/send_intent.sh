#!/usr/bin/env bash

NATS_CONTAINER="nats-box"
NATS_SERVER="nats://nats:4222"

PAYLOAD=$(jq -n \
  --arg id "t1-refill" \
  --arg source "cold" \
  --arg network "regtest" \
  --arg address "hot" \
  --argjson amount 1000 \
  '{
      id: $id,
      type: "refill",
      network: $network,
      amount_sats: $amount,
      target_address: $address,
      source_address: $source,
      meta: {}
   }')

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(jq -n \
  --arg id "t1-network-deny" \
  --arg network "tester" \
  --arg address "bcrt1qanotherexampledestinationaddress00000000000" \
  --arg source "hot" \
  --argjson amount 1000 \
  '{
      id: $id,
      type: "hot-tx",
      network: $network,
      amount_sats: $amount,
      target_address: $address,
      source_address: $source,
      meta: {}
   }')

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(jq -n \
  --arg id "t1-amount deny" \
  --arg network "regtest" \
  --arg address "bcrt1qanotherexampledestinationaddress00000000000" \
  --argjson amount 5000001 \
  --arg source "hot" \
  '{
      id: $id,
      type: "hot-tx",
      network: $network,
      amount_sats: $amount,
      target_address: $address,
      source_address: $source,
      meta: {}
   }')

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(jq -n \
  --arg id "t1-target deny" \
  --arg network "regtest" \
  --arg address "bcrt1qanotherexampledestinationaddress00000000001" \
  --argjson amount 1000 \
  --arg source "hot" \
  '{
      id: $id,
      type: "hot-tx",
      network: $network,
      amount_sats: $amount,
      target_address: $address,
      source_address: $source,
      meta: {}
   }')

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(jq -n \
  --arg id "t1-hot-tx allow" \
  --arg network "regtest" \
  --arg address "bcrt1qanotherexampledestinationaddress00000000000" \
  --argjson amount 1000 \
  --arg source "hot" \
  '{
      id: $id,
      type: "hot-tx",
      network: $network,
      amount_sats: $amount,
      target_address: $address,
      source_address: $source,
      meta: {}
   }')

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"