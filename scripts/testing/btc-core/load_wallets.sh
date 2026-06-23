#!/bin/bash
# Einmaliges Aufsetzen dieser Nodes.
#Danach importieren der descitpoiren aus dem filesystem /wallets/, um über mehrere versuche dieselben Adressen zu haben.
#Wichtig für OPA whitelisting
set -e

RPC="/root/bitcoin-cli -regtest -rpcuser=user -rpcpassword=pass"
 
until $RPC getblockchaininfo >/dev/null 2>&1; do
    echo "Waiting for Bitcoin RPC..."
    sleep 1
done
 
restore_wallet() {
  local WALLET=$1
  local FILE="/root/.bitcoin/wallets/$WALLET.descriptors.json"
 
  echo "Restoring $WALLET..."
 
  # descriptor Wallet neu erstellen
  $RPC createwallet "$WALLET" false false "" false true >/dev/null 2>&1 || true
 
  # Descriptors extrahieren und importieren
  DESCS=$(cat "$FILE" | jq -c '.descriptors')
 
  $RPC -rpcwallet="$WALLET" importdescriptors "$DESCS"
 
  echo "Loaded $WALLET"
}
 
restore_wallet "wallet1"
restore_wallet "wallet2"
restore_wallet "wallet3"
 
echo
echo "Loaded wallets:"
$RPC listwallets
 
echo "Mining initial blocks..."
ADDR_FUND=$($RPC -rpcwallet=wallet1 getnewaddress)
$RPC generatetoaddress 101 "$ADDR_FUND" >/dev/null
 
 
echo "Creating addresses..."
ADDR1=$($RPC -rpcwallet=wallet1 getnewaddress)
ADDR2=$($RPC -rpcwallet=wallet2 getnewaddress)
ADDR3=$($RPC -rpcwallet=wallet3 getnewaddress)
 
echo "Funding wallets..."
TX1=$($RPC -rpcwallet=wallet1 sendtoaddress "$ADDR2" 25)
TX2=$($RPC -rpcwallet=wallet1 sendtoaddress "$ADDR3" 1)
 
echo "Confirming..."
$RPC generatetoaddress 1 "$ADDR_FUND" >/dev/null
 
TX1=$($RPC -rpcwallet=wallet1 sendtoaddress "$ADDR3" 25)
TX2=$($RPC -rpcwallet=wallet1 sendtoaddress "$ADDR2" 1)
 
$RPC generatetoaddress 1 "$ADDR_FUND" >/dev/null
 
$RPC -rpcwallet=wallet1 getbalances
$RPC -rpcwallet=wallet2 getbalances
$RPC -rpcwallet=wallet3 getbalances