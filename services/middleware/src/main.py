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

from .db import update_intent_state

from embit.psbt import PSBT

import hmac
import secrets

from nats.aio.client import Client as NATS

SIGNER_URL = os.getenv("SIGNER_URL")
SIGNER_HMAC_SECRET = os.getenv("SIGNER_HMAC_SECRET")

nc = None

from .db import (
    ArchivedTxRecord,
    upsert_archived_tx,
    upsert_psbt_artifact,
    update_intent_state,
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
    
class PsbtExtractRequest(BaseModel):
    psbt_base64: str


class PsbtExtractResponse(BaseModel):
    rawtx_hex: str


@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
async def health():
    return {
        "service": "middleware",
        "status": "ok"
    }


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


@app.post("/api/v1/archive/broadcasted")
async def archive_broadcasted(
    id: str = Form(...),
    txid: str = Form(...),
    broadcast_utc: str = Form(...),
    rawtx_hex: Optional[str] = Form(None),
    intent_id: Optional[str] = Form(None),
    final_psbt_file: UploadFile = File(...),
    approval_json_file: Optional[UploadFile] = File(None),
    approval_sig_file: Optional[UploadFile] = File(None),
):
    if not id or not txid:
        raise HTTPException(400, "id and txid required")

    root = Path(ARCHIVE_ROOT)
    tx_dir = root / id
    tx_dir.mkdir(parents=True, exist_ok=True)

    psbt_bytes = await final_psbt_file.read()
    if not psbt_bytes:
        raise HTTPException(400, "final_psbt_file empty")

    psbt_name = f"final.{id}.psbt"
    psbt_path = tx_dir / psbt_name
    psbt_path.write_bytes(psbt_bytes)

    rawtx_path = None
    rawtx_sha = None
    if rawtx_hex:
        rawtx_path = tx_dir / "rawtx_hex.txt"
        rawtx_path.write_text(rawtx_hex.strip() + "\n", encoding="utf-8")
        if is_hex(rawtx_hex):
            rawtx_sha = sha256_hex(bytes.fromhex(rawtx_hex.strip()))

    record = {
        "id": id,
        "txid": txid,
        "broadcast_utc": broadcast_utc,
        "archived_utc": utc_now_iso(),
        "network": BITCOIN_NETWORK,
        "source": "manual-usb",
        "final_psbt": psbt_name,
        "sha256_final_psbt": sha256_hex(psbt_bytes),
        "intent_id": intent_id,
    }
    (tx_dir / "broadcast.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    approval_json_path = None
    approval_sig_path = None

    if approval_json_file is not None:
        aj = await approval_json_file.read()
        if aj:
            p = tx_dir / "approval.json"
            p.write_bytes(aj)
            approval_json_path = str(p)

    if approval_sig_file is not None:
        asig = await approval_sig_file.read()
        if asig:
            p = tx_dir / "approval.json.sig"
            p.write_bytes(asig)
            approval_sig_path = str(p)

    archive_path = f"psbt-archive/{id}/"
    final_psbt_fullpath = str(psbt_path)

    rec = ArchivedTxRecord(
        id=id,
        network=BITCOIN_NETWORK,
        source="manual-usb",
        txid=txid,
        broadcast_utc=broadcast_utc,
        archive_path=archive_path,
        final_psbt_path=final_psbt_fullpath,
        final_psbt_sha256=sha256_hex(psbt_bytes),
        rawtx_hex_path=str(rawtx_path) if rawtx_path else None,
        rawtx_sha256=rawtx_sha,
        approval_json_path=approval_json_path,
        approval_sig_path=approval_sig_path,
        meta={"intent_id": intent_id} if intent_id else {},
    )

    # psycopg is sync -> run in thread
    await asyncio.to_thread(upsert_archived_tx, rec)

    if intent_id:
        await asyncio.to_thread(
            upsert_psbt_artifact,
            intent_id,
            "final",
            f"archive:/{archive_path}{psbt_name}",
            sha256_hex(psbt_bytes),
            len(psbt_bytes),
        )

    return {"stored": True, "archive_path": archive_path}
from typing import Optional

@app.get("/api/v1/intents/{intent_id}/psbt")
async def get_psbt(intent_id: str, format: str = "base64"):
    if format != "base64":
        raise HTTPException(400, "only base64 supported")

    url = f"http://tx-builder.btc-hot.svc.cluster.local:8080/api/v1/work/{intent_id}/psbt"

    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(url)
        if r.status_code == 404:
            raise HTTPException(404, "psbt not ready")
        r.raise_for_status()
        return r.json()

@app.on_event("startup")
async def startup():
    global nc
    nc = NATS()
    await nc.connect(servers=[os.getenv("NATS_URL")])

    async def intent_created_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_intent(data, nc)

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
        "intent.psbt.created",
        cb=psbt_created_handler
    )

    await nc.subscribe(
        "intent.psbt.failed",
        cb=psbt_failed_handler
    )

    await nc.subscribe(
        "intent.psbt.signed",
        cb=psbt_signed_handler
    )

    await nc.subscribe(
        "intent.psbt.unsigned",
        cb=psbt_unsigned_handler
    )

#OPA Interface
opa = OPAClient()
async def handle_intent(intent: dict, nc):
    opa_input = to_opa_input(intent)

    await asyncio.to_thread(
        update_intent_state,
        intent["intent_id"],
        "RECEIVED",
        {"received_at": utc_now_iso(), "source": "middleware"}
    )

    decision = await opa.evaluate_hot_intent(opa_input)

    result = decision.get("result", {})
    allowed = result.get("allow", False)
    reasons = result.get("reasons", [])

    if not allowed:
        await asyncio.to_thread(
            update_intent_state,
            intent["intent_id"],
            "OPA_REJECTED",
            decision
        )

        await nc.publish(
            "intent.rejected",
            json.dumps({
                "intent_id": intent.get("intent_id"),
                "reasons": reasons
            }).encode()
        )
        return

    await asyncio.to_thread(
        update_intent_state,
        intent["intent_id"],
        "OPA_APPROVED",
        decision
    )
    await nc.publish(
        "intent.build.requested",
        json.dumps({
            "intent_id": intent["intent_id"],
            "network": intent.get("network"),
            "amount_sats": intent.get("amount_sats"),
            "target_address": intent.get("target_address"),
            "reason": intent.get("reason"),
            "meta": intent.get("meta", {}),
            "approved_at": utc_now_iso()
    }).encode()
)

async def handle_psbt_created(event: dict):
    intent_id = event["intent_id"]

    await asyncio.to_thread(
        update_intent_state,
        intent_id,
        {
            "state": "PSBT_CREATED",
            "created_utc": event.get("created_utc")
        }
        
    )

    await asyncio.to_thread(
        upsert_psbt_artifact,
        intent_id,
        "unsigned",
        event["psbt_ref"],
        event["sha256"],
        None
    )

    #Weiterleitung zu Sign Funktion
    try:
        signed = await sign_psbt_on_signer(
            intent_id,
            event["psbt_ref"],
            event["sha256"]
        )
    except Exception as e:
        await asyncio.to_thread(
            update_intent_state,
            intent_id,
            "FAILED",
            {
                "error_code": "SIGNER_ERROR",
                "message": str(e)
            }
        )
        return
    
    #Nach erfolgreichen Signieren NATS event pisblishen
    await nc.publish(
        "intent.psbt.signed",
        json.dumps({
            "intent_id": intent_id,
            "signed_psbt_ref": signed["signed_psbt_ref"],
            "sha256": signed["sha256"],
            "created_utc": utc_now_iso()
        }).encode()
    )

#Sprich NixOs Signer per WG und HMAC an
async def sign_psbt_on_signer(
        intent_id: str,
        psbt_ref: str,
        sha256: str,
    ):
        timestamp = utc_now_iso()
        nonce = secrets.token_hex(16)

        payload = {
            "intent_id": intent_id,
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





async def handle_psbt_failed(event: dict):
    intent_id = event["intent_id"]

    await asyncio.to_thread(
        update_intent_state,
        intent_id,
        {
            "state": "PSBT_FAILED",
            "created_utc": event.get("created_utc"),
            "error_code": event.get("error_code")
        }
    )

async def psbt_signed_handler(msg):
    event = json.loads(msg.data.decode())
    intent_id = event["intent_id"]

    # update state
    await asyncio.to_thread(
        update_intent_state,
        intent_id,
        "PSBT_SIGNED",
        {
            "signed_at": utc_now_iso(),
            "source": "signer-node"
        }
    )

    # store signed PSBT artifact
    await asyncio.to_thread(
        upsert_psbt_artifact,
        intent_id,
        "signed",
        event["signed_psbt_ref"],
        event.get("sha256"),
        None
    )

    await nc.publish(
        "intent.broadcast.requested",
        json.dumps({
            "intent_id": intent_id,
            "signed_psbt_ref": event["signed_psbt_ref"],
            "created_utc": utc_now_iso()
        }).encode()
    )

async def psbt_unsigned_handler(msg):
    event = json.loads(msg.data.decode())
    intent_id = event["intent_id"]

    # update state
    await asyncio.to_thread(
        update_intent_state,
        intent_id,
        "PSBT_UNSIGNED",
        {
            "signed_at": utc_now_iso(),
            "source": "signer-node"
        }
    )