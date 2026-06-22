import asyncio
import os
import logging
import json
from fastapi import APIRouter, Body, Request, HTTPException
from src.db import create_wallet

router = APIRouter()

SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

nc = None


#Genutzt von wgHMAC.sh
#Laden von cold und hot-wallet in die DB
#To Do ZMQ listening service für UTXO changes
@router.post("/api/v1/importWallet")
async def add_wallet(request: Request, metadata: dict = Body(...)):
    nc = request.app.state.nc

    required_fields = ["wallet_type", "network", "xpub"]

    missing = [f for f in required_fields if f not in metadata]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {missing}"
        )
    wallet_name = ""
    if metadata.get("wallet_type") == "cold":
        wallet_name = metadata.get("name") or "cormorant"
    else:
        wallet_name = metadata.get("name") or "keyA"

    wallet_id = metadata.get("wallet_id") or wallet_name or metadata["wallet_type"][:12] or metadata["xpub"][:12]

    await asyncio.to_thread(
        create_wallet,
        wallet_id,
        wallet_name,
        metadata.get("wallet_type") or "external",
        metadata.get("network"),
        metadata.get("xpub",""),
        metadata.get("derivation_path", ""),
        metadata.get("master_fingerprint", ""),
        metadata.get("descriptor")
    )

    log.info(
        "Wallet imported",
        extra={
            "wallet_id": wallet_id,
            "wallet_name": wallet_name,
            "wallet_type": metadata.get("wallet_type") or "external",
            "network": metadata.get("network"),
            "xpub ": metadata.get("xpub",""),
            "derivation_path": metadata.get("derivation_path", ""),
            "master_finderprint": metadata.get("master_fingerprint", ""),
            "descriptor": metadata.get("descriptor")
        }
    )

    #Export for tx-builder
    await nc.publish(
        "newWallet.registered",
        json.dumps({"wallet_id": wallet_id, "wallet_type": metadata.get("wallet_type"), "desc": metadata["descriptor"], "name": wallet_name}).encode()
    )

    return {
        "success": True,
        "wallet_id": wallet_id,
    }