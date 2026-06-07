#!/usr/bin/env bash

NATS_CONTAINER="nats-box"
NATS_SERVER="nats://nats:4222"

PAYLOAD=$(printf '{"id":"%s","type":"refill","network":"%s","amount_sats":%s,"target_address":"%s","meta":{}}' \
  "t1-refill" \
  "1000" \
  "cold")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(printf '{"id":"%s","type":"hot-tx","network":"%s","amount_sats":%s,"target_address":"%s","meta":{}}' \
  "t1-network-deny" \
  "mainnet" \
  "1000" \
  "bcrt1qanotherexampledestinationaddress00000000000")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(printf '{"id":"%s","type":"hot-tx","network":"%s","amount_sats":%s,"target_address":"%s","meta":{}}' \
  "t1-amount deny" \
  "mainnet" \
  "5000001" \
  "bcrt1qanotherexampledestinationaddress00000000000")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(printf '{"id":"%s","type":"hot-tx","network":"%s","amount_sats":%s,"target_address":"%s","meta":{}}' \
  "t1-target deny" \
  "mainnet" \
  "1000" \
  "bcrt1qanotherexampledestinationaddress00000000001")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"


PAYLOAD=$(printf '{"id":"%s","type":"hot-tx","network":"%s","amount_sats":%s,"target_address":"%s","meta":{}}' \
  "t1-hot-tx allow" \
  "mainnet" \
  "1000" \
  "bcrt1qanotherexampledestinationaddress00000000000")

docker exec "$NATS_CONTAINER" \
  nats --server "$NATS_SERVER" pub intent.created "$PAYLOAD"