import asyncio
import os
import logging
import json
from fastapi import APIRouter, Body, Request, HTTPException

from src.db import create_wallet
from .btc_core import rpc_call


RPC_URL  = os.getenv("BTC-CORE_RPC_URL", "http://btc-core:18443")
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

nc = None
router = APIRouter()

def normalize(desc_string: str) -> str:
    # Whitespaces entfernen
    desc = desc_string.strip()

    # Checksumme abschneiden (Immer # + 8 Zeichen = 9 Zeichen von rechts)
    if "#" in desc:
        desc = desc[:-9]

    return desc


@router.post("/api/v1/importWallet")
async def add_wallet(request: Request, metadata: dict = Body(...)):
    nc = request.app.state.nc

    # Load data out of API call
    required_fields = ["wallet_type", "network"]
    missing = [f for f in required_fields if f not in metadata]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {missing}"
        )
    
    wallet_name = metadata.get("wallet_name")
    xpub_backup = metadata.get("xpub", "")
    wallet_id = metadata.get("wallet_id") or wallet_name or xpub_backup[:12] or "unknown_id"

    # BTC-CORE registration
    WALLET_RPC_URL = f"{RPC_URL}/wallet/{wallet_name}"

    # Wallet erzeugen
    rpc_call(
        RPC_URL,
        "createwallet",
        [
            wallet_name,
            True,   # Disable priv keys
            True,   # blank wallet
            "",
            False,
            True    # descriptor (neue Architektur)
        ],
        rpc_id=f"createwallet {wallet_name}"
    )

    raw_desc = metadata.get("descriptor", "")
    if "#" in raw_desc:
        raw_desc = raw_desc[:-9]

    if not raw_desc:
        raise HTTPException(status_code=400, detail="Descriptor is empty")

    desc_payload = []

    # Descriptor mit Checksum versehen via Bitcoin Core
    desc_info = rpc_call(RPC_URL, "getdescriptorinfo", [raw_desc], rpc_id="checksum_multipath")
    if "multipath_expansion" in desc_info and len(desc_info["multipath_expansion"]) >= 2:
        ext_desc = desc_info["multipath_expansion"][0]
        int_desc = desc_info["multipath_expansion"][1]

        desc_payload = [
            {
                "desc": ext_desc,
                "timestamp": "now",
                "active": True,
                "internal": False,  # Externe Empfangsadressen
                "keypool": True,
                "range": [0, 1000]
            },
            {
                "desc": int_desc,
                "timestamp": "now",
                "active": True,
                "internal": True,   # Interne Wechselgeld-Adressen (Change)
                "keypool": True,
                "range": [0, 1000]
            }
        ]
    else:
        desc_payload = [
            {
                "desc": desc_info["descriptor"],
                "timestamp": "now",
                "active": True,
                "internal": False,
                "keypool": True,
                "range": [0, 1000]
            }
        ]
    

    # Descriptoren in Bitcoin Core importieren
    rpc_call(
        WALLET_RPC_URL,
        "importdescriptors",
        [desc_payload],
        rpc_id=f"import desc {wallet_name}"
    )

    # Wallet prüfen
    wallet_info = rpc_call(
        WALLET_RPC_URL,
        "getwalletinfo",
        [],
        rpc_id=f"info: {wallet_name}"
    )

    # Write to DB
    await asyncio.to_thread(
        create_wallet,
        wallet_id,
        wallet_name,
        metadata.get("wallet_type") or "external",
        metadata.get("network"),
        xpub_backup,
        metadata.get("derivation_path", ""),
        metadata.get("fingerprint", ""),
        metadata.get("descriptor")
    )

    log.info(
        "Wallet imported",
        extra={
            "wallet_id": wallet_id,
            "wallet_name": wallet_name,
            "wallet_type": metadata.get("wallet_type") or "external",
            "network": metadata.get("network"),
            "xpub": xpub_backup,
            "derivation_path": metadata.get("derivation_path", ""),
            "fingerprint": metadata.get("fingerprint", ""),
            "descriptor": metadata.get("descriptor"),
            "wallet_info": json.dumps(wallet_info, indent=2)
        }
    )

    return {
        "success": True,
        "wallet_id": wallet_id,
    }