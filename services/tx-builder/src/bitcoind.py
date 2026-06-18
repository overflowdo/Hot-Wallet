import os
import httpx

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "").rstrip("/") + "/"
BITCOIND_RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
BITCOIND_RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")

HEADERS = {"content-type": "text/plain;"}

class BitcoindRPCError(RuntimeError):
    pass

async def rpc(method, params=None):
    params = params or []

    r = await httpx.post(
        BITCOIND_RPC_URL,
        auth=(BITCOIND_RPC_USER, BITCOIND_RPC_PASS),
        json={
            "jsonrpc": "1.0",
            "id": "middleware",
            "method": method,
            "params": params
        }
    )

    r.raise_for_status()

    body = r.json()

    if body["error"]:
        raise RuntimeError(body["error"])

    return body["result"]


async def get_height() -> int:
    info = await rpc("getblockchaininfo")
    return int(info["blocks"])

async def get_block_hash(height: int) -> str:
    return await rpc("getblockhash", [height])

async def get_block_verbose2(block_hash: str) -> dict:
    # verbosity=2 => decoded tx
    return await rpc("getblock", [block_hash, 2])

async def estimate_sat_per_vb(target_blocks: int) -> int:
    try:
        r = await rpc("estimatesmartfee", [target_blocks])

        if not r:
            return 2

        feerate = r.get("feerate")
        errors = r.get("errors")

        # Bitcoin Core sometimes returns estimates with warnings
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
    

async def fetch_utxos(descriptors: list[str]) -> list[dict]:
    result = await rpc(
        "scantxoutset",
        ["start", descriptors]
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