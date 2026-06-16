import os
import json
import asyncio
import logging
import zmq
import zmq.asyncio
import httpx
import nats

from embit.transaction import Transaction
from embit.block import Block


# ENV
ZMQ_ENDPOINT = os.getenv("ZMQ_ENDPOINT", "tcp://bitcoind:28332")
RPC_URL = os.getenv("RPC_URL", "http://bitcoind:18443")
RPC_USER = os.getenv("RPC_USER")
RPC_PASSWORD = os.getenv("RPC_PASSWORD")

MIDDLEWARE_URL = os.getenv("MIDDLEWARE_URL", "http://middleware:8080")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

NETWORK = os.getenv("BITCOIN_NETWORK", "regtest")

log = logging.getLogger("btc-indexer")


#HTTP CLIENT
http = httpx.AsyncClient(timeout=10.0)

# NATS
nc = None
async def publish(subject: str, msg: dict):
    global nc
    if nc:
        await nc.publish(subject, json.dumps(msg).encode())

WATCH_MAP = {}

# WATCH CACHE
async def load_watch_map():
    r = await http.get(f"{MIDDLEWARE_URL}/api/v1/watch-scripts")
    global WATCH_MAP

    r.raise_for_status()
    data = r.json()

    WATCH_MAP = data["watch_map"]


async def fetch_height():
    r = await http.get(f"{MIDDLEWARE_URL}/api/v1/block/height")
    r.raise_for_status()
    return r.json()["height"]


#TX processor (MEMPOOL)
async def process_tx(tx: Transaction):
    txid = tx.txid.hex()

    # inputs → spent
    for vin in tx.vin:
        if vin.prevout is None:
            continue

        await publish("btc.utxo.spent", {
            "txid": vin.prevout.hash.hex(),
            "vout": vin.prevout.n,
            "spent_by": txid,
            "network": NETWORK
        })

    # outputs → created
    for i, vout in enumerate(tx.vout):
        script_hex = vout.script_pubkey.serialize().hex()

        wallet_id = WATCH_MAP.get(script_hex)
        if not wallet_id:
            continue

        await publish("btc.utxo.created", {
            "txid": txid,
            "vout": i,
            "wallet_id": wallet_id,
            "amount_sats": int(vout.value),
            "script_pubkey": script_hex,
            "confirmed": False,
            "network": NETWORK
        })



#block processor
async def process_block(block: Block):
    block_hash = block.hash().hex()

    height = await fetch_height()
    
    for tx in block.vtx:
        txid = tx.txid.hex()

        # spent inputs
        for vin in tx.vin:
            if vin.prevout is None:
                continue

            await publish("btc.utxo.spent", {
                "txid": vin.prevout.hash.hex(),
                "vout": vin.prevout.n,
                "spent_by": txid,
                "block_hash": block_hash,
                "block_height": height,
                "network": NETWORK
            })

        # outputs
        for i, vout in enumerate(tx.vout):
            script_hex = vout.script_pubkey.data.hex()

            wallet_id = WATCH_MAP.get(script_hex)
            if not wallet_id:
                continue

            await publish("btc.utxo.created", {
                "txid": txid,
                "vout": i,
                "wallet_id": wallet_id,
                "amount_sats": int(vout.value),
                "script_pubkey": script_hex,
                "confirmed": True,
                "block_hash": block_hash,
                "block_height": height,
                "network": NETWORK
            })

    await publish("btc.block.connected", {
        "hash": block_hash,
        "height": height,
        "network": NETWORK
    })



#ZMQ loop
async def zmq_loop():
    ctx = zmq.asyncio.Context()
    sock = ctx.socket(zmq.SUB)

    sock.connect(ZMQ_ENDPOINT)

    sock.setsockopt(zmq.SUBSCRIBE, b"rawtx")
    sock.setsockopt(zmq.SUBSCRIBE, b"rawblock")

    log.info("ZMQ connected")

    while True:
        topic, data = await sock.recv_multipart()

        try:
            if topic == b"rawtx":
                tx = Transaction.parse(data)
                await process_tx(tx)

            elif topic == b"rawblock":
                block = Block.parse(data)
                await process_block(block)

        except Exception as e:
            log.error("processing error: %s", str(e))


#nats subscribe control panel
async def control_loop():
    async def handler(msg):
        subject = msg.subject
        data = json.loads(msg.data.decode())

        log.info("control event: %s", subject)

        if subject == "btc.control.reload_watchmap":
            await load_watch_map()
            log.info("watchmap reloaded")

    await nc.subscribe("btc.control.*", cb=handler)


async def main():
    global nc

    logging.basicConfig(level=logging.INFO)

    # NATS connect
    nc = await nats.connect(NATS_URL)
    log.info("NATS connected")

    # load initial state
    await load_watch_map()

    # optional control plane
    await control_loop()

    # run indexer
    await zmq_loop()


if __name__ == "__main__":
    asyncio.run(main())