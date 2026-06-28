import os
import json
from fastapi import FastAPI
import asyncio
from nats.aio.client import Client as NATS
import logging


from .opa import opa_evaluate, check_walletBalance, handle_refillDecision
from .api.btc_core import broadcast_to_bitcoind, psbt_finalize
from .signer import sign_psbt, save_psbt
from .txBuilder import handle_psbt_created, handle_psbt_failed, whitelist_check
from .logging_setup import setup_logging
from .models import create_psbt, create_psbt_msg, create_paymentIntent_msg
from src.api import payments, wallets, health, psbt
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
app.include_router(psbt.router)
    

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
        intent = await create_paymentIntent_msg(json.loads(msg.data.decode()))

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
                rail=intent.rail,
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
            if await whitelist_check(psbt.target_address, psbt.rail):
                #refill und hot-tx müssen gesigned werden
                #Weiterleitung zum Signer
                signed = await sign_psbt(psbt)
                
                if signed is not None:

                    psbt_signed = signed.get("psbt")

                    if not psbt_signed:
                        await asyncio.to_thread(
                                insert_psbt, psbt
                            )
                        
                        psbt.state = "SIGNING_FAILED"
                        await asyncio.to_thread(
                            insert_psbt, psbt
                        )
                        log.info("Signing failed")

                        raise RuntimeError("Signer did not return a signed PSBT.")
                    
                    psbt.state = "SIGNED"
                    psbt.psbt = psbt_signed
                    await asyncio.to_thread(
                        insert_psbt, psbt
                    )
                    log.info("PSBT signed successfully.")
                    
                    if psbt.wallet_type == "hot":
                        #Finalisierung
                        try:

                            rawtx_hex = psbt_finalize(psbt_signed)

                            psbt.state = "PSBT_FINALIZED"
                            await asyncio.to_thread(
                                insert_psbt, psbt
                            )
                            log.info("PSBT finalized successfully.")

                        except Exception as e:
                            log.exception("Failed to finalize PSBT.")
                            raise RuntimeError(f"PSBT finalization failed: {e}") from e

                        #Broadcast
                        try:
                            txid = broadcast_to_bitcoind(rawtx_hex)

                            if not txid:
                                raise RuntimeError("Bitcoind returned no transaction id.")
                            
                            psbt.state = "BROADCASTED"
                            await asyncio.to_thread(
                                insert_psbt, psbt
                            )
                            log.info("Transaction broadcasted successfully. txid=%s", txid)

                        except Exception as e:
                            log.exception("Broadcast failed.")
                            raise RuntimeError(f"Broadcast failed: {e}") from e

                        #Archíving
                        await asyncio.to_thread(
                            archive_psbt, {
                                **psbt.model_dump(),
                                "final_tx": rawtx_hex,
                                "txid": txid
                            }
                        )
                        log.info("Broadcast completed")

                        decision = await check_walletBalance(psbt.source_address)
                        psbt_input = await handle_refillDecision(decision)
                        
                        
                        if psbt_input is not None:
                            intent = await create_paymentIntent_msg(psbt_input)
                            await nc.publish(
                                "psbt.build.requested",
                                intent.model_dump_json().encode()
                            )
                            

                    elif psbt.wallet_type == "cold":
                        psbt.state = "WAITING_HUMAN"
                        await asyncio.to_thread(
                            insert_psbt, psbt
                        )

                        await asyncio.to_thread(save_psbt, psbt.psbt)

                        log.info("Warten auf Operanten für cold-worflow")
                        #Ntfy informieren

            else:
                #Ntfy about malicious request
                return
        else:
            return
            #add retry queue log/Ntfy human?
        

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