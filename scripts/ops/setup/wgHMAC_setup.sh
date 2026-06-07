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

# communication
cp \
  "$USB_MOUNT/communication/wireguard-public.key" \
  "$SECRETS_DIR/wireguard-public.key"

cp \
  "$USB_MOUNT/communication/signer-hmac.secret" \
  "$SECRETS_DIR/signer-hmac.secret"

chmod 644 "$SECRETS_DIR/wireguard-public.key"
chmod 600 "$SECRETS_DIR/signer-hmac.secret"


# env.runtime
HMAC_SECRET=$(cat "$SECRETS_DIR/signer-hmac.secret")

cat > "$ENV_RUNTIME" <<EOF
SIGNER_URL=${SIGNER_URL}
SIGNER_HMAC_SECRET=${HMAC_SECRET}
EOF

chmod 600 "$ENV_RUNTIME"

# wallet
#hot/cold subfolder
echo ""
echo "Importing wallets..."

FOUND=0

for WALLET_TYPE_DIR in "$USB_MOUNT/wallet"/*/
do
    [ -d "$WALLET_TYPE_DIR" ] || continue

    WALLET_JSON="$WALLET_TYPE_DIR/wallet.json"

    if [ ! -f "$WALLET_JSON" ]; then
        echo "Skipping $(basename "$WALLET_TYPE_DIR") (no wallet.json)"
        continue
    fi

    FOUND=1

    WALLET_TYPE=$(basename "$WALLET_TYPE_DIR")

    echo ""
    echo "----------------------------------"
    echo "Wallet type: $WALLET_TYPE"
    echo "File: $WALLET_JSON"
    echo "----------------------------------"

    # local copy
    mkdir -p "$WALLET_DIR/$WALLET_TYPE"
    cp "$WALLET_TYPE_DIR/"* "$WALLET_DIR/$WALLET_TYPE/"

    chmod 644 "$WALLET_DIR/$WALLET_TYPE"/*

    # register in middleware
    curl \
      --fail \
      --show-error \
      --silent \
      -X POST \
      "${MIDDLEWARE_URL}/api/v1/wallets" \
      -H "Content-Type: application/json" \
      --data @"$WALLET_JSON"

    echo "OK: $WALLET_TYPE registered"
done

if [ "$FOUND" -eq 0 ]; then
    echo "WARNING: no wallets found"
fi


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