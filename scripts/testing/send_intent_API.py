import requests
import json
from urllib.parse import quote

BASE = "http://localhost:8080/api/v1/request"

RPC_URL = "http://192.168.99.58:18443"
RPC_USER = "user"
RPC_PASS = "pass"


class BitcoindRPCError(RuntimeError):
    pass

def rpc_call(url, method, params=None, rpc_id="tx-builder"):
    payload = {
        "jsonrpc": "1.0",
        "id": rpc_id,
        "method": method,
        "params": params or []
    }

    response = requests.post(
        url,
        auth=(RPC_USER, RPC_PASS),
        json=payload,
        headers={"content-type": "text/plain;"}
    )

    response.raise_for_status()
    return response.json()

#TEST BIP21
def test_bip21(wallet_name_target):
    rpc_res = rpc_call(f"{RPC_URL}/wallet/{wallet_name_target}", "getnewaddress", ["BIP21-Test", "bech32"])
    new_address = rpc_res["result"]

    print(f"Generierte Adresse für wallet2: {new_address}")

    #Metadaten für den BIP-21
    amount = "0.12"
    label = quote("Luke Dashjr")  # URL-Encoding für Leerzeichen etc.
    message = quote("Donation to Luke & friends")

    #dynamische BIP-21 URI
    bip21_uri = (
        f"bitcoin:{new_address}?amount={amount}&label={label}&message={message}"
    )

    res = requests.post(f"{BASE}/bip21", json={"uri": bip21_uri})
    print("BIP21 Server Response:", res.json())



#TEST PSBT
def test_psbt(wallet_name_target: str, wallet_name_source: str):
    rpc_res_w2 = rpc_call(f"{RPC_URL}/wallet/{wallet_name_target}", "getnewaddress", ["BIP21-Empfang", "bech32"])
    target_address = rpc_res_w2["result"]
    print(f" Zieladresse (wallet2): {target_address}")

    outputs = [{target_address: 0.12}]
    
    funded_res = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name_source}",
        "walletcreatefundedpsbt",
        [
            [],              # inputs: auto coin selection
            outputs,         # outputs
            lockTime,        #für smart contracts
            {
                "add_inputs": True,
                #"fee_rate": "1.2",             fee rate nicht direkt angeben. BTC CORE überlassen + OPA kontrolle
                "conf_target": 6,               #confirmation in ungefähr einer stunde (fee für 6 blöcke finden)
                "includeWatching": True,
                "replaceable": True,            #Start mit low fee. bei zu langem warten erhöhen ermöglichen
                "estimate_mode": "conservative" #Sicherer
            },
            True            #bip32derivs 
        ]
    )
    
    final_psbt_base64 = funded_res["result"]["psbt"]
    print(f" PSBT via 'createfundedpsbt' generiert.")

    # 3. PSBT an Ihr Backend senden
    res = requests.post(
        f"{BASE}/psbt",
        json={
            "psbt": final_psbt_base64
        }
    )
    print(" Server Response für /psbt:", res.json())



#RUN
if __name__ == "__main__":
    test_bip21("wallet2")
    test_psbt("wallet2", "keyA")