import os
import httpx
import asyncio
import asyncpg
import logging
import nats

logger = logging.getLogger(__name__)


# -------------------------
# DB CHECK
# -------------------------
async def check_db():
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await conn.fetchval("SELECT 1;")
        await conn.close()
        return True
    except Exception as e:
        logger.error(f"DB health failed: {e}")
        return False


# -------------------------
# NATS CHECK
# -------------------------
async def check_nats():
    try:
        nc = await nats.connect(os.environ["NATS_URL"])
        await nc.close()
        return True
    except Exception as e:
        logger.error(f"NATS health failed: {e}")
        return False


# -------------------------
# BITCOIN RPC CHECK
# -------------------------
async def check_bitcoind():
    try:
        url = os.environ["BITCOIND_RPC_URL"]
        auth = (os.environ["BITCOIND_RPC_USER"], os.environ["BITCOIND_RPC_PASS"])

        payload = {
            "jsonrpc": "1.0",
            "id": "health",
            "method": "getblockchaininfo",
            "params": []
        }

        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.post(url, json=payload, auth=auth)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Bitcoind health failed: {e}")
        return False


# -------------------------
# FULL HEALTH
# -------------------------
async def full_health(service_name: str):
    db = await check_db() if "DATABASE_URL" in os.environ else None
    nats_ok = await check_nats() if "NATS_URL" in os.environ else None
    rpc = await check_bitcoind() if "BITCOIND_RPC_URL" in os.environ else None

    status = "ok"

    if False in [db, nats_ok, rpc]:
        status = "fail"
    elif any(x is False for x in [db, nats_ok, rpc] if x is not None):
        status = "degraded"

    return {
        "service": service_name,
        "status": status,
        "checks": {
            "db": db,
            "nats": nats_ok,
            "rpc": rpc
        }
    }