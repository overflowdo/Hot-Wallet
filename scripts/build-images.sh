#!/usr/bin/env bash
set -euo pipefail

REG="${REG:-ghcr.io/your-org}"
TAG="${TAG:-0.1.0}"

docker build -t "$REG/middleware:$TAG" services/middleware
docker build -t "$REG/tx-builder:$TAG" services/tx-builder
docker build -t "$REG/policy-signer:$TAG" services/policy-signer

echo "Built images with TAG=$TAG"