import logging
import os
import hashlib
import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.signer import load_psbt, delete_psbt
from src.db import insert_psbt, archive_psbt, get_psbt_byID, get_pending_PSBT
from .btc_core import broadcast_to_bitcoind, psbt_finalize
from src.models import create_psbt_msg

SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")

log = logging.getLogger(SERVICE_NAME)

router = APIRouter(prefix="/api/v1/request", tags=["psbt"])


def hash_psbt(psbt: str) -> str:
    return hashlib.sha256(psbt.encode()).hexdigest()


@router.get("/psbt")
async def psbt():

    psbt = load_psbt()
    if psbt is None:
        raise HTTPException(status_code=404, detail="No PSBT available")

    psbt_info = get_pending_PSBT()
    psbt_id = psbt_info.get("psbt_id")
    psbt_info['rail'] = "OPA_cold"
    psbt_info['psbt'] = psbt
    psbt = create_psbt_msg(psbt_info)

    if psbt is None:
        raise HTTPException(status_code=404, detail="No refill PSBT available")

    #Nur loeschen der Datei, nicht Status überschreiben
    delete_psbt()
    

    psbt.state = "COLD_STARTED"
    await asyncio.to_thread(
        insert_psbt, psbt
    )

    payload = json.dumps({
        "psbt_id": psbt_id,
        "psbt": psbt
    })

    return PlainTextResponse(payload)


@router.post("/broadcast")
async def broadcast_psbt(psbt_id: str, request: Request):

    psbt_signed = (await request.body()).decode().strip()

    if not psbt_signed:
        raise HTTPException(status_code=400, detail="Empty PSBT")
    
    psbt_info = get_psbt_byID(psbt_id)
    if psbt_info.get("psbt_state") != "COLD_STARTED":
        log.warning(f"Invalid broadcast state psbt_id={psbt_id}")
        raise HTTPException(
            status_code=409,
            detail="Invalid PSBT state for broadcast"
        )
    
    psbt_info['rail'] = "OPA_cold"
    psbt_info['psbt'] = psbt_signed

    psbt = create_psbt_msg(psbt_info)
        

    psbt_hash = hash_psbt(psbt_signed)

    log.info(f"Broadcast request psbt_id={psbt_id} hash={psbt_hash}")

    try:
        #finalize
        rawtx_hex = psbt_finalize(psbt_signed)

    except Exception as e:
        log.exception("Failed to finalize PSBT")
        raise HTTPException(status_code=400, detail=f"finalization failed: {e}")

    try:
        #broadcast
        txid = broadcast_to_bitcoind(rawtx_hex)

        if not txid:
            raise RuntimeError("Bitcoind returned empty txid")

    except Exception as e:
        log.exception("Broadcast failed")
        raise HTTPException(status_code=400, detail=f"broadcast failed: {e}")
    
    

    #persist final state (optional tracking)
    psbt.state = "BROADCASTED"
    await asyncio.to_thread(
        insert_psbt, psbt
    )

    await asyncio.to_thread(
        archive_psbt, {
            **psbt.model_dump(),
            "final_tx": rawtx_hex,
            "txid": txid
        }
    )

    log.info(f"Broadcast success txid={txid}")

    return {
        "txid": txid,
        "psbt_hash": psbt_hash,
    }