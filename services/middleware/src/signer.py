import hmac
import os
import secrets
import asyncio
import hashlib
import json
import httpx
import logging
import time
from pathlib import Path

from .db import insert_psbt,get_pending_PSBT, get_psbt_byID
from .models import PSBTModel,create_psbt_msg

REFILL_FILE = Path(os.getenv("REFILL_PSBT", "/run/refill.psbt"))
REFILL_FILE.parent.mkdir(parents=True, exist_ok=True)

SIGNER_URL = os.getenv("SIGNER_URL")
SIGNER_PORT = os.getenv("SIGNER_PORT")
SIGNER_HMAC_SECRET = os.getenv("SIGNER_HMAC_SECRET")
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

if not SIGNER_URL:
    raise RuntimeError("SIGNER_URL is not set")

if not SIGNER_HMAC_SECRET:
    raise RuntimeError("SIGNER_HMAC_SECRET is not set")

log = logging.getLogger("middleware")


#Hilfsfunktion für API communication zur Signer VM
def utc_now_epoch() -> str:
    return str(int(time.time()))

async def sign_psbt(psbt: PSBTModel) -> PSBTModel:
    #Weiterleitung zu Sign Funktion
    try:
        signed = await sign_psbt_on_signer(
            psbt.psbt_id,
            psbt.psbt,
            psbt.sha256,
            psbt.wallet_type
        )
    except Exception as e:
        psbt.state = "SIGNING_FAILED"
        await asyncio.to_thread(
            insert_psbt, psbt
        )
        log.info(f"Ein Fehler ist aufgetreten: {e}")
        return
    
    #Bei sign ohne direkten error
    if signed is None:
        psbt.state = "SIGNING_FAILED"
        await asyncio.to_thread(
            insert_psbt, psbt
        )
        return signed
    
    #Nach erfolgreichen Signieren
    psbt.state = "SIGNED"
    await asyncio.to_thread(
        insert_psbt, psbt
    )

    return signed
        
    

#Sprich NixOs Signer per WG und HMAC an
async def sign_psbt_on_signer(
        psbt_id: str,
        psbt: str,
        sha256: str,
        wallet_type: str,
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
        "wallet_type": wallet_type,
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
            "wallet_type": wallet_type,
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
    

def save_psbt(psbt: str):
    psbt_id = get_pending_PSBT().get("psbt_id")
    if psbt_id is not None:
        delete_psbt(psbt_id, status = True)

    REFILL_FILE.write_text(psbt)

def load_psbt():
    if not REFILL_FILE.exists():
        return None
    return REFILL_FILE.read_text()


#Löscht nicht, sondern schriebt COLD_STOPPED
def delete_psbt(psbt_id = None):
    if psbt_id is not None:
        psbt_info = get_psbt_byID(psbt_id)
        psbt_info['rail'] = "OPA_cold"
        psbt_info['psbt'] = psbt
        psbt = create_psbt_msg(psbt_info)

        psbt.state = "COLD_STOPPED"
        psbt.state = "COLD_STARTED"
        asyncio.to_thread(
            insert_psbt, psbt
        )

    if REFILL_FILE.exists():
        REFILL_FILE.unlink()
