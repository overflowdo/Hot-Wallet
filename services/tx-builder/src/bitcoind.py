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


async def get_height() -> int:
    info = rpc_call(BITCOIND_RPC_URL, "getblockchaininfo")
    return int(info["blocks"])

async def get_block_hash(height: int) -> str:
    return rpc_call(BITCOIND_RPC_URL,"getblockhash", [height])

async def get_block_verbose2(block_hash: str) -> dict:
    #verbosity=2 => decoded tx
    return rpc_call(BITCOIND_RPC_URL, "getblock", [block_hash, 2])

async def estimate_sat_per_vb(target_blocks: int) -> int:
    try:
        r = rpc_call(BITCOIND_RPC_URL, "estimatesmartfee", [target_blocks])

        if not r:
            return 2

        feerate = r.get("feerate")
        errors = r.get("errors")

        # Bitcoin Core  returns estimates with warnings
        if feerate is None:
            return 2

        # optional: treat bad estimates as fallback
        if errors:
            # e.g. "Insufficient data"
            return 2

        # BTC/kVB → sat/vB
        sat_per_kvb = feerate * 100_000_000
        sat_per_vb = sat_per_kvb / 1000

        # safer rounding UP instead of truncation
        return max(1, int(sat_per_vb + 0.999))

    except Exception:
        return 2
    

async def fetch_utxos(descriptors) -> list[dict]:

    # In Liste von Descriptor-Strings umwandeln
    if isinstance(descriptors, str):
        descriptor_list = [descriptors]

    elif isinstance(descriptors, dict):

        if "desc" in descriptors:
            descriptor_list = [descriptors["desc"]]
        else:
            descriptor_list = list(descriptors.values())

    elif isinstance(descriptors, (list, tuple, set)):
        descriptor_list = list(descriptors)

    else:
        raise TypeError(f"Unsupported descriptor type: {type(descriptors)}")

    scan_objects = [
        {"desc": desc}
        for desc in descriptor_list
        if desc.startswith(("wpkh(", "pkh(", "sh(", "wsh(", "tr(", "addr("))
    ]

    result = rpc_call(
        BITCOIND_RPC_URL,
        "scantxoutset",
        ["start", scan_objects]
    )

    unspents = result.get("unspents", [])

    utxos = []

    for u in unspents:
        utxos.append({
            "txid": u["txid"],
            "vout": u["vout"],

            # safer conversion
            "amount_sats": int(round(u["amount"] * 100_000_000)),

            "script_pubkey": u.get("scriptPubKey"),
            "desc": u.get("desc"),
            "height": u.get("height"),
        })

    return utxos

def estimate_vbytes(n_in: int, n_out: int, vin_vb: int, vout_vb: int, base_vb: int = 10) -> int:
    return base_vb + n_in * vin_vb + n_out * vout_vb

def select_utxos(utxos: List[Dict], target_sats: int) -> Tuple[List[Dict], int]:
    chosen = []
    total = 0
    for u in utxos:
        chosen.append(u)
        total += int(u["amount_sats"])
        if total >= target_sats:
            return chosen, total
    return [], 0