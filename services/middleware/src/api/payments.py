from urllib.parse import urlparse, parse_qs
import os
import logging
from fastapi import APIRouter, Body, HTTPException, Request

from src.models import create_paymentIntent, PaymentIntent, create_psbt, PSBTModel
from uuid import uuid4 
from .db import psbt_id_exists
import asyncio

BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

router = APIRouter(prefix="/api/v1/request", tags=["payments"])

@router.post("/bip21")
async def request_bip21(request: Request, payload: dict = Body(...)):
    """
    payload:
    {
        "uri": "bitcoin:bc1qxyz...?amount=0.001&label=test"
    }
    """
    nc = request.app.state.nc

    uri = payload.get("uri")
    if not uri or not uri.startswith("bitcoin:"):
        raise HTTPException(status_code=400, detail="Invalid BIP21 URI")

    parsed = urlparse(uri)
    address = parsed.path
    qs = parse_qs(parsed.query)

    amount_btc = float(qs.get("amount", [0])[0]) if "amount" in qs else 0
    amount_sats = int(amount_btc * 100_000_000) if amount_btc else None

    intent_id = ""
    while True:
        intent_id = str(uuid4())
        exists = await asyncio.to_thread(psbt_id_exists, intent_id)
        if not exists:
            break

    intent = await create_paymentIntent(
        intent_id=intent_id,
        rail="bip21",
        network=BITCOIN_NETWORK,
        amount_sats=amount_sats,
        target_address=address,
        meta={
            "label": qs.get("label", [None])[0],
            "source": "bip21"
        }
    )

    publish_intent(nc, intent)

    return {
        "ok": True,
        "intent_id": intent_id
    }

async def publish_intent(nc, intent: PaymentIntent):

    await nc.publish(
        "intent.created",
        intent.model_dump_json().encode()
    )


#######################################################


@router.post("/psbt")
async def request_psbt(request: Request, payload: dict = Body(...)):
    """
    payload:
    {
        "psbt": "cHNidP8BAHECA....",
        "source_address": "... (optional metadata)"
    }
    """
    nc = request.app.state.nc

    psbt = payload.get("psbt")
    if not psbt:
        raise HTTPException(status_code=400, detail="Missing PSBT")
    
    psbt_id = ""
    while True:
        psbt_id = str(uuid4())
        exists = await asyncio.to_thread(psbt_id_exists, psbt_id)
        if not exists:
            break

    psbt = await create_psbt(
        psbt_id=psbt_id,
        wallet_type="hot",
        psbt=psbt,
        rail="psbt",
        network=BITCOIN_NETWORK,
        source_address="hot",
        sha256=payload.get("sha256"),
        state="PSBT_CREATED",
    )

    publish_psbt(nc, psbt)

    return {
        "ok": True,
        "psbt_id": psbt_id
    }

async def publish_psbt(nc, psbt: PSBTModel):

    await nc.publish(
        "psbt.created",
        psbt.model_dump_json().encode()
    )