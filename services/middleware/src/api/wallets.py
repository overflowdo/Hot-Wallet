import asyncio
import os
import logging
import json
from fastapi import APIRouter, Body, Request, HTTPException

from src.db import create_wallet
from .btc_core import rpc_call


RPC_HOST = os.getenv("BTC-NETWORK_IP", "btc-core")
RPC_PORT = os.getenv("BTC-NETWORK_PORT", 18443)

RPC_URL = f"http://{RPC_HOST}:{RPC_PORT}"
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

nc = None
router = APIRouter()


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
    wallet_name = ""
    if metadata.get("wallet_type") == "cold":
        wallet_name = metadata.get("name") or "cormorant"
    else:
        wallet_name = metadata.get("name") or "keyA"

    wallet_id = metadata.get("wallet_id") or wallet_name or metadata["wallet_type"][:12] or metadata["xpub"][:12]


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
    
    # Externer (/0/*)
    external_desc = metadata.get("descriptor")
    # Interner Change-Descriptor (/1/*)
    internal_desc = metadata.get("descriptor").replace("/0/*", "/1/*")

    # Descriptor mit Checksum versehen
    ext_desc_info = rpc_call(
        RPC_URL,
        "getdescriptorinfo",
        [external_desc],
        rpc_id="checksum"
    )
    ext_desc = ext_desc_info["descriptor"]

    int_desc_info = rpc_call(
        RPC_URL,
        "getdescriptorinfo",
        [internal_desc],
        rpc_id=f"checksum {wallet_name}"
    )
    int_desc = int_desc_info["descriptor"]

    # Descriptor importieren
    rpc_call(
        WALLET_RPC_URL,
        "importdescriptors",
        [[
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
        ]],
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