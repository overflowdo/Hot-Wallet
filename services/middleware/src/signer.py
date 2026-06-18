import hmac
import os
import secrets
import asyncio
import hashlib
import json
import httpx
from datetime import datetime, timezone

from .db import insert_psbt, upsert_psbt_artifact

SIGNER_URL = os.getenv("SIGNER_URL")
SIGNER_HMAC_SECRET = os.getenv("SIGNER_HMAC_SECRET")


#Hilfsfunktion für API communication zur Signer VM
def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

async def sign_psbt(psbt: dict) -> dict:
    #Weiterleitung zu Sign Funktion
    try:
        signed = await sign_psbt_on_signer(
            psbt.get("id"),
            psbt.get("psbt_base64"),
            psbt.get("sha256")
        )
    except Exception as e:
        await asyncio.to_thread(
            insert_psbt, {
                "id": psbt.get("id"),
                "type": psbt.get("type"),
                "state": "SIGNING_FAILED",        
                "amount_sats": psbt.get("amount_sats"),
                "source_address": psbt.get("source_address"),
                "target_address": psbt.get("target_address"),
                "meta": {},
                "error_code": e
            }
        )
        return
    
    #Bei sign file ohne error
    if signed is None:
        await asyncio.to_thread(
            insert_psbt, {
                "id": psbt.get("id"),
                "type": psbt.get("type"),
                "state": "SIGNING_FAILED",        
                "amount_sats": psbt.get("amount_sats"),
                "source_address": psbt.get("source_address"),
                "target_address": psbt.get("target_address"),
                "meta": {},
                "error_code": psbt.get("error_code"),
            }
        )
        return signed
    
    #Nach erfolgreichen Signieren
    await asyncio.to_thread(
        insert_psbt, {
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_SIGNED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code"),
        }
    )

    # store signed PSBT artifact
    await asyncio.to_thread(
        upsert_psbt_artifact,
        psbt.get("id"),
        "signed",
        psbt.get("signed_psbt_ref"),
        psbt.get("sha256"),
        None
    )
    return signed
        
    

#Sprich NixOs Signer per WG und HMAC an
async def sign_psbt_on_signer(
        psbt_id: str,
        psbt: str,
        sha256: str,
        psbt_type,
    ):
        timestamp = utc_now_iso()
        nonce = secrets.token_hex(16)

        payload = {
            "psbt_id": psbt_id,
            "psbt_type": psbt_type,
            "psbt_ref": psbt,
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