
bash /home/user/Desktop/Hot-Wallet/scripts/ops/setup/wallet_import.sh
python3 /home/user/Desktop/Hot-Wallet/scripts/ops/setup/whiteWallet.py
    
bash ./btc-core/load_wallet.sh
sleep 5
bash ./btc-core/simMoney.sh
    
sleep 5
    
python3 send_intent_API.py

