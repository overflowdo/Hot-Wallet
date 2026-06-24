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

def normalize(desc_string):
    #Whitespaces entfernen
    desc = desc_string.strip()

    #Checksumme abschneiden (Immer # + 8 Zeichen = 9 Zeichen von rechts)
    if "#" in desc:
        desc = desc[:-9]

    #Interne/Externe Kombination <0;1> durch reine 0 ersetzen
    # Ersetzt "/<0;1>/*" mit "/0/*"
    desc = desc.replace("/<0;1>/*", "/0/*")

    #Falls irgendwo fälschlicherweise der interne Pfad /1/* stand,
    # wird auch dieser für das externe Skript auf /0/* korrigiert
    desc = desc.replace("/1/*", "/0/*")

    return desc


#Genutzt von wgHMAC.sh
#Laden von cold und hot-wallet in die DB
#To Do ZMQ listening service für UTXO changes
@router.post("/api/v1/importWallet")
async def add_wallet(request: Request, metadata: dict = Body(...)):
    nc = request.app.state.nc

    #Load data out of API call
    required_fields = ["wallet_type", "network", "xpub"]

    missing = [f for f in required_fields if f not in metadata]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {missing}"
        )
    
    wallet_name = metadata.get("wallet_name")
    wallet_id = metadata.get("wallet_id") or wallet_name or metadata["xpub"][:12]

    #BTC-CORE registration
    WALLET_RPC_URL = f"{RPC_URL}/wallet/{wallet_name}"

    # Wallet erzeugen
    rpc_call(
        RPC_URL,
        "createwallet",
        [
            wallet_name,
            True,   #Disable priv keys
            True,   #blank wallet
            "",
            False,
            True    #descriptor (neue Architektur)
        ],
        rpc_id=f"createwallet {wallet_name}"
    )
    
    external_desc = normalize(metadata.get("descriptor"))
    if metadata.get("wallet_type") == "cold" or metadata.get("wallet_type") == "hot":
        # Interner Change-Descriptor (/1/*)
        internal_desc = external_desc.replace("/0/*", "/1/*")

        int_desc_info = rpc_call(
            RPC_URL,
            "getdescriptorinfo",
            [internal_desc],
            rpc_id=f"checksum {wallet_name}"
        )
        int_desc = int_desc_info["descriptor"]
    

    # Descriptor mit Checksum versehen
    ext_desc_info = rpc_call(
        RPC_URL,
        "getdescriptorinfo",
        [external_desc],
        rpc_id="checksum"
    )
    ext_desc = ext_desc_info["descriptor"]

    

    desc = [
            {
                "desc": ext_desc,
                "timestamp": "now",
                "active": True,
                "internal": False,
                "keypool": True,
                "range": [0, 1000]
            },
            {
                "desc": int_desc,
                "timestamp": "now",
                "active": True,
                "internal": True,
                "keypool": True,
                "range": [0, 1000]
            }
        ]

    # Descriptor importieren
    rpc_call(
        WALLET_RPC_URL,
        "importdescriptors",
        desc,
        rpc_id=f"import desc {wallet_name}"
    )


    # Wallet prüfen
    wallet_info = rpc_call(
        WALLET_RPC_URL,
        "getwalletinfo",
        [],
        rpc_id=f"info: {wallet_name}"
    )


    #Write to DB
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
            "descriptor": metadata.get("descriptor"),
            "wallet_info": json.dumps(wallet_info, indent=2)
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