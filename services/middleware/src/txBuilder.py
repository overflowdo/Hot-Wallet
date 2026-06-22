import asyncio
import logging
import os

from .db import insert_psbt
from .models import PSBTModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

# Nach OPA senden zu Tx-builder (forwarding in middleware nc subscribe (oben))
#Nach Tx-builder, WENN FEHLSCHLUG
async def handle_psbt_failed(psbt: PSBTModel):

    log.info(
        "PSBT build failed",
        extra={
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_FAILED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code")
        }
    )

    await asyncio.to_thread(
        insert_psbt, {
            psbt
        }
    )


#Hier funktion nach Tx-builder, wenn ERFOLGREICH
async def handle_psbt_created(psbt: PSBTModel):
    
    log.info(
        "PSBT build success",
        extra={
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_CREATED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code")
        }
    )

    await asyncio.to_thread(
        insert_psbt, {
            psbt
        }
    )