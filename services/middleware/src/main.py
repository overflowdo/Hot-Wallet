import os
import json
from fastapi import FastAPI
import asyncio
from nats.aio.client import Client as NATS
import logging


from .opa import opa_evaluate
from .api.btc_core import broadcast_to_bitcoind
from .signer import sign_psbt
from .txBuilder import handle_psbt_created, handle_psbt_failed
from .logging_setup import setup_logging
from .models import create_psbt, create_psbt_msg, create_paymentIntent_msg
from src.api import payments, wallets, health 
from .db import archive_psbt, psbt_created_seen, insert_psbt



BITCOIN_NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")
POLICY_SIGNER_URL = os.getenv("POLICY_SIGNER_URL", "http://policy-signer:8080")

SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

nc = None


#API dateien /api
app = FastAPI()

app.include_router(payments.router)
app.include_router(wallets.router)
app.include_router(health.router)
    

############################################################################
@app.on_event("startup")
async def startup():

    #NATS setup
    global nc
    nc = NATS()
    await nc.connect(servers=[os.getenv("NATS_URL")])
    #In API state packen
    app.state.nc = nc

    setup_logging(SERVICE_NAME)

    
    #Init
    #Weiterleitung zu TX-builder
    async def intent_created_handler(msg):
        intent = await create_paymentIntent_msg(msg.data.decode())

        rail = intent.rail
        log.info(f"intent received: {intent.id} rail={rail}")

        #Deduplication of Tx (only when id send by vendor. wenn selsbtvergeben immer unique)
        if await asyncio.to_thread(psbt_created_seen, intent.id, "INTENT_CREATED"):
            log.info(f"Already seen: {intent.id} rail={rail}")
            return
            

        if rail == "bip21":
            psbt = await create_psbt(
                psbt_id=intent.id,
                wallet_type="hot",
                psbt="",                                    #nach tx-builder
                network=intent.network,
                source_address="keyA",
                target_address=intent.target_address,
                amount_sats=intent.amount_sats,
                fee_sats=None,
                fee_rate=None,
                changepos=None,
                state="INTENT_CREATED",
                meta={
                    "rail": rail,
                },
                error_code={}
            )

            await asyncio.to_thread(
                insert_psbt, psbt
            )

            await nc.publish(
                "psbt.build.requested",
                intent.model_dump_json().encode()
            )
        
        elif rail == "manual":
            print("help")

        elif rail == "refill":
            print("help")

        else:
            log.error(f"unknown rail: {rail}")


    #Nach TX-Builder
    #Unerfolgreich    
    async def psbt_failed_handler(msg):
        data = json.loads(msg.data.decode())
        #Inkludiert nur logging
        await handle_psbt_failed(data)


    #Nach TX-builder
    #Erfolgreich
    #Weiterleitung zu Signer
    async def psbt_created_handler(msg):
        psbt = await create_psbt_msg(msg.data.decode())

        #Inkludiert nur logging
        await handle_psbt_created(psbt)

        if await opa_evaluate(psbt):
            #refill und hot-tx müssen gesigned werden
            #Weiterleitung zum Signer
            signed = await sign_psbt(psbt)
            if signed is not None:
                if psbt.wallet_type == "hot":
                    rawtx_hex = signed.get("rawtx_hex")

                    if not rawtx_hex:
                        raise RuntimeError("Signer did not return rawtx_hex")

                    #Broadcasting
                    txid = await broadcast_to_bitcoind(rawtx_hex)

                    # to add logging
                    await asyncio.to_thread(
                        archive_psbt, {
                            psbt
                        }
                    )
                    log.info("Broadcast completed")

                elif psbt.wallet_type == "cold":
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

@app.on_event("shutdown")
async def shutdown():
    global nc
    if nc:
        await nc.drain()

    log.info(SERVICE_NAME)