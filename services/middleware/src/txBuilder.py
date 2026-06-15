import asyncio

from .db import insert_psbt, upsert_psbt_artifact

# Nach OPA senden zu Tx-builder (forwarding in middleware nc subscribe (oben))
#Nach Tx-builder, WENN FEHLSCHLUG
async def handle_psbt_failed(psbt: dict):

    await asyncio.to_thread(
        insert_psbt, {
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_FAILED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code"),
        }
    )


#Hier funktion nach Tx-builder, wenn ERFOLGREICH
async def handle_psbt_created(psbt: dict):

    await asyncio.to_thread(
        insert_psbt, {
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_CREATED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code"),
        }
    )


    await asyncio.to_thread(
        upsert_psbt_artifact,
        psbt.get("id"),
        "unsigned",
        psbt.get("psbt_ref"),
        psbt.get("sha256"),
        None
    )