import os
import requests
from typing import List, Dict, Tuple

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "")
RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")


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

    # Zuerst versuchen, die JSON-Fehlermeldung von Bitcoin Core zu lesen
    try:
        result = response.json()
        if result.get("error") is not None:
            raise RuntimeError(
                f"RPC-Fehler bei '{method}': {result['error']}"
            )
        return result["result"]
    except ValueError:
        #error 500
        response.raise_for_status()
        raise

def get_changeAddress(wallet_name: str):
    return rpc_call(
        f"{BITCOIND_RPC_URL}/wallet/{wallet_name}",
        "getrawchangeaddress"
    )


def get_outputAddress(wallet_name: str):
    return rpc_call(
        f"{BITCOIND_RPC_URL}/wallet/{wallet_name}",
        "getnewaddress"
    )


#Alles in einer methode doch BTC CORE
def get_psbt(outputs, wallet_name: str, confirmation_blocks: int, estimate_mode: str, lockTime: int = 0):
    result = rpc_call(
        f"{BITCOIND_RPC_URL}/wallet/{wallet_name}",
        "walletcreatefundedpsbt",
        [
            [],              # inputs: auto coin selection
            outputs,         # outputs
            lockTime,        #für smart contracts
            {
                "add_inputs": True,
                #"fee_rate": "1.2",                 fee rate nicht direkt angeben. BTC CORE überlassen + OPA kontrolle
                "conf_target": confirmation_blocks,               #confirmation in ungefähr einer stunde (fee für 6 blöcke finden)
                "includeWatching": True,
                "replaceable": True,                #Start mit low fee. bei zu langem warten erhöhen ermöglichen
                "estimate_mode": estimate_mode     #Sicherer
            },
            True            #bip32derivs 
        ]
    )

    return result