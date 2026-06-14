#!/usr/bin/env bash
set -euo pipefail

USB_DEVICE="/dev/disk/by-label/USB"
USB_MOUNT="/mnt/usb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(realpath "${SCRIPT_DIR}/../../..")"

SECRETS_DIR="${PROJECT_ROOT}/middleware_data/secrets"
WALLET_DIR="${PROJECT_ROOT}/middleware_data/wallets"
ENV_RUNTIME="${PROJECT_ROOT}/middleware_data/secrets/env.runtime"

SIGNER_IP="10.10.0.2"
SIGNER_URL="http://${SIGNER_IP}:8080"

MIDDLEWARE_URL="http://localhost:3000"

echo "Writing to host docker mount: $PROJECT_ROOT/middleware_data"

echo "=== Import Hot/Cold Signer ==="

mkdir -p "$USB_MOUNT" "$SECRETS_DIR" "$WALLET_DIR"

mount "$USB_DEVICE" "$USB_MOUNT"

echo ""
echo "Checking communication files (optional)..."

# communication (OPTIONAL)
if [[ -f "$USB_MOUNT/communication/wireguard-public.key" ]]; then
    cp "$USB_MOUNT/communication/wireguard-public.key" \
       "$SECRETS_DIR/wireguard-public.key"
    chmod 644 "$SECRETS_DIR/wireguard-public.key"
    echo "Imported: wireguard-public.key"
else
    echo "Skipping: wireguard-public.key (not found)"
fi

if [[ -f "$USB_MOUNT/communication/signer-hmac.secret" ]]; then
    cp "$USB_MOUNT/communication/signer-hmac.secret" \
       "$SECRETS_DIR/signer-hmac.secret"
    chmod 600 "$SECRETS_DIR/signer-hmac.secret"
    echo "Imported: signer-hmac.secret"
else
    echo "Skipping: signer-hmac.secret (not found)"
fi

# env.runtime nur erzeugen wenn HMAC existiert
if [[ -f "$SECRETS_DIR/signer-hmac.secret" ]]; then
    HMAC_SECRET=$(cat "$SECRETS_DIR/signer-hmac.secret")

    cat > "$ENV_RUNTIME" <<EOF
SIGNER_URL=${SIGNER_URL}
SIGNER_HMAC_SECRET=${HMAC_SECRET}
EOF

    chmod 600 "$ENV_RUNTIME"
    echo "Generated: env.runtime"
else
    echo "Skipping env.runtime (no HMAC secret)"
fi

echo ""
echo "Importing wallets (hot/cold optional)..."

FOUND=0

for WALLET_TYPE_DIR in "$USB_MOUNT/wallet"/*/
do
    [[ -d "$WALLET_TYPE_DIR" ]] || continue

    WALLET_TYPE=$(basename "$WALLET_TYPE_DIR")

    # nur hot/cold erlauben (optional harte Validierung)
    if [[ "$WALLET_TYPE" != "hot" && "$WALLET_TYPE" != "cold" ]]; then
        echo "Skipping unknown wallet type: $WALLET_TYPE"
        continue
    fi

    WALLET_META="$WALLET_TYPE_DIR/metadata.json"

    if [[ ! -f "$WALLET_META" ]]; then
        echo "Skipping $WALLET_TYPE (no metadata.json)"
        continue
    fi

    FOUND=1

    echo ""
    echo "----------------------------------"
    echo "Wallet type: $WALLET_TYPE"
    echo "----------------------------------"

    mkdir -p "$WALLET_DIR/$WALLET_TYPE"

    cp "$WALLET_TYPE_DIR/"* "$WALLET_DIR/$WALLET_TYPE/"
    chmod 644 "$WALLET_DIR/$WALLET_TYPE"/*
    
    if curl \
      --fail \
      --show-error \
      --silent \
      -X POST \
      "${MIDDLEWARE_URL}/api/v1/importWallet" \
      -H "Content-Type: application/json" \
      --data @"$WALLET_META"
    then
      echo "OK: $WALLET_TYPE registered"
    else
      echo "middleware not reachable, container running?"
    fi
done

if [[ "$FOUND" -eq 0 ]]; then
    echo "WARNING: no wallets found (hot/cold missing)"
fi

sync
umount "$USB_MOUNT"

echo ""
echo "Import complete"
echo "Signer URL: ${SIGNER_URL}"