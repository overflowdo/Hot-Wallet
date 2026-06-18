import os
import json
from fastapi import Body, FastAPI, HTTPException
import asyncio
from nats.aio.client import Client as NATS


from .opa import handle_intent
from .broadcast import broadcast_to_bitcoind
from .signer import sign_psbt
from .txBuilder import handle_psbt_created, handle_psbt_failed
from .db import (
    create_wallet,
    get_desc
)


nc = None
app = FastAPI()

BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
POLICY_SIGNER_URL = os.getenv("POLICY_SIGNER_URL", "http://policy-signer:8080")




#######################################################################
# API Endpoints (per FastAPI, wenn es kein event ist sondern direkt abfrage (anders als NATS))
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/health")
async def health():
    return {
        "service": "middleware",
        "status": "ok"
    }


#Genutzt von wgHMAC.sh
#Laden von cold und hot-wallet in die DB
#To Do ZMQ listening service für UTXO changes
@app.post("/api/v1/importWallet")
async def add_wallet(metadata: dict = Body(...)):

    required_fields = ["wallet_type", "network", "xpub"]

    missing = [f for f in required_fields if f not in metadata]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {missing}"
        )

    wallet_id = metadata.get("wallet_id") or metadata["wallet_type"][:12] or metadata["xpub"][:12]

    await asyncio.to_thread(
        create_wallet,
        wallet_id,
        metadata.get("wallet_type") or "external",
        metadata.get("network"),
        metadata.get("xpub",""),
        metadata.get("derivation_path", ""),
        metadata.get("master_fingerprint", ""),
        metadata.get("descriptor")
    )

    #Export for tx-builder
    await nc.publish(
        "newWallet.registered",
        json.dumps({"wallet_id": wallet_id, "desc": metadata["descriptor"]}).encode()
    )

    return {
        "success": True,
        "wallet_id": wallet_id,
    }
    

############################################################################
@app.on_event("startup")
async def startup():

    #NATS setup
    global nc
    nc = NATS()
    await nc.connect(servers=[os.getenv("NATS_URL")])

    
    #Init
    #Weiterleitung zu OPA
    async def intent_created_handler(msg):
        psbt = json.loads(msg.data.decode())

        if await handle_intent(psbt):
            #Nach OPA
            #desciptoren ziehen
            desc = await asyncio.to_thread(get_desc, psbt.get("source_address"))

            await nc.publish(
                "psbt.build.requested",
                json.dumps({
                    "id": psbt.get("id"),
                    "type": psbt.get("type"),
                    "network": psbt.get("network"),
                    "amount_sats": psbt.get("amount_sats"),
                    "target_address": psbt.get("target_address"),
                    "meta": psbt.get("meta", {}),
                    "descriptors": desc
                }).encode()
            )


    #Nach TX-Builder
    #Unerfolgreich    
    async def psbt_failed_handler(msg):
        data = json.loads(msg.data.decode())
        await handle_psbt_failed(data)


    #Nach TX-builder
    #Erfolgreich
    #Weiterleitung zu Signer
    async def psbt_created_handler(msg):
        psbt = json.loads(msg.data.decode())

        await handle_psbt_created(psbt)
        #refill und hot-tx müssen gesigned werden
        #Weiterleitung zum Signer
        signed = await sign_psbt(psbt)
        if signed is not None:
            if psbt.get("type") == "hot-tx":
                rawtx_hex = signed.get("rawtx_hex")

                if not rawtx_hex:
                    raise RuntimeError("Signer did not return rawtx_hex")

                #Broadcasting
                txid = await broadcast_to_bitcoind(rawtx_hex)

                # to add logging

            elif psbt.get("type") == "refill":
                #Notify Human via ntfy for start of manual proess
                return
        

    #Initial
    await nc.subscribe(
        "intent.created",
        cb=intent_created_handler
    )

    #Nach TX-Builder
    await nc.subscribe(
        "psbt.created",
        cb=psbt_created_handler
    )

    await nc.subscribe(
        "psbt.failed",
        cb=psbt_failed_handler
    )    