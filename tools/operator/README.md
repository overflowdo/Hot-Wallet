# Operator Tools

## usb-export-psbt.sh

**Run on Hot VM (operator machine)** after Proxmox attached the USB.

### Requirements
- root
- `jq` installed
- USB label `USB`

### Usage
```bash
sudo API_BASE="http://middleware.btc-hot.svc.cluster.local:8080" \
     API_TOKEN="" \
     ./usb-export-psbt.sh <intent-id>