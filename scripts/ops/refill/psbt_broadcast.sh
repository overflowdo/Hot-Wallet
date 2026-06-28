#!/usr/bin/env bash
set -euo pipefail

MNT="/mnt/usb"
LABEL="USB"

API_BASE="${API_BASE:-http://middleware:8080}"

die(){ echo "ERROR: $*" >&2; exit 1; }
info(){ echo "[*] $*"; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."

DEV="$(readlink -f /dev/disk/by-label/${LABEL} 2>/dev/null || true)"
[[ -n "$DEV" ]] || die "Kein Device mit Label '${LABEL}' gefunden."

mkdir -p "$MNT"
mountpoint -q "$MNT" || mount "$DEV" "$MNT"

cd "$MNT/psbt" || die "psbt folder missing"

shopt -s nullglob
files=( appr.*.psbt )
shopt -u nullglob

[[ ${#files[@]} -gt 0 ]] || die "Keine appr.*.psbt gefunden"
[[ ${#files[@]} -eq 1 ]] || die "Mehr als eine appr.*.psbt gefunden (unsafe)"

FILE="${files[0]}"

info "Using file: $FILE"

# psbt_id aus Filename extrahieren
# appr.<psbt_id>.psbt
BASENAME="$(basename "$FILE")"
psbt_id="${BASENAME#appr.}"
psbt_id="${psbt_id%.psbt}"

info "psbt_id: $psbt_id"

PSBT="$(cat "$FILE")"
[[ -n "$PSBT" ]] || die "Empty PSBT"


API_URL="${API_BASE}/api/v1/request/broadcast/${psbt_id}"

info "Sending to API: $API_URL"

resp="$(curl -fsSL \
  -X POST \
  -H "Content-Type: text/plain" \
  --data "$PSBT" \
  "$API_URL")" || die "Broadcast API call failed"

echo "$resp"

info "Done"

sync
umount "$MNT"

info "USB unmounted"