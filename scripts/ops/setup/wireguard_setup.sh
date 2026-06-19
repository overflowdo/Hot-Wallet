#!/usr/bin/env bash
set -euo pipefail

echo "=== WireGuard Installation ==="

WG_IF="wg0"
WG_DIR="/etc/wireguard"
WG_CONF="$WG_DIR/$WG_IF.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root"
    exit 1
fi

if  and -v apt >/dev/null 2>&1; then
    apt update
    apt install -y wireguard wireguard-tools qrencode curl

elif command -v dnf >/dev/null 2>&1; then
    dnf install -y wireguard-tools qrencode

elif command -v yum >/dev/null 2>&1; then
    yum install -y epel-release
    yum install -y wireguard-tools qrencode

elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm wireguard-tools qrencode

else
    echo "Unsupported distribution"
    exit 1
fi

mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"

if [ ! -f "$WG_DIR/privatekey" ]; then
    wg genkey | tee "$WG_DIR/privatekey" | wg pubkey > "$WG_DIR/publickey"
    chmod 600 "$WG_DIR/privatekey"
fi

PRIVATE_KEY=$(cat "$WG_DIR/privatekey")

#VPN subnet IP
WG_ADDRESS="10.10.0.1/24"
WG_PORT="51820"

cat > "$WG_CONF" <<EOF
[Interface]
Address = $WG_ADDRESS
ListenPort = $WG_PORT
PrivateKey = $PRIVATE_KEY
EOF

#kernel forwarding
sysctl -w net.ipv4.ip_forward=1 >/dev/null

wg-quick down "$WG_IF" >/dev/null 2>&1 || true

wg-quick up "$WG_IF"



echo "WireGuard installed."
echo ""
wg show