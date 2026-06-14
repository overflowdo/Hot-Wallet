import os
import base64
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import asyncio

from .opa_client import OPAClient
from .opa_mapper import to_opa_input

from embit.psbt import PSBT

import hmac
import secrets

from nats.aio.client import Client as NATS

SIGNER_URL = os.getenv("SIGNER_URL")
SIGNER_HMAC_SECRET = os.getenv("SIGNER_HMAC_SECRET")

nc = None

from .db import (
    archive_txRecord,
    upsert_psbt_artifact,
    insert_psbt,
    create_wallet,
    get_spendable_utxos,
    update_spendable_utxos,
    insert_opa_decision,
    psbt_created_seen
)

class BroadcastRequest(BaseModel):
    signed_rawtx_hex: str

app = FastAPI()

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "")
BITCOIND_RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
BITCOIND_RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")

ARCHIVE_ROOT = os.getenv("ARCHIVE_ROOT", "/var/lib/btc-archive/psbt-archive")
BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
POLICY_SIGNER_URL = os.getenv("POLICY_SIGNER_URL", "http://policy-signer:8080")


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_hex(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False
    
###########################################################################
#Data classes
class PsbtExtractRequest(BaseModel):
    psbt_base64: str


class PsbtExtractResponse(BaseModel):
    rawtx_hex: str

class WalletCreateRequest(BaseModel):
    wallet_id: str
    wallet_type: str

    network: str

    xpub: str

    derivation_path: str | None = None
    master_fingerprint: str | None = None

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

@app.post("/api/v1/wallets")
async def add_wallet(req: WalletCreateRequest):

    await asyncio.to_thread(
        create_wallet,
        req.wallet_id,
        req.wallet_type,
        req.network,
        req.xpub,
        req.derivation_path,
        req.master_fingerprint
    )

    return {
        "success": True,
        "wallet_id": req.wallet_id
    }

@app.post("/api/v1/psbt/extract", response_model=PsbtExtractResponse)
def psbt_extract(req: PsbtExtractRequest):
    try:
        psbt_bytes = base64.b64decode(req.psbt_base64)
    except Exception:
        raise HTTPException(400, "invalid base64")

    try:
        rawtx_hex = extract_rawtx_hex_from_final_psbt(psbt_bytes)
    except Exception as e:
        raise HTTPException(422, f"cannot extract raw tx from psbt: {e}")

    if len(rawtx_hex) < 20:
        raise HTTPException(422, "extracted raw tx too short (psbt not finalized?)")

    return PsbtExtractResponse(rawtx_hex=rawtx_hex)

@app.get("/api/v1/intents/{psbt_id}/psbt")
async def get_psbt(psbt_id: str, format: str = "base64"):
    if format != "base64":
        raise HTTPException(400, "only base64 supported")

    url = f"http://tx-builder.btc-hot.svc.cluster.local:8080/api/v1/work/{psbt_id}/psbt"

    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(url)
        if r.status_code == 404:
            raise HTTPException(404, "psbt not ready")
        r.raise_for_status()
        return r.json()
    

########################################
#utxo
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


####################
#Zu löschen, umbauen oer NATS
@app.post("/api/v1/broadcast")
async def broadcast(body: dict):
    raw = body.get("signed_rawtx_hex")
    if not raw:
        raise HTTPException(400, "signed_rawtx_hex required")

    if not BITCOIND_RPC_URL:
        raise HTTPException(500, "BITCOIND_RPC_URL not configured")

    payload = {"jsonrpc": "1.0", "id": "b", "method": "sendrawtransaction", "params": [raw]}
    auth = (BITCOIND_RPC_USER, BITCOIND_RPC_PASS)

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(BITCOIND_RPC_URL, json=payload, auth=auth)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise HTTPException(502, str(data["error"]))
        return {"txid": data["result"]}


############################################################################
@app.on_event("startup")
async def startup():
    global nc
    nc = NATS()
    await nc.connect(servers=[os.getenv("NATS_URL")])

    async def intent_created_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_intent(data)

    async def psbt_created_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_psbt_created(data)

    async def psbt_failed_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_psbt_failed(data)

    await nc.subscribe(
        "intent.created",
        cb=intent_created_handler
    )

    await nc.subscribe(
        "psbt.created",
        cb=psbt_created_handler
    )

    await nc.subscribe(
        "psbt.failed",
        cb=psbt_failed_handler
    )

##############################################################################
# Event Workflow

#Nach event raised
#OPA Interface
opa = OPAClient()
async def handle_intent(psbt: dict):

    #Deduplication of Tx because of race conditions check
    if await asyncio.to_thread(psbt_created_seen, psbt["id"], "INTENT_CREATED"):
        return

    if psbt.get("type") == "refill":
        psbt["source_address"] = "cold"
    elif psbt.get("type") == "hot-tx":
        psbt["source_address"] = "hot"

        # Nur Hot braucht OPA decision, cold wird vom menschen vor Ausführung überprüft
    
        opa_input = to_opa_input(psbt)

        await asyncio.to_thread(
            insert_psbt,{
                "id": psbt["id"],
                "type": psbt["type"],
                "state": "INTENT_CREATED",        
                "amount_sats": psbt["amount_sats"],
                "source_address": psbt["source_address"],
                "target_address": psbt["target_address"],
                "meta": {},
                "error_code": "-",
            }
        )

        decision = await opa.evaluate_hot_intent(opa_input)

        result = decision.get("result", {})
        allowed = result.get("allow", False)
        reasons = result.get("reasons", [])

        #DB logging
        await asyncio.to_thread(
            insert_opa_decision,
            psbt_id=psbt["id"],
            policy_name="policy.hot",
            actor="middleware",
            allow=allowed,
            reasons=reasons,
            input_data=opa_input,
            result=result
        )

        if not allowed:
            await asyncio.to_thread(
                insert_psbt, {
                    "id": psbt["id"],
                    "type": psbt["type"],
                    "state": "OPA_REJECTED",        
                    "amount_sats": psbt["amount_sats"],
                    "source_address": psbt["source_address"],
                    "target_address": psbt["target_address"],
                    "meta": {},
                    "error_code": psbt["error_code"],
                }
            )
            return

        await asyncio.to_thread(
            insert_psbt, {
                "id": psbt["id"],
                "type": psbt["type"],
                "state": "OPA_APPROVED",        
                "amount_sats": psbt["amount_sats"],
                "source_address": psbt["source_address"],
                "target_address": psbt["target_address"],
                "meta": {},
                "error_code": psbt["error_code"],
            }
        )

    await nc.publish(
        "psbt.build.requested",
        json.dumps({
            "psbt_id": psbt["psbt_id"],
            "network": psbt.get("network"),
            "amount_sats": psbt.get("amount_sats"),
            "target_address": psbt.get("target_address"),
            "meta": psbt.get("meta", {}),
            "sent_at": utc_now_iso()
    }).encode()
)

# Nach OPA senden zu Tx-builder
async def handle_psbt_created(psbt: dict):
    psbt_id = psbt["psbt_id"]

    await asyncio.to_thread(
        insert_psbt, {
            "id": psbt["id"],
            "type": psbt["type"],
            "state": "PSBT_CREATED",        
            "amount_sats": psbt["amount_sats"],
            "source_address": psbt["source_address"],
            "target_address": psbt["target_address"],
            "meta": {},
            "error_code": psbt["error_code"],
        }
    )

    await asyncio.to_thread(
        upsert_psbt_artifact,
        psbt_id,
        "unsigned",
        psbt["psbt_ref"],
        psbt["sha256"],
        None
    )

    signed = None

    if psbt.set("state") == "hot-tx":
        await sign_psbt()


async def handle_psbt_created(psbt: dict):
        #Weiterleitung zu Sign Funktion
        try:
            signed = await sign_psbt_on_signer(
                psbt_id,
                psbt["psbt_ref"],
                psbt["sha256"]
            )
        except Exception as e:
            await asyncio.to_thread(
                insert_psbt, {
                    "id": psbt["id"],
                    "type": psbt["type"],
                    "state": "SIGNING_FAILED",        
                    "amount_sats": psbt["amount_sats"],
                    "source_address": psbt["source_address"],
                    "target_address": psbt["target_address"],
                    "meta": {},
                    "error_code": psbt["error_code"],
                }
            )
            return
        
        #Bei sign file ohne error
        if signed is None:
            await asyncio.to_thread(
                insert_psbt, {
                    "id": psbt["id"],
                    "type": psbt["type"],
                    "state": "SIGNING_FAILED",        
                    "amount_sats": psbt["amount_sats"],
                    "source_address": psbt["source_address"],
                    "target_address": psbt["target_address"],
                    "meta": {},
                    "error_code": psbt["error_code"],
                }
            )
            return
        
        #Nach erfolgreichen Signieren
        await asyncio.to_thread(
            insert_psbt, {
                "id": psbt["id"],
                "type": psbt["type"],
                "state": "PSBT_SIGNED",        
                "amount_sats": psbt["amount_sats"],
                "source_address": psbt["source_address"],
                "target_address": psbt["target_address"],
                "meta": {},
                "error_code": psbt["error_code"],
            }
        )

        # store signed PSBT artifact
        await asyncio.to_thread(
            upsert_psbt_artifact,
            psbt_id,
            "signed",
            psbt["signed_psbt_ref"],
            psbt.get("sha256"),
            None
        )

        if psbt.set("state") == "hot-tx":
            rawtx_hex = signed.get("rawtx_hex")

            if not rawtx_hex:
                raise RuntimeError("Signer did not return rawtx_hex")

            txid = await broadcast_to_bitcoind(rawtx_hex)

            # to add logging

        elif psbt.set("state") == "refill":
            #Notify Human via ntfy for start of manual proess
            return
        
        
####################################################################
#Nach Tx-builder
async def handle_psbt_failed(psbt: dict):
    psbt_id = psbt["psbt_id"]

    await asyncio.to_thread(
            insert_psbt, {
                "id": psbt["id"],
                "type": psbt["type"],
                "state": "PSBT_FAILED",        
                "amount_sats": psbt["amount_sats"],
                "source_address": psbt["source_address"],
                "target_address": psbt["target_address"],
                "meta": {},
                "error_code": psbt["error_code"]",
            }
        )

#Sprich NixOs Signer per WG und HMAC an
async def sign_psbt_on_signer(
        psbt_id: str,
        psbt_ref: str,
        sha256: str,
        psbt_type,
    ):
        timestamp = utc_now_iso()
        nonce = secrets.token_hex(16)

        payload = {
            "psbt_id": psbt_id,
            "psbt_type": psbt_type,
            "psbt_ref": psbt_ref,
            "sha256": sha256,
            "timestamp": timestamp,
            "nonce": nonce
        }

        body = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True
        ).encode()

        msg = timestamp.encode() + nonce.encode() + body

        signature = hmac.new(
            SIGNER_HMAC_SECRET.encode(),
            msg,
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{SIGNER_URL}/sign",
                content=body,
                headers=headers
            )

            r.raise_for_status()

            return r.json()
        

async def broadcast_to_bitcoind(rawtx_hex: str):
    payload = {
        "jsonrpc": "1.0",
        "id": "b",
        "method": "sendrawtransaction",
        "params": [rawtx_hex]
    }

    auth = (BITCOIND_RPC_USER, BITCOIND_RPC_PASS)

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(BITCOIND_RPC_URL, json=payload, auth=auth)
        r.raise_for_status()

        data = r.json()

        if data.get("error"):
            raise RuntimeError(data["error"])

        return data["result"]
