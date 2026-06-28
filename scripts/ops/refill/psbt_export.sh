#!/usr/bin/env bash
set -euo pipefail

MNT="/mnt/usb"
LABEL="USB"

API_BASE="${API_BASE:-http://localhost:8080}"

die(){ echo "ERROR: $*" >&2; exit 1; }
info(){ echo "[*] $*"; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."

DEV="$(readlink -f /dev/disk/by-label/${LABEL} 2>/dev/null || true)"
[[ -n "$DEV" ]] || die "Kein Device mit Label '${LABEL}' gefunden."

mkdir -p "$MNT"
mountpoint -q "$MNT" || mount "$DEV" "$MNT"

mkdir -p "$MNT/psbt"

shopt -s nullglob
existing=( "$MNT/psbt"/unappr.*.psbt )
shopt -u nullglob
[[ ${#existing[@]} -eq 0 ]] || die "USB enthält bereits unappr.*.psbt (Single-TX Regel verletzt): ${existing[*]}"

URL="${API_BASE}/api/v1/request/psbt"
info "Fetch PSBT: $URL"

resp="$(curl -fsSL "$URL")" || die "PSBT fetch failed."
[[ -n "$resp" ]] || die "Empty response."

# -----------------------------
# JSON parsen
# -----------------------------
psbt_id="$(echo "$resp" | jq -r '.psbt_id')"
psbt="$(echo "$resp" | jq -r '.psbt')"

[[ -n "$psbt_id" && "$psbt_id" != "null" ]] || die "Missing psbt_id"
[[ -n "$psbt" && "$psbt" != "null" ]] || die "Missing psbt"

TMP="$(mktemp)"
trap 'rm -f "$TMP" 2>/dev/null || true' EXIT

echo "$psbt" > "$TMP"

OUT="$MNT/psbt/unappr.${psbt_id}.psbt"

cp -f "$TMP" "$OUT"

info "Wrote: $OUT"

sync
umount "$MNT"

info "USB unmounted"
info "psbt_id=$psbt_id"