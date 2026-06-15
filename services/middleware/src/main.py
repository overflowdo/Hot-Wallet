import os
import json
from datetime import datetime, timezone
from fastapi import Body, FastAPI, HTTPException
import asyncio
from embit.psbt import PSBT
from nats.aio.client import Client as NATS

from .opa import handle_intent
from .broadcast import broadcast_to_bitcoind
from .signer import sign_psbt
from .txBuilder import handle_psbt_created, handle_psbt_failed
from .db import (
    create_wallet,
    get_spendable_utxos,
    update_spendable_utxos,
)


nc = None
app = FastAPI()

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "")
BITCOIND_RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
BITCOIND_RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")

ARCHIVE_ROOT = os.getenv("ARCHIVE_ROOT", "/var/lib/btc-archive/psbt-archive")
BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
POLICY_SIGNER_URL = os.getenv("POLICY_SIGNER_URL", "http://policy-signer:8080")


#Hilfsfunktion für DB insert
def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

#######################################################################
# API Endpoints (per FastAPI, wenn es kein event ist sondern direkt abfrage (anders als NATS))
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
async def health():
    return {
        "service": "middleware",
        "status": "ok"
    }


#Genutzt von wgHMAC.sh
#Laden von cold und hot-wallet in die DB
#To Do ZMQ listening service für UTXO changes
@app.post("/api/v1/importWallet")
async def add_wallet(metadata: dict = Body(...)):

    required_fields = ["wallet_type", "network", "xpub"]

    missing = [f for f in required_fields if f not in metadata]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {missing}"
        )

    wallet_id = metadata.get("wallet_id") or metadata["wallet_type"][:12] or metadata["xpub"][:12]

    await asyncio.to_thread(
        create_wallet,
        wallet_id,
        metadata.get("wallet_type") or "external",
        metadata["network"],
        metadata["xpub"],
        metadata.get("derivation_path", ""),
        metadata.get("master_fingerprint", "")
    )

    return {
        "success": True,
        "wallet_id": wallet_id
    }
    

########################################
#utxo
#genutzt von tx-builder
@app.get("/api/v1/utxo/spendable")
async def get_utxos(wallet_id: str):
    rows = await asyncio.to_thread(
        get_spendable_utxos,
        wallet_id
    )

    return {
        "wallet_id": wallet_id,
        "utxos": rows
    }


#Kann weg?
@app.post("/api/v1/utxo/apply-tx")
async def apply_tx(body: dict):
    """
    body:
    {
        "txid": "...",
        "inputs": [{"txid": "...", "vout": 0}],
        "outputs": [
            {"script": "...", "value": 12345}
        ],
        "height": 0
    }
    """

    txid = body["txid"]
    inputs = body["inputs"]
    outputs = body["outputs"]
    height = body.get("height", 0)

    await asyncio.to_thread(update_spendable_utxos, txid, inputs, outputs, height)

    return {"ok": True}
########################################################################


#Entfernen? kann sparrow für cold finalizen?
def extract_rawtx_hex_from_final_psbt(psbt_bytes: bytes) -> str:
    """
    Extract raw tx hex from a FINALIZED PSBT using embit.

    NOTE:
    - This expects Sparrow already combined+finalized the PSBT.
    - embit API varies; we use a conservative fallback strategy.
    """
    psbt = PSBT.parse(psbt_bytes)

    # Try finalize (idempotent when already finalized)
    try:
        psbt.finalize()
    except Exception:
        pass

    # Some embit versions provide extraction helpers.
    for name in ("extract_tx", "final_tx", "extract_transaction", "finalize_tx"):
        fn = getattr(psbt, name, None)
        if callable(fn):
            tx = fn()
            if hasattr(tx, "serialize"):
                return tx.serialize().hex()
            if isinstance(tx, (bytes, bytearray)):
                return bytes(tx).hex()

    # Fallback: serialize tx object directly
    tx = getattr(psbt, "tx", None)
    if tx is not None and hasattr(tx, "serialize"):
        raw_hex = tx.serialize().hex()
        if len(raw_hex) >= 20:
            return raw_hex

    raise ValueError("cannot extract raw tx (psbt not finalized or unsupported embit version)")


############################################################################
@app.on_event("startup")
async def startup():

    #NATS setup
    global nc
    nc = NATS()
    await nc.connect(servers=[os.getenv("NATS_URL")])

    #Initial
    await nc.subscribe(
        "intent.created",
        cb=intent_created_handler
    )

    #Nach TX-Builder
    await nc.subscribe(
        "psbt.created",
        cb=psbt_created_handler
    )

    await nc.subscribe(
        "psbt.failed",
        cb=psbt_failed_handler
    )


    #Init
    #Weiterleitung zu OPA
    async def intent_created_handler(msg):
        psbt = json.loads(msg.data.decode())
        await handle_intent(psbt)

        await nc.publish(
            "psbt.build.requested",
            json.dumps({
                "id": psbt.get("id"),
                "network": psbt.get("network"),
                "amount_sats": psbt.get("amount_sats"),
                "target_address": psbt.get("target_address"),
                "meta": psbt.get("meta", {}),
                "sent_at": utc_now_iso()
            }).encode()
        )


    #Nach TX-Builder
    #Unerfolgreich    
    async def psbt_failed_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_psbt_failed(data)


    #Nach TX-builder
    #Erfolgreich
    #Weiterleitung zu Signer
    async def psbt_created_handler(msg):
        psbt = json.loads(msg.data.decode())

        await handle_psbt_created(psbt)
        #refill und hot-tx müssen gesigned werden
        #Weiterleitung zum Signer
        signed = await sign_psbt()

        if psbt.set("state") == "hot-tx":
            rawtx_hex = signed.get("rawtx_hex")

            if not rawtx_hex:
                raise RuntimeError("Signer did not return rawtx_hex")

            #Broadcasting
            txid = await broadcast_to_bitcoind(rawtx_hex)

            # to add logging

        elif psbt.set("state") == "refill":
            #Notify Human via ntfy for start of manual proess
            return