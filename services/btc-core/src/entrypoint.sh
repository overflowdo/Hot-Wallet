#!/bin/bash
set -e
 
echo "[regtest] starting bitcoind..."

CONF_FILE="/root/.bitcoin/bitcoin.conf"
LOG_FILE="/root/.bitcoin/regtest/debug.log"
WALLET_FILE="/root/.bitcoin/scripts/load_wallets.sh"
 

/root/bitcoind -regtest -conf="$CONF_FILE" -daemon
 

RPC="/root/bitcoin-cli -regtest -rpcuser=user -rpcpassword=pass"
 
echo "[regtest] waiting for node..."
sleep 2

while true; do
  if ! ps aux | grep '[b]itcoind' > /dev/null; then
    echo "CRITICAL ERROR: bitcoind process died! Check config or network IPs."
    exit 1
  fi
 
  # RPC-Abfrage testen
  $RPC getblockchaininfo >/dev/null 2>&1
  if [ $? -eq 0 ]; then
    break
  fi
  sleep 1
done
 
echo "[regtest] node ready"
 
$RPC loadwallet default >/dev/null 2>&1 || \
$RPC createwallet default >/dev/null 2>&1
# Wallet readiness prüfen
until $RPC getwalletinfo >/dev/null 2>&1; do
  sleep 1
done

#Zuvor erstellten Wallets imporieren
if [ -f "$WALLET_FILE" ]; then
  bash "$WALLET_FILE"
fi
#Wenn erster containerstart wird diese Ausfuehrung unterbrochen.
#Dann kann wallet_init_oneTime.sh ausgeführt werden zum erstellen der wallet deskriptoren
#Diese werden konsistiert und bei neustart gemountet
#Sind dementsprechend bei erneuten Start verfügbar
#Sicherstellen selbe xpub und xprv bei jedem start
 
echo "[regtest] wallet subsystem ready"
sleep 5
 
echo "[regtest] tailing logs..."

tail -f "$LOG_FILE"