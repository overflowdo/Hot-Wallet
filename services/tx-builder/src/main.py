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
from .btc_core import get_psbt, get_outputAddress
from .models import PSBTModel, create_psbt, PaymentIntent, create_paymentIntent_msg

SERVICE_NAME = os.getenv("SERVICE_NAME", "tx-builder")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
WORK_ROOT = os.getenv("WORK_ROOT", "/var/lib/btc-work/psbt-work")

MIDDLEWARE_URL= os.getenv("MIDDLEWARE_URL","http://middleware:8080")

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
    
    intent = await create_paymentIntent_msg(msg.data.decode())

    try:
        if not intent.id:
            return

        # build psbt
        psbt = await build_psbt_for_intent(intent)

        if psbt is None or psbt.psbt == "":
            #metrics logging
            PSBT_BUILT_TOTAL.labels(result="failed").inc()
            INTENTS_TOTAL.labels(type="refill", result="no-psbt").inc()

            psbt.meta = psbt.meta | {"created_utc": utc_now_iso()}

            log.error("intent_handler_failed", extra={"service": SERVICE_NAME, "intent_id": psbt.psbt_id,"status": "intent_handler_failed", "error_code": psbt.error_code, "context": psbt.meta,"created_utc": utc_now_iso()})
            if nc:
                await nc.publish(
                    "psbt.failed",
                    psbt.model_dump_json().encode()
                )
            return

        #metrics logging
        PSBT_BUILT_TOTAL.labels(result="ok").inc()
        INTENTS_TOTAL.labels(type="refill", result="psbt-created").inc()

        psbt.meta = psbt.meta | {"created_utc": utc_now_iso()}

        if nc:
            await nc.publish(
                "psbt.created",
                psbt.model_dump_json().encode()
            )

    except Exception as e:
        intent.meta = intent.meta | {"message": str(e)} | {"created_utc": utc_now_iso()}

        log.error("intent_handler_failed", extra={"service": SERVICE_NAME, "intent_id": intent.id,"status": "intent_handler_failed", "error_code": "INTERNAL_ERROR", "context": {"message": str(e)},"created_utc": utc_now_iso()})
        if nc:
            await nc.publish(
                "psbt.failed",
                intent.model_dump_json().encode()
            )

  
async def build_psbt_for_intent(intent: PaymentIntent) -> PSBTModel:
    intent_id = intent.id
    target_address = intent.target_address

    confirmation_blocks = 6
    estimate_mode = "economical"

    #Variieren nach auszuführender Aktion
    if intent.type == "refill":
        wallet_type = "cold"
        target_address = get_outputAddress(intent.target_address)
        confirmation_blocks = intent.get("meta").get("confirmation_blocks")
        estimate_mode = intent.get("meta").get("estimate_mode")
        
    elif intent.type == "hot-tx":
        wallet_type = "hot"

    else:
        return await create_psbt(
            psbt_id = intent.id,
            wallet_type = wallet_type,
            psbt =  "",
            network = intent.network,
            amount_sats = intent.amount_sats,
            target_address = target_address,
            source_address = intent.source_address,
            state = "PSBT_FAILED",
            meta = intent.meta | {"success=False"},
            error_code = "UNKNOWN_INTENT_TYPE"
        )

    amount_sats = int(intent.amount_sats)
    if amount_sats <= 0:
        log.warning("invalid_amount", extra={
            "intent_id": intent_id,
            "amount_sats": amount_sats
        })

        return await create_psbt(
            psbt_id = intent.id,
            wallet_type = wallet_type,
            psbt =  "",
            network = intent.network,
            amount_sats = intent.amount_sats,
            target_address = target_address,
            source_address = intent.source_address,
            state = "PSBT_FAILED",
            meta = intent.meta | {"success=False"},
            error_code = "INVALID_AMOUNT"
        )

    
    #sats -> BTC
    amount_btc = amount_sats / 1e8

    outputs = {
        target_address: amount_btc
    }

    #früher manuell fee stabilisierung + block abgragung bei RPC
    #Dann direkte Methode gefunden
    try:
        result = get_psbt(outputs, intent.source_address, estimate_mode, confirmation_blocks)
        
    except Exception as e:
        return await create_psbt(
            psbt_id = intent.id,
            wallet_type = wallet_type,
            psbt =  "",
            network = intent.network,
            amount_sats = intent.amount_sats,
            target_address = target_address,
            source_address = intent.source_address,
            state = "PSBT_FAILED",
            meta = intent.meta | {"success=False"} | {"message": str(e)},
            error_code = "RPC_ERROR"
        )
    
    psbt = result.get("psbt")

    fee_btc = result.get("fee")
    fee_sats = int(fee_btc * 1e8)

    changepos = result.get("changepos")


    psbt_bytes = base64.b64decode(psbt) if isinstance(psbt, str) else psbt
    psbt_str = base64.b64encode(psbt_bytes).decode()
    check_sha256 = sha256(psbt_bytes) #Intern bytes

    log.info(
        "psbt_created_core",
        extra={
            "intent_id": intent.id,
            "fee_sats": fee_sats,
            "changepos": changepos,
            "sha256": check_sha256
        }
    )

    return await create_psbt(
        psbt_id = intent.id,
        wallet_type = wallet_type,
        psbt =  psbt_str,
        network = intent.network,
        amount_sats = intent.amount_sats,
        fee_sats = fee_sats,
        fee_rate = None,
        changepos = changepos,
        target_address = target_address,
        source_address = intent.source_address,
        sha256=check_sha256,
        state = "PSBT_CREATED",
        meta = intent.meta,
        error_code={}
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