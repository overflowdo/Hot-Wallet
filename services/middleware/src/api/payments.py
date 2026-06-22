from urllib.parse import urlparse, parse_qs
import os
import logging
from fastapi import APIRouter, Body, HTTPException, Request
from decimal import Decimal

from src.models import create_paymentIntent, PaymentIntent, create_psbt, PSBTModel
from uuid import uuid4 
from src.db import psbt_id_exists
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

    if not uri.startswith("bitcoin://"):
        normalized_uri = uri.replace("bitcoin:", "bitcoin://", 1)
    else:
        normalized_uri = uri

    parsed = urlparse(normalized_uri)
    address = parsed.netloc
    qs = parse_qs(parsed.query)

    if not address:
        raise HTTPException(
            status_code=400, detail="Could not extract Bitcoin address"
        )

    amount_sats = None
    if "amount" in qs:
        try:
            amount_btc_str = qs.get("amount")[0]
            # Konvertierung direkt von String zu Decimal verhindert Rundungsfehler
            amount_btc = Decimal(amount_btc_str)
            amount_sats = int(amount_btc * Decimal("100000000"))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="Invalid amount format in URI"
            )

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
            "message": qs.get("message", [None])[0],
            "source": "bip21",
        },
    )

    await publish_intent(nc, intent)

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

    psbt_model = await create_psbt(
        psbt_id=psbt_id,
        wallet_type="hot",
        psbt=psbt,
        rail="psbt",
        network=BITCOIN_NETWORK,
        source_address="hot",
        sha256=payload.get("sha256"),
        state="PSBT_CREATED",
    )

    await publish_psbt(nc, psbt_model)

    return {
        "ok": True,
        "psbt_id": psbt_id
    }

async def publish_psbt(nc, psbt: PSBTModel):

    await nc.publish(
        "psbt.created",
        psbt.model_dump_json().encode()
    )