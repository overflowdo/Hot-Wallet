#!/usr/bin/env bash
set -euo pipefail

echo "=== WireGuard Installation ==="

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root"
    exit 1
fi

if command -v apt >/dev/null 2>&1; then
    apt update
    apt install -y wireguard wireguard-tools qrencode

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

mkdir -p /etc/wireguard
chmod 700 /etc/wireguard

echo ""
echo "WireGuard installed."
echo ""
echo "Next step:"
echo "  copy signer/wireguard-public.key"
echo "  create /etc/wireguard/wg0.conf"
echo "  systemctl enable wg-quick@wg0"