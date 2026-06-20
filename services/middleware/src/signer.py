import hmac
import os
import secrets
import asyncio
import hashlib
import json
import httpx
from datetime import datetime, timezone
import logging
import time

from .db import insert_psbt, upsert_psbt_artifact

SIGNER_URL = os.getenv("SIGNER_URL")
SIGNER_PORT = os.getenv("SIGNER_PORT")
SIGNER_HMAC_SECRET = os.getenv("SIGNER_HMAC_SECRET")

if not SIGNER_URL:
    raise RuntimeError("SIGNER_URL is not set")

if not SIGNER_HMAC_SECRET:
    raise RuntimeError("SIGNER_HMAC_SECRET is not set")

log = logging.getLogger("middleware")


#Hilfsfunktion für API communication zur Signer VM
def utc_now_epoch() -> str:
    return str(int(time.time()))

async def sign_psbt(psbt: dict) -> dict:
    #Weiterleitung zu Sign Funktion
    try:
        signed = await sign_psbt_on_signer(
            psbt.get("id"),
            psbt.get("psbt_base64"),
            psbt.get("sha256"),
            psbt.get("type")
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
                "error_code": str(e)
            }
        )
        log.info(f"Ein Fehler ist aufgetreten: {e}")
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
        psbt_type: str,
    ):
    if os.path.isfile(SIGNER_HMAC_SECRET):
        print("Gültige Datei")
        with open(SIGNER_HMAC_SECRET, "r") as f:
            secret = bytes.fromhex(f.read().strip())
    else:
        print("Nicht vorhanden oder kein File")
        raise FileNotFoundError(
                f"HMAC secret not found: {SIGNER_HMAC_SECRET}"
        )
    
    
    
    timestamp = utc_now_epoch()
    nonce = secrets.token_hex(16)

    payload = {
        "psbt_id": psbt_id,
        "psbt_type": psbt_type,
        "psbt": psbt,
        "sha256": sha256,
    }

    body = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True
    ).encode()

    msg = timestamp.encode() + nonce.encode() + body

    signature = hmac.new(
        secret,
        msg,
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }
    
    url = f"{SIGNER_URL}:{SIGNER_PORT}/sign"

    log.info(
        f"Sende asynchrone Anfrage an: {url}",
        extra={
            "psbt_id": psbt_id,
            "psbt_type": psbt_type,
            "psbt": psbt,
            "sha256": sha256,
        }
    )

 
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                url,
                content=body,
                headers=headers
            )
            
            print(f"Status Code vom Signer erhalten: {r.status_code}")
            
            r.raise_for_status() 
            
            return r.json()
 
    except httpx.HTTPStatusError as e:
        print(f"Signer lieferte Fehler-Status: {e.response.status_code} - Text: {e.response.text}")
        raise RuntimeError(f"Signer request failed with status {e.response.status_code}: {e.response.text}") from e
        
    except httpx.RequestError as e:
        print(f"Netzwerkfehler beim Verbindungsaufbau: {e}")
        raise RuntimeError(f"Signer network request failed: {e}") from e
    
    except httpx.HTTPError as e:
        raise RuntimeError(f"Signer request failed: {e}") from e