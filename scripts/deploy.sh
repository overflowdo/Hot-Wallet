#!/usr/bin/env bash#!/usr/bin/env bash--
# Deploy script for:
# - Namespaces: btc-hot, btc-net
# - Core: nats, opa
# - PVCs: work-pvc, archive-pvc
# - btc-net: bitcoind-regtest, miner
# - Services: middleware, tx-builder, policy-signer
# - NetPols
# - Optional: VolSync manifests (if present)
#
# Usage:
#   bash k8s/scripts/deploy.sh
#
# Optional env:
#   APPLY_VOLSYNC=1   -> apply deploy/k8s/volsync/*.yaml (if present)
#   APPLY_NTFY=1      -> apply deploy/k8s/base/ntfy.yaml (if you use ExternalName placeholder)
# ------------------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

BASE_DIR="$ROOT_DIR/deploy/k8s/base"
NET_DIR="$ROOT_DIR/deploy/k8s/bitcoin-net"
VOLSYNC_DIR="$ROOT_DIR/deploy/k8s/volsync"

APPLY_VOLSYNC="${APPLY_VOLSYNC:-0}"
APPLY_NTFY="${APPLY_NTFY:-0}"

die(){ echo "ERROR: $*" >&2; exit 1; }
info(){ echo "[*] $*"; }

need_kubectl(){
  command -v kubectl >/dev/null 2>&1 || die "kubectl not found"
  kubectl version --client >/dev/null 2>&1 || die "kubectl client not working"
}

apply_if_exists(){
  local f="$1"
  if [[ -f "$f" ]]; then
    info "apply: $f"
    kubectl apply -f "$f"
  else
    info "skip (missing): $f"
  fi
}

require_file(){
  local f="$1"
  [[ -f "$f" ]] || die "required file missing: $f"
}

check_secret_exists(){
  local ns="$1"
  local name="$2"
  if kubectl -n "$ns" get secret "$name" >/dev/null 2>&1; then
    info "secret exists: $ns/$name"
  else
    info "WARNING: secret missing: $ns/$name (create it before services can work)"
  fi
}

main(){
  need_kubectl

  require_file "$BASE_DIR/namespace.yaml"
  require_file "$BASE_DIR/nats.yaml"
  require_file "$BASE_DIR/opa.yaml"
  require_file "$NET_DIR/bitcoind-regtest.yaml"
  require_file "$NET_DIR/miner.yaml"
  require_file "$BASE_DIR/middleware.yaml"
  require_file "$BASE_DIR/tx-builder.yaml"
  require_file "$BASE_DIR/policy-signer.yaml"
  require_file "$BASE_DIR/networkpolicies.yaml"

  info "=== 1) Namespaces ==="
  kubectl apply -f "$BASE_DIR/namespace.yaml"

  info "=== 2) Core services (btc-hot): NATS + OPA ==="
  kubectl apply -f "$BASE_DIR/nats.yaml"
  kubectl apply -f "$BASE_DIR/opa.yaml"

  info "=== 3) ConfigMap + Secrets (templates are not applied automatically) ==="
  apply_if_exists "$BASE_DIR/configmap.yaml"

  # secrets-template.yaml is a template -> do not apply by default
  if [[ -f "$BASE_DIR/secrets-template.yaml" ]]; then
    info "NOTE: secrets-template.yaml is present (template). Apply a real secret separately."
  fi

  # Check required secrets that should exist
  check_secret_exists "btc-hot" "btc-hot-secrets"
  # policy signer secret may exist or not (depending on stage)
  check_secret_exists "btc-hot" "policy-signer-secrets"

  info "=== 4) PVCs (btc-hot): work + archive ==="
  apply_if_exists "$BASE_DIR/work-pvc.yaml"
  apply_if_exists "$BASE_DIR/archive-pvc.yaml"
  apply_if_exists "$BASE_DIR/work-cleanup-cronjob.yaml"

  info "=== 5) Bitcoin network (btc-net): regtest node-only + miner ==="
  kubectl apply -f "$NET_DIR/bitcoind-regtest.yaml"
  kubectl apply -f "$NET_DIR/miner.yaml"

  info "=== 6) Hot services (btc-hot): middleware + tx-builder + policy-signer ==="
  kubectl apply -f "$BASE_DIR/middleware.yaml"
  kubectl apply -f "$BASE_DIR/tx-builder.yaml"
  kubectl apply -f "$BASE_DIR/policy-signer.yaml"

  if [[ "$APPLY_NTFY" == "1" ]]; then
    info "=== 6b) Optional: ntfy ExternalName placeholder ==="
    apply_if_exists "$BASE_DIR/ntfy.yaml"
  fi

  info "=== 7) NetworkPolicies ==="
  kubectl apply -f "$BASE_DIR/networkpolicies.yaml"

  if [[ "$APPLY_VOLSYNC" == "1" ]]; then
    info "=== 8) Optional: VolSync resources (btc-hot namespace) ==="
    apply_if_exists "$VOLSYNC_DIR/00-volsync-restic-secret.yaml"
    apply_if_exists "$VOLSYNC_DIR/10-archive-replicationsource.yaml"
    # restore destination is optional/manual
    apply_if_exists "$VOLSYNC_DIR/90-archive-restore-destination.yaml"
  else
    info "skip VolSync apply (set APPLY_VOLSYNC=1 to enable)"
  fi

  info "=== Done ==="
  info "Next checks:"
  info "  kubectl -n btc-hot get pods,svc"
  info "  kubectl -n btc-net get pods,svc"
}

main "$@"
set -euo pipefail