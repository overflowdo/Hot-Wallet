#!/usr/bin/env bash
set -euo pipefail

REG="${REG:-ghcr.io/your-org}"
TAG="${TAG:-0.1.0}"

docker push "$REG/middleware:$TAG"
docker push "$REG/tx-builder:$TAG"
docker push "$REG/policy-signer:$TAG"

echo "Pushed images with TAG=$TAG"