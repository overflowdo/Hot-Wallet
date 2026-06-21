import os
import requests

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

def send_raw_transaction(raw_tx_hex: str):
    return rpc_call(
        f"{BITCOIND_RPC_URL}",
        "sendrawtransaction",
        [raw_tx_hex]
    )