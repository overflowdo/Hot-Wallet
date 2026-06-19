set -euo pipefail

USB_DEVICE="/dev/disk/by-label/USB"
USB_MOUNT="/mnt/usb"

mkdir -p "$USB_MOUNT"
if mountpoint -q "$USB_MOUNT"; then
  echo "USB already mounted at $USB_MOUNT, skipping mount"
else
  echo "Mounting USB..."
  mount "$USB_DEVICE" "$USB_MOUNT"
fi

#Wenn noch nicht erstellt
PRIVATE_KEY=/etc/wireguard/private.key
PUBLIC_KEY=/etc/wireguard/public.key

if [[ ! -f "$PRIVATE_KEY" ]]; then
    echo "Generating local WireGuard keypair..."

    umask 077
    wg genkey | tee "$PRIVATE_KEY" | wg pubkey > "$PUBLIC_KEY"

    chmod 600 "$PRIVATE_KEY"
    chmod 644 "$PUBLIC_KEY"
fi

mkdir -p "$USB_MOUNT/communication/wireguard"



WG_PORT="51820"


SIGNER_ENDPOINT_IP=$(ip route get 1.1.1.1 | awk '{print $7; exit}')


SIGNER_IP="10.10.0.2/24"
WALLET_IP="10.10.0.1/24"

SIGNER_PUB_KEY="$(cat "$PUBLIC_KEY")"

WIREGUARD_JSON="$USB_MOUNT/communication/wireguard/wireguard.wallet.json"

cat > "$WIREGUARD_JSON" <<EOF
{
  "Wallet_public_key": "$SIGNER_PUB_KEY",
  "signer_ip": "$SIGNER_IP",
  "wallet_ip": "$WALLET_IP",
  "port": $WG_PORT,
  "endpoint": "${SIGNER_ENDPOINT_IP}:${WG_PORT}",
  "allowed_ips_signer": "$WALLET_IP/32",
  "allowed_ips_wallet": "$SIGNER_IP/32"
}
EOF

chmod 644 "$WIREGUARD_JSON"

echo "WireGuard contract exported:"
echo "  $WIREGUARD_JSON"

sync
umount "$USB_MOUNT"

echo "done"