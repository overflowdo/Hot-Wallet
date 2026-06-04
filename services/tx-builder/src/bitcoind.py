import os
import httpx

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "").rstrip("/") + "/"
BITCOIND_RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
BITCOIND_RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")

HEADERS = {"content-type": "text/plain;"}

class BitcoindRPCError(RuntimeError):
    pass

async def rpc(method: str, params=None, timeout: float = 30.0):
    if params is None:
        params = []
    if not BITCOIND_RPC_URL or BITCOIND_RPC_URL == "/":
        raise BitcoindRPCError("BITCOIND_RPC_URL missing")

    payload = {"jsonrpc": "1.0", "id": "txb", "method": method, "params": params}
    auth = (BITCOIND_RPC_USER, BITCOIND_RPC_PASS)

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(BITCOIND_RPC_URL, json=payload, auth=auth, headers=HEADERS)
        r.raise_for_status()
        j = r.json()

    if j.get("error"):
        raise BitcoindRPCError(f"{method} error: {j['error']}")
    return j["result"]

async def get_height() -> int:
    info = await rpc("getblockchaininfo")
    return int(info["blocks"])

async def get_block_hash(height: int) -> str:
    return await rpc("getblockhash", [height])

async def get_block_verbose2(block_hash: str) -> dict:
    # verbosity=2 => decoded tx
    return await rpc("getblock", [block_hash, 2])

async def estimate_sat_per_vb(target_blocks: int) -> int:
    # estimatesmartfee returns BTC/kvB
    try:
        r = await rpc("estimatesmartfee", [target_blocks])
        feerate = r.get("feerate")  # BTC/kvB
        if feerate is None:
            return 2
        sat_per_kvb = int(float(feerate) * 100_000_000)  # sat/kvB
        sat_per_vb = max(1, sat_per_kvb // 1000)         # sat/vB
        return sat_per_vb
    except Exception:
        return 2