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
from .bitcoind import get_psbt, get_outputAddress
from .models import PSBTModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "tx-builder")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
WORK_ROOT = os.getenv("WORK_ROOT", "/var/lib/btc-work/psbt-work")

MIDDLEWARE_URL= os.getenv("MIDDLEWARE_URL","http://middleware:8080")

#BTC config
HOT_WALLET_DESC = ""
HOT_WALLET_NAME = "keyA"
COLD_WALLET_DESC = ""
COLD_WALLET_NAME = "cormorant"

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

app = FastAPI()

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)



#To be tested
##########################################################################################################
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
###########################################################################################################



#Called from middleware
async def handle_intent_build(msg):
    global nc
    if not nc or not nc.is_connected:
        log.error("nats_not_initialized")
        return

    try:
        intent_data = json.loads(msg.data.decode("utf-8"))
        intent = PSBTModel(
            psbt_id=intent_data["psbt_id"],
            wallet_type=intent_data.get("wallet_type"),
            psbt="",
            network=intent_data.get("network", "regtest"),
            source_address=intent_data.get("source_address"),
            target_address=intent_data.get("target_address"),
            amount_sats=intent_data.get("amount_sats"),
            fee_sats=None,
            fee_rate=None,
            changepos=None,
            state=intent_data.get("state"),           
            meta=intent_data.get("meta"),
            error_code=intent_data.get("error_code")
        )
        if not intent.get("id"):
            return

        # build psbt
        result = await build_psbt_for_intent(intent)

        if result is None or not result.success:
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

        if isinstance(result.psbt, str):
            psbt_bytes = base64.b64decode(result.psbt)
        elif isinstance(result.psbt, bytes):
            psbt_bytes = result.psbt
        else:
            raise ValueError("Invalid PSBT format")

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
                    "psbt_base64": base64.b64encode(psbt_bytes).decode(),
                    "sha256": sha256(psbt_bytes),
                    "meta": intent.get("meta", {}),
                    "created_utc": utc_now_iso(),
                    "resources": result.context or {}
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

  
async def build_psbt_for_intent(intent: PSBTModel) -> PSBTModel:
    intent_id = intent.get("id")
    target_address = None
    #change_desc = None
    changeWallet_name = None

    amount_sats = int(intent.get("amount_sats", 0))
    if amount_sats <= 0:
        log.warning("invalid_amount", extra={
            "intent_id": intent_id,
            "amount_sats": amount_sats
        })
        intent["error_code"] = "INVALID_AMOUNT"
        intent["meta"] = intent["meta"] | {"success=False"}
        return intent

    #Variieren nach auszuführender Aktion
    if intent.get("type") == "refill":
        changeWallet_name = COLD_WALLET_NAME
        target_address = get_outputAddress(HOT_WALLET_NAME)
        
    elif intent.get("type") == "hot-tx":
        #change_desc = HOT_WALLET_DESC
        changeWallet_name = HOT_WALLET_NAME
        #target_address = intent.get("target_address", "") richtig, aber beim testing gerade schwierig#########################################################################################
        target_address = get_outputAddress(COLD_WALLET_NAME)
    else:
        intent["error_code"] = "UNKNOWN_INTENT_TYPE"
        intent["meta"] = intent["meta"] | {"success=False"}
        return intent
    
    #change_address = get_changeAddress(changeWallet_name)
    
    #sats → BTC
    amount_btc = amount_sats / 1e8

    outputs = {
        target_address: amount_btc
    }

    #Vorher manuell fee stabilisierung + block abgragung bei RPC
    #Dann direkte Methode gefunden
    try:
        result = get_psbt(outputs, changeWallet_name)
        
    except Exception as e:
        intent["error_code"] = "RPC_ERROR"
        intent["meta"] = intent["meta"] | {"success=False"} | {"message": str(e)}
        return intent
    
    psbt = result.get("psbt")

    fee_btc = result.get("fee", 0)
    fee_sats = int(fee_btc * 1e8)

    fee_rate = result.get("fee_rate")

    changepos = result.get("changepos", None)


    psbt_bytes = base64.b64decode(psbt) if isinstance(psbt, str) else psbt

    log.info(
        "psbt_created_core",
        extra={
            "intent_id": intent_id,
            "fee_sats": fee_sats,
            "changepos": changepos,
            "fee_rate": result.get("fee_rate"),
            "sha256": sha256(psbt_bytes)
        }
    )

    intent["sha256"] = sha256(psbt_bytes)
    intent["psbt"] = psbt_bytes
    intent["fee_rate"] = result.get("fee_rate")
    intent["fee_sats"] = fee_sats
    intent["change_pos"] = changepos
    intent["meta"] = intent["meta"] | {"success=True"}
    return intent


async def handle_newWallet(msg):
    wallet = json.loads(msg.data.decode("utf-8"))
    if wallet["wallet_id"] == "hot":
        global HOT_WALLET_DESC
        HOT_WALLET_DESC = wallet["desc"]
        global HOT_WALLET_NAME
        HOT_WALLET_NAME = wallet["name"]
    elif wallet["wallet_id"] == "cold": 
        global COLD_WALLET_DESC
        COLD_WALLET_DESC = wallet["desc"]
        global COLD_WALLET_NAME
        COLD_WALLET_NAME = wallet["name"]

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