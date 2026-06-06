#!/usr/bin/env bash
set -euo pipefail

USB_DEVICE="/dev/disk/by-label/USB"
USB_MOUNT="/mnt/usb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(realpath "${SCRIPT_DIR}/../..")"

SECRETS_DIR="${PROJECT_ROOT}/secrets"
WALLET_DIR="${PROJECT_ROOT}/wallet"

ENV_RUNTIME="${PROJECT_ROOT}/env.runtime"

SIGNER_IP="10.10.0.2"
SIGNER_URL="http://${SIGNER_IP}:8080"

echo "=== Import Hot Signer ==="

mkdir -p "$USB_MOUNT"
mkdir -p "$SECRETS_DIR"
mkdir -p "$WALLET_DIR"

mount "$USB_DEVICE" "$USB_MOUNT"


# sanity checks
test -f "$USB_MOUNT/communication/wireguard-public.key"
test -f "$USB_MOUNT/communication/signer-hmac.secret"

test -f "$USB_MOUNT/wallet/hot-wallet.xpub"
test -f "$USB_MOUNT/wallet/wallet.json"



# communication
cp \
  "$USB_MOUNT/communication/wireguard-public.key" \
  "$SECRETS_DIR/wireguard-public.key"

cp \
  "$USB_MOUNT/communication/signer-hmac.secret" \
  "$SECRETS_DIR/signer-hmac.secret"



# wallet
cp \
  "$USB_MOUNT/wallet/hot-wallet.xpub" \
  "$WALLET_DIR/hot-wallet.xpub"

cp \
  "$USB_MOUNT/wallet/wallet.json" \
  "$WALLET_DIR/wallet.json"

chmod 644 "$SECRETS_DIR/wireguard-public.key"
chmod 600 "$SECRETS_DIR/signer-hmac.secret"



# env.runtime
HMAC_SECRET=$(cat "$SECRETS_DIR/signer-hmac.secret")

cat > "$ENV_RUNTIME" <<EOF
SIGNER_URL=${SIGNER_URL}
SIGNER_HMAC_SECRET=${HMAC_SECRET}
EOF

chmod 600 "$ENV_RUNTIME"

sync

umount "$USB_MOUNT"

echo ""
echo "Imported:"
echo "  secrets/wireguard-public.key"
echo "  secrets/signer-hmac.secret"
echo "  wallet/hot-wallet.xpub"
echo "  wallet/wallet.json"
echo ""
echo "Generated:"
echo "  env.runtime"
echo ""
echo "Signer URL:"
echo "  ${SIGNER_URL}"