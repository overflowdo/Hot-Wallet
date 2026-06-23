#!/usr/bin/env bash
set -euo pipefail

USB_DEVICE="/dev/disk/by-label/USB"
USB_MOUNT="/mnt/usb"

WG_IF="wg0"
WG_DIR="/etc/wireguard"
WG_CONF="$WG_DIR/$WG_IF.conf"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(realpath "${SCRIPT_DIR}/../../..")"

SECRETS_DIR="${PROJECT_ROOT}/middleware_data/secrets"
ENV_RUNTIME="${PROJECT_ROOT}/middleware_data/secrets/env.runtime"

SIGNER_IP="10.10.0.2"
SIGNER_URL="http://${SIGNER_IP}:8080"



echo "Writing to host docker mount: $PROJECT_ROOT/middleware_data"

mkdir -p "$USB_MOUNT" "$SECRETS_DIR"

if mountpoint -q "$USB_MOUNT"; then
  echo "USB already mounted at $USB_MOUNT, skipping mount"
else
  echo "Mounting USB..."
  mount "$USB_DEVICE" "$USB_MOUNT"
fi

echo ""
echo "Checking communication files ..."

# communication (OPTIONAL)
#WG
WG_JSON="$USB_MOUNT/communication/wireguard/wireguard.signer.json"

if [[ -f "$WG_JSON" ]]; then
    echo "Applying WireGuard peer from JSON..."

    SIGNER_PUB_KEY=$(jq -r '.signer_public_key' "$WG_JSON")
    SIGNER_IP=$(jq -r '.signer_ip' "$WG_JSON")
    SIGNER_ENDPOINT=$(jq -r '.endpoint' "$WG_JSON")

    WG_IF="wg0"

    # validate input
    if [[ -z "$SIGNER_PUB_KEY" || "$SIGNER_PUB_KEY" == "null" ]]; then
        echo "ERROR: invalid signer_public_key"
        exit 1
    fi
    if [[ -z "$SIGNER_IP" || "$SIGNER_IP" == "null" ]]; then
        echo "ERROR: invalid signer_ip"
        exit 1
    fi
    if [[ -z "$SIGNER_ENDPOINT" || "$SIGNER_ENDPOINT" == "null" ]]; then
        echo "ERROR: invalid signer_endpoint"
        exit 1
    fi
    ALLOWED_IP="${SIGNER_IP%/*}/32"

    if [[ -f "$WG_CONF" ]]; then
        echo "Writing new peer to $WG_CONF..."

        #VPN subnet IP
        WG_ADDRESS="10.10.0.1/32"
        WG_PORT="51820"

        PRIVATE_KEY=$(cat "$WG_DIR/private.key")

        #Überschreiben der Datei
        cat <<EOF > "$WG_CONF"
[Interface]
Address = $WG_ADDRESS
ListenPort = $WG_PORT
PrivateKey = $PRIVATE_KEY
SaveConfig = false

[Peer]
PublicKey = $SIGNER_PUB_KEY
AllowedIPs = $ALLOWED_IP
PersistentKeepalive = 25
Endpoint = $SIGNER_ENDPOINT
EOF
    else
        echo "WARNING: Configuration file $WG_CONF not found. Could not persist peer."
    fi

    #interface exists
    if ! ip link show "$WG_IF" >/dev/null 2>&1; then
        echo "WireGuard interface $WG_IF missing..."

        ip link add dev "$WG_IF" type wireguard
        ip link set "$WG_IF" up
    fi

    #restart

    wg-quick down "$WG_IF" >/dev/null 2>&1 || true

    wg-quick up "$WG_IF"
    
    echo "WireGuard peer applied successfully"

else
    echo "Skipping: wireguard.signer.json not found"
fi


#########################################
#HMAC
if [[ -f "$USB_MOUNT/communication/signer-hmac.secret" ]]; then
    cp "$USB_MOUNT/communication/signer-hmac.secret" \
       "$SECRETS_DIR/signer-hmac.secret"
    chmod 600 "$SECRETS_DIR/signer-hmac.secret"
    echo "Imported: signer-hmac.secret"
else
    echo "Skipping: signer-hmac.secret "
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
    echo "Skipping env.runtime"
fi

echo ""


sync
umount "$USB_MOUNT"

echo ""
echo "Import complete"
echo "Signer URL: ${SIGNER_URL}"