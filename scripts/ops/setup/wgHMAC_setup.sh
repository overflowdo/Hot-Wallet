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
WALLET_DIR="${PROJECT_ROOT}/middleware_data/wallets"
ENV_RUNTIME="${PROJECT_ROOT}/middleware_data/secrets/env.runtime"

SIGNER_IP="10.10.0.2"
SIGNER_URL="http://${SIGNER_IP}:8080"

MIDDLEWARE_URL="http://localhost:8080"

patch_metadata() {
  local meta_file="$1"
  local wallet_type="$2"
  local wallet_dir="$3"

  local xpub_file="$wallet_dir/xpub.txt"

  if [[ ! -f "$xpub_file" ]]; then
    echo "ERROR: missing xpub.txt in $wallet_dir" >&2
    return 1
  fi

  local xpub
  xpub=$(cat "$xpub_file")


  local tmp
  tmp=$(mktemp)

  jq \
    --arg wallet_type "$wallet_type" \
    --arg xpub "$xpub" \
    '
    .wallet_type = ($wallet_type)
    | .xpub = (if $xpub == "" then null else $xpub end)
    ' "$meta_file" > "$tmp"

  mv "$tmp" "$meta_file"
}


echo "Writing to host docker mount: $PROJECT_ROOT/middleware_data"

echo "=== Import Hot/Cold Signer ==="

mkdir -p "$USB_MOUNT" "$SECRETS_DIR" "$WALLET_DIR"

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
echo "Importing wallets..."

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

    if [[ "$WALLET_TYPE" == "hot" ]]; then

        if [[ ! -f "$WALLET_META" ]]; then
            echo "Skipping hot"
            continue
        fi

        FOUND=1

        patch_metadata "$WALLET_META" "$WALLET_TYPE" "$WALLET_TYPE_DIR"

    elif [[ "$WALLET_TYPE" == "cold" ]]; then

        COLD_SIGNER="$WALLET_TYPE_DIR/cold-signer.wsh"

        if [[ ! -f "$COLD_SIGNER" ]]; then
            echo "Skipping cold"
            continue
        fi

        FOUND=1
        WALLET_META=$(mktemp)

        jq -n \
          --arg wallet_type "cold" \
          --arg desc "$(tail -n 1 "$COLD_SIGNER")" \
          --arg network "regtest" \
          '
          {
            wallet_type: $wallet_type,
            xpub: "",
            descriptor: $desc,
            network: $network,
          }
          ' > "$WALLET_META"

    fi

    echo ""
    echo "----------------------------------"
    echo "Wallet type: $WALLET_TYPE"
    echo "----------------------------------"

    mkdir -p "$WALLET_DIR/$WALLET_TYPE"

    cp "$WALLET_TYPE_DIR/"* "$WALLET_DIR/$WALLET_TYPE/"
    find "$WALLET_DIR/$WALLET_TYPE" -type f -exec chmod 644 {} \;
    
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
    echo "WARNING: no wallets found"
fi

sync
umount "$USB_MOUNT"

echo ""
echo "Import complete"
echo "Signer URL: ${SIGNER_URL}"