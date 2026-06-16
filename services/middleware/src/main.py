import os
import json
from fastapi import Body, FastAPI, HTTPException
import asyncio
from nats.aio.client import Client as NATS


from .opa import handle_intent
from .broadcast import broadcast_to_bitcoind
from .signer import sign_psbt
from .txBuilder import handle_psbt_created, handle_psbt_failed
from .wallet import derive_p2wpkh_scripts, expand_watch_scripts
from .db import (
    create_wallet,
    mark_utxo_spent,
    db_get_watchScripts,
    get_utxos,
    db_get_watchScripts,
    insert_utxo,
    rollback_block,
    set_tip,
    get_tip,
    get_block,
    upsert_block,
    update_wallet_usage
)


nc = None
app = FastAPI()

BITCOIND_RPC_URL = os.getenv("BITCOIND_RPC_URL", "")
BITCOIND_RPC_USER = os.getenv("BITCOIND_RPC_USER", "")
BITCOIND_RPC_PASS = os.getenv("BITCOIND_RPC_PASS", "")

ARCHIVE_ROOT = os.getenv("ARCHIVE_ROOT", "/var/lib/btc-archive/psbt-archive")
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
        metadata["network"],
        metadata["xpub"],
        metadata.get("derivation_path", ""),
        metadata.get("master_fingerprint", "")
    )

    #WatcScript mit dynamic gap/limit
    await expand_watch_scripts(wallet_id)

    #reload trigger für zmq
    await nc.publish(
        "btc.control.reload_watchmap",
        json.dumps({"wallet_id": wallet_id}).encode()
    )

    return {
        "success": True,
        "wallet_id": wallet_id,
    }
    

########################################
#utxo
#genutzt von tx-builder
@app.get("/api/v1/utxo/spendable")
async def get_utxos(wallet_id: str):
    rows = await asyncio.to_thread(
        get_utxos,
        wallet_id
    )

    # optional: filter + normalize for tx-builder
    utxos = [
        {
            "txid": r["txid"],
            "vout": r["vout"],
            "amount_sats": r["amount_sats"],
            "script_pubkey": r["script_pubkey"],
            "confirmed": r["confirmed"]
        }
        for r in rows
        if not r.get("spent", False)
    ]

    return {
        "wallet_id": wallet_id,
        "utxos": utxos
    }


#genutzt von ZMQ-listener
@app.get("/api/v1/watch-scripts")
async def get_watchScripts(wallet_id: str):
    rows = await asyncio.to_thread(
        db_get_watchScripts
    )

    return {
        "watch_scripts": {
            r["script_pubkey_hex"]: r["wallet_id"]
            for r in rows
        }
    }


@app.get("/api/v1/block/height")
async def get_height():
    r = await asyncio.to_thread(get_tip)
    return {
        "height": r["height"],
        "hash": r["hash"]
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
            
            await nc.publish(
                "psbt.build.requested",
                json.dumps({
                    "id": psbt.get("id"),
                    "type": psbt.get("type"),
                    "network": psbt.get("network"),
                    "amount_sats": psbt.get("amount_sats"),
                    "target_address": psbt.get("target_address"),
                    "meta": psbt.get("meta", {})
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
        signed = await sign_psbt()

        if psbt.get("state") == "hot-tx":
            rawtx_hex = signed.get("rawtx_hex")

            if not rawtx_hex:
                raise RuntimeError("Signer did not return rawtx_hex")

            #Broadcasting
            txid = await broadcast_to_bitcoind(rawtx_hex)

            # to add logging

        elif psbt.set("state") == "refill":
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


    #Dauerhaft UTXO listening durch ZMQ-listener
    def handle_utxo_created(msg: dict):
        wallet_id = msg["wallet_id"]
        script = msg["script_pubkey"]
        insert_utxo(
            txid=msg["txid"],
            vout=msg["vout"],
            wallet_id=msg["wallet_id"],
            amount_sats=msg["amount_sats"],
            script_pubkey=msg["script_pubkey"],
            confirmed=msg.get("confirmed", False),
            block_height=msg.get("block_height"),
            block_hash=msg.get("block_hash")
        )

        update_wallet_usage(wallet_id, msg.get("index", 0))

        expand_watch_scripts(wallet_id)

    def handle_utxo_spent(msg: dict):
        mark_utxo_spent(
            txid=msg["txid"],
            vout=msg["vout"],
            spent_txid=msg["spent_by"],
            block_height=msg.get("block_height")
        )

    def handle_block_connected(msg):
        data = json.loads(msg.data.decode())

        height = data.get("height")
        hash_ = data.get("hash")
        prev = data.get("previous_hash")

        tip = get_tip()

        # A: normal extension
        if tip and height == tip["height"] + 1:
            upsert_block(height, hash_, prev)
            set_tip(height, hash_)
            return


        #B: REORG DETECTED
        print("[REORG DETECTED]")

        # find fork point
        fork_height = tip["height"]

        while fork_height > 0:
            b = get_block(fork_height)

            if not b:
                fork_height -= 1
                continue

            # naive check: break where hashes differ
            if b["hash"] == prev:
                break

            rollback_block(fork_height)
            fork_height -= 1

        # move tip back
        set_tip(fork_height, prev)

    def handle_block_disconnected(msg):
        data = json.loads(msg.data.decode())
        height = data["height"]

        print("[BLOCK DISCONNECTED]", height)

        rollback_block(height)

        

    await nc.subscribe(
        "btc.utxo.created",
        cb=handle_utxo_created
    )

    await nc.subscribe(
        "btc.utxo.spent",
        cb=handle_utxo_spent
    )

    await nc.subscribe(
        "btc.block.connected",
        cb=handle_block_connected
    )

    await nc.subscribe(
        "btc.block.disconnected",
        cb=handle_block_disconnected
    )

    await nc.subscribe(
        "btc.wallet.expand.requested",
        cb=lambda msg: asyncio.create_task(
            expand_watch_scripts(json.loads(msg.data.decode())["wallet_id"])
        )
    )

    