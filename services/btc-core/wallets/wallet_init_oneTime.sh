#!/bin/bash
#Einmaliges Ausführen zum Extrahieren der bitcoin wallet deskriptoren
#Ausführen außerhalb der Docker container (CP aus dem Container nicht möglich)
#Github kommt mit Standard generierten Deskiptoren

RPC="docker exec bitcoind-regtest /root/bitcoin-cli -regtest -rpcuser=user -rpcpassword=pass"

 
$RPC createwallet wallet1 false false "" false true
$RPC createwallet wallet2 false false "" false true
$RPC createwallet wallet3 false false "" false true
 
for W in wallet1 wallet2 wallet3; do
  echo "Exporting $W..."
 
  $RPC -rpcwallet="$W" listdescriptors true > "./$W.descriptors.json"
 
done


 
echo "DONE"