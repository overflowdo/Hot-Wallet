import os
import json
import time
import uuid
import asyncio
import zmq
import nats

from bitcoin.core import CTransaction

ZMQ_ENDPOINT = os.getenv("ZMQ_ENDPOINT")
NATS_URL = os.getenv("NATS_URL")
WHITELIST_PATH = os.getenv("WHITELIST_PATH")



# LOAD WHITELIST
def load_whitelist():
    try:
        with open(WHITELIST_PATH, "r") as f:
            return set(json.load(f)["allowed_addresses"])
    except Exception as e:
        print("[warn] whitelist load failed:", e)
        return set()



# DECODE TX
def decode_tx(raw):
    tx = CTransaction.deserialize(raw)

    outputs = []
    for vout in tx.vout:
        try:
            addr = str(vout.scriptPubKey.addresses[0])
            outputs.append((addr, vout.nValue))
        except Exception:
            continue

    return outputs



# BUILD EVENT
def build_event(addr, value, txid):
    return {
        "id": str(uuid.uuid4()),
        "type": "hot-tx",
        "amount_sats": int(value),
        "target_address": addr,
        "network": "regtest",
        "meta": {
            "source": "zmq",
            "txid": txid
        }
    }



# MAIN
async def main():
    whitelist = load_whitelist()

    print("[listener] whitelist:", len(whitelist))

    # NATS connect
    nc = await nats.connect(NATS_URL)
    print("[listener] connected to NATS")

    # ZMQ connect
    ctx = zmq.Context()
    socket = ctx.socket(zmq.SUB)
    socket.connect(ZMQ_ENDPOINT)
    socket.setsockopt(zmq.SUBSCRIBE, b"")

    print("[listener] connected to ZMQ")

    while True:
        try:
            raw = socket.recv()

            outputs = decode_tx(raw)

            for addr, value in outputs:
                if addr in whitelist:

                    event = build_event(addr, value, "unknown")

                    await nc.publish(
                        "intent.created",
                        json.dumps(event).encode()
                    )

                    print("[EVENT] intent.created ->", addr, value)

        except Exception as e:
            print("[error]", e)
            time.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())