import os
import json
import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import hashlib
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from nats.aio.client import Client as NATS


from .logging_setup import setup_logging
from .metrics import INTENTS_TOTAL, UTXO_UNSPENT_GAUGE, PSBT_BUILT_TOTAL
from .bitcoind import estimate_sat_per_vb, fetch_utxos, select_utxos, estimate_vbytes
from .psbt_builder import build_psbt


app = FastAPI()

SERVICE_NAME = os.getenv("SERVICE_NAME", "tx-builder")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
WORK_ROOT = os.getenv("WORK_ROOT", "/var/lib/btc-work/psbt-work")

MIDDLEWARE_URL= os.getenv("MIDDLEWARE_URL","http://middleware:8080")

#BTC config
HOT_WALLET_DESC = ""
COLD_WALLET_DESC = ""

# Fee estimation default config
DEFAULT_INPUT_VBYTES = int(os.getenv("VIN_VB_P2WSH", "104"))
DEFAULT_OUTPUT_VBYTES = int(os.getenv("VOUT_VB", "31"))
FEE_TOLERANCE_SATS = int(os.getenv("FEE_TOLERANCE_SATS", "10"))

#Standard values für TXs
FEE_TARGET_BLOCKS = int(os.getenv("FEE_TARGET_BLOCKS", "6"))
MAX_FEE_SATS = int(os.getenv("MAX_FEE_SATS", "50000"))
MAX_FEE_RATE_SAT_VB = int(os.getenv("MAX_FEE_RATE_SAT_VB", "50"))
DUST_LIMIT = int(os.getenv("DUST_LIMIT", "50")) 

log = logging.getLogger("tx-builder")

nc: Optional[NATS] = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


#PSBT in den Speicher schreiben, damit middleware darauf zugreifen kann. Pfad: WORK_ROOT/intent_id/unappr.psbt
def write_work_item(intent_id: str, psbt_bytes: bytes, meta: dict):
    d = Path(WORK_ROOT) / intent_id
    ensure_dir(d)
    (d / "unappr.psbt").write_bytes(psbt_bytes)
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

@dataclass
class PsbtResult:
    success: bool
    intent_id: int
    psbt: Optional[bytes] = None
    error_code: Optional[str] = None
    context: Optional[dict] = field(default_factory=dict)


#To be tested
##########################################################################################################
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/api/v1/work/{intent_id}/psbt")
def get_work_psbt(intent_id: str):
    p = Path(WORK_ROOT) / intent_id / "unappr.psbt"
    if not p.exists():
        raise HTTPException(404, "PSBT not found for intent_id")
    data = p.read_bytes()
    return {"intent_id": intent_id, "psbt_base64": base64.b64encode(data).decode("ascii"), "created_utc": utc_now_iso()}
###########################################################################################################



#Called from middleware
async def handle_intent_build(msg):
    global nc
    if not nc or not nc.is_connected:
        log.error("nats_not_initialized")
        return

    try:
        intent = json.loads(msg.data.decode("utf-8"))
        if not intent.get("id"):
            return

        # build psbt
        result = await build_psbt_for_intent(intent)

        if not result.success or result is None:
            #metrics logging
            PSBT_BUILT_TOTAL.labels(result="failed").inc()
            INTENTS_TOTAL.labels(type="refill", result="no-psbt").inc()

            log.error("intent_handler_failed", extra={"service": SERVICE_NAME, "intent_id": intent.get("id"),"status": "intent_handler_failed", "error_code": result.error_code, "context": result.context,"created_utc": utc_now_iso()})
            if nc:
                await nc.publish(
                "psbt.failed",
                json.dumps({
                    "id": intent.get("id"),
                    "type": intent.get("type"),
                    "network": intent.get("network"),
                    "amount_sats": intent.get("amount_sats"),
                    "target_address": intent.get("target_address"),
                    "error_code": result.error_code,
                    "context": result.context,
                    "meta": intent.get("meta", {}),
                    "created_utc": utc_now_iso()
                }).encode()
            )

            return

        psbt_bytes = result.psbt

        meta = {
            "intent": intent,
            "created_utc": utc_now_iso(),
            "network": BITCOIN_NETWORK
        }
        write_work_item(intent.get("id"), psbt_bytes, meta)

        #metrics logging
        PSBT_BUILT_TOTAL.labels(result="ok").inc()
        INTENTS_TOTAL.labels(type="refill", result="psbt-created").inc()

        if nc:
            await nc.publish(
                "psbt.created",
                json.dumps({
                    "id": intent.get("id"),
                    "type": intent.get("type"),
                    "network": intent.get("network"),
                    "amount_sats": intent.get("amount_sats"),
                    "source_address": intent.get("source_address"),
                    "target_address": intent.get("target_address"),
                    "psbt_path": str(Path(WORK_ROOT) / intent.get("id") / "unappr.psbt"),
                    "psbt_ref": f"psbt-work/{intent.get("id")}/unappr.psbt",
                    "sha256": sha256(psbt_bytes),
                    "meta": intent.get("meta", {}),
                    "created_utc": utc_now_iso()
                }).encode()
            )

    except Exception as e:
        log.error("intent_handler_failed", extra={"service": SERVICE_NAME, "intent_id": intent.get("id"),"status": "intent_handler_failed", "error_code": "INTERNAL_ERROR", "context": {"message": str(e)},"created_utc": utc_now_iso()})
        if nc:
            await nc.publish(
                "psbt.failed",
                json.dumps({
                    "id": intent.get("id"),
                    "type": intent.get("type"),
                    "network": intent.get("network"),
                    "amount_sats": intent.get("amount_sats"),
                    "source_address": intent.get("source_address"),
                    "target_address": intent.get("target_address"),
                    "context": {"message": str(e)},
                    "meta": intent.get("meta", {}),
                    "created_utc": utc_now_iso()
                }).encode()
            )

  
#Hilfsfunktion fee
def estimate_fee_and_vbytes(n_in: int, n_out: int, sat_vb: int):
    vbytes = estimate_vbytes(n_in, n_out, DEFAULT_INPUT_VBYTES, DEFAULT_OUTPUT_VBYTES)
    if vbytes <= 0:
        return None, None
    fee = sat_vb * vbytes
    return fee, vbytes


async def build_psbt_for_intent(intent: dict) -> PsbtResult:
    intent_id = intent.get("id")
    wallet = None
    output_script = None
    change_script = None
    utxos = None

    #Variieren nach auszuführender Aktion
    if intent.get("type") == "refill":
        output_script = HOT_WALLET_DESC
        change_script = COLD_WALLET_DESC
        wallet = "cold"
        
    elif intent.get("type") == "hot-tx":
        output_script = intent.get("target_address")
        change_script = HOT_WALLET_DESC
        wallet = "hot"

    # 0. prereq. amount
    # Redundanz zu OPA, aber wichtiger check für operationelle funktionalität
    amount_sats = int(intent.get("amount_sats", 0))
    if amount_sats <= 0:
        log.warning("invalid_amount", extra={
            "intent_id": intent_id,
            "amount_sats": amount_sats
        })
        return PsbtResult(
            success=False,
            intent_id=intent_id,
            error_code="INVALID_AMOUNT",
        )

    # 1. initial coin selection (no fee)

    utxos = await fetch_utxos(intent.get("descriptors"))
    if not utxos:
        log.warning("no_utxos_available", extra={"intent_id": intent_id})
        return PsbtResult(
            success=False,
            intent_id=intent_id,
            error_code="NO_UTXOS_AVAILABLE"
        )
    
    fee = 0

    sat_vb = await estimate_sat_per_vb(FEE_TARGET_BLOCKS)

    while True:

        chosen, total = select_utxos(utxos, amount_sats + fee)
        if not chosen:
            log.warning("not_enough_utxos_for_amount", extra={"intent_id": intent_id, "amount_sats": amount_sats})
            return PsbtResult(
                success=False,
                intent_id=intent_id,
                error_code="NOT_ENOUGH_UTXOS"
            )
        
        #Vorläufiger Change
        change = total - amount_sats - fee
        if change < 0:
            log.warning("change_negative", extra={"change_sats": change, "total": total, "amount": amount_sats, "fee": fee})
            return PsbtResult(
                success=False,
                intent_id=intent_id,
                error_code="NEGATIVE_CHANGE",
                context={
                    "change_sats": change,
                    "total": total,
                    "amount": amount_sats,
                    "fee": fee
                }
            )

        #Anzahl Outputs
        has_change = change >= DUST_LIMIT
        n_outputs = 2 if has_change else 1

        #Neue Fee
        newFee, vbytes = estimate_fee_and_vbytes(
            len(chosen),
            n_outputs,
            sat_vb
        )
        #Werte kontrollieren
        if newFee is None or vbytes is None:
            log.warning("invalid_vbytes", extra={"intent_id": intent_id})
            return PsbtResult(
                success=False,
                intent_id=intent_id,
                error_code="INVALID_VBYTES"
            )
        if newFee > MAX_FEE_SATS:
            log.warning("fee_too_high", extra={"fee": newFee})
            return PsbtResult(
                success=False,
                intent_id=intent_id,
                error_code="FEE_TOO_HIGH",
                context={"fee_sats": fee}
            )
        newFee_rate = newFee / vbytes
        if newFee_rate > MAX_FEE_RATE_SAT_VB:
            log.warning("fee_rate_too_high", extra={"fee_rate": newFee_rate})
            return PsbtResult(
                success=False,
                intent_id=intent_id,
                error_code="FEE_RATE_TOO_HIGH",
                context={"fee_rate": newFee_rate}
            )
        
        #Abbruch bed.: Fee stabil?
        if abs(newFee - fee) <= FEE_TOLERANCE_SATS and fee != 0:
            fee = newFee
            break
        fee = newFee

    chosen, total = select_utxos(utxos, amount_sats + fee)
    change = total - amount_sats - fee

    outputs = [(output_script, amount_sats)]

    #Unter DUST_Limit change als miner fee
    if change >= DUST_LIMIT:
        psbt_bytes = build_psbt(
            chosen,
            outputs,
            change_script,
            change_sats=change
        )
    else:
        psbt_bytes = build_psbt(
            chosen,
            outputs,
            change_script,
            change_sats=None
        )

    log.info(
        "psbt_created",
        extra={
            "intent_id": intent_id,
            "sha256": sha256(psbt_bytes)
        }
    )

    return PsbtResult(
        success=True,
        intent_id=intent_id,
        psbt=psbt_bytes
    )


async def handle_newWallet(msg):
    wallet = json.loads(msg.data.decode("utf-8"))
    if wallet["wallet_id"] == "hot": 
        global HOT_WALLET_DESC
        HOT_WALLET_DESC = wallet["xpub"]
    elif wallet["wallet_id"] == "cold": 
        global COLD_WALLET_DESC
        COLD_WALLET_DESC = wallet["xpub"]

    log.info(
        "wallet_created",
        extra={
            "wallet_id": wallet["wallet_id"],
        }
    )
    


@app.on_event("startup")
async def startup():
    setup_logging(SERVICE_NAME)
    ensure_dir(Path(WORK_ROOT))

    # NATS setup
    global nc
    nc = NATS()
    await nc.connect(servers=[NATS_URL])

    log.info(
        "nats_connected",
        extra={
            "service": SERVICE_NAME,
            "nats_url": NATS_URL
        }
    )

    await nc.subscribe(
        "psbt.build.requested",
        cb=handle_intent_build
    )

    await nc.subscribe(
        "newWallet.registered",
        cb=handle_newWallet
    )

    log.info(
        "nats_subscribed",
        extra={
            "subject": "psbt.build.requested"
        }
    )

    log.info("tx-builder_started")


@app.on_event("shutdown")
async def shutdown():
    global nc
    if nc:
        await nc.drain()
    log.info("tx-shutdown")