from urllib.parse import urlparse, parse_qs
import os
import logging
from fastapi import APIRouter, Body, HTTPException, Request

from src.models import create_payment_intent, PaymentIntent

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

    intent = await create_payment_intent(
        rail="bip21",
        network=BITCOIN_NETWORK,
        target_address=address,
        amount_sats=amount_sats,
        meta={
            "label": qs.get("label", [None])[0],
            "source": "bip21"
        }
    )

    intent_id = await publish_intent(nc, intent)

    return {
        "ok": True,
        "intent_id": intent_id
    }



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

    intent = await create_payment_intent(
        rail="psbt",
        network=BITCOIN_NETWORK,
        psbt=psbt,
        source_address=payload.get("source_address"),
        meta={
            "source": "psbt_api"
        }
    )

    intent_id = await publish_intent(nc, intent)

    return {
        "ok": True,
        "intent_id": intent_id
    }


async def publish_intent(nc, intent: PaymentIntent):

    await nc.publish(
        "intent.created",
        intent.model_dump_json().encode()
    )

    return intent.id