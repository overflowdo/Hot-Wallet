import os
import requests

RPC_URL = os.getenv("BTC-CORE_RPC_URL", "")
RPC_USER = os.getenv("BTC-CORE_RPC_USER", "")
RPC_PASS = os.getenv("BTC-CORE_RPC_PASS", "")


class BitcoindRPCError(RuntimeError):
    pass

def rpc_call(url, method, params=None, rpc_id="middleware"):
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

def broadcast_to_bitcoind(raw_tx_hex: str):
    return rpc_call(
        f"{RPC_URL}",
        "sendrawtransaction",
        [raw_tx_hex]
    )


def address_wallet_match(wallet_name: str, address: str) -> bool:
    result = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name}",
        "getaddressinfo",
        [address]
    )

    return result.get("ismine", False)