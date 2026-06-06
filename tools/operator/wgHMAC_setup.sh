#!/usr/bin/env bash
set -euo pipefail

USB_DEVICE="/dev/sdX1"
USB_MOUNT="/mnt/bootstrap"

SECRETS_DIR="./secrets"

WG_ENDPOINT="10.50.0.1"
SIGNER_URL="http://${WG_ENDPOINT}:8080"

mkdir -p "$USB_MOUNT"
mkdir -p "$SECRETS_DIR"

echo "[1] Mount bootstrap USB"

mount "$USB_DEVICE" "$USB_MOUNT"

echo "[2] Verify required files"

test -f "$USB_MOUNT/signer_api_secret.txt"
test -f "$USB_MOUNT/signer_wg_public.key"

echo "[3] Read HMAC secret"

SIGNER_HMAC_SECRET="$(cat "$USB_MOUNT/signer_api_secret.txt")"

if [ -z "$SIGNER_HMAC_SECRET" ]; then
    echo "ERROR: Empty signer_api_secret.txt"
    exit 1
fi

echo "[4] Create Docker secret"

printf "%s" "$SIGNER_HMAC_SECRET" \
    > "$SECRETS_DIR/signer_hmac.txt"

chmod 600 "$SECRETS_DIR/signer_hmac.txt"

echo "[5] Create runtime env"

cat > .env.runtime <<EOF
SIGNER_URL=${SIGNER_URL}
SIGNER_HMAC_SECRET=${SIGNER_HMAC_SECRET}
WG_ENDPOINT=${WG_ENDPOINT}
EOF

chmod 600 .env.runtime

echo "[6] Store signer WG public key"

cp \
  "$USB_MOUNT/signer_wg_public.key" \
  "$SECRETS_DIR/signer_wg_public.key"

chmod 644 "$SECRETS_DIR/signer_wg_public.key"

echo "[7] Unmount USB"

sync
umount "$USB_MOUNT"

echo "[8] Connectivity check"

curl \
  --connect-timeout 3 \
  "${SIGNER_URL}/health" \
  || echo "WARNING: Signer not reachable yet"

echo
echo "[OK] Bootstrap imported"
echo
echo "Generated:"
echo "  .env.runtime"
echo "  secrets/signer_hmac.txt"
echo "  secrets/signer_wg_public.key"