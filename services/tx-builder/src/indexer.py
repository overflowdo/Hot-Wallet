from typing import Dict, Set
from . import db
from .bitcoind import get_height, get_block_hash, get_block_verbose2
from .metrics import INDEX_HEIGHT

def _script_hex_from_vout(vout: dict) -> str:
    spk = vout.get("scriptPubKey", {})
    return (spk.get("hex") or "").lower()

async def sync_chain(network: str):
    watch = db.watch_scripts()
    watch_set: Set[str] = set([w["script_pubkey_hex"].lower() for w in watch])

    tip_height, _ = db.get_chain_state(network)
    chain_height = await get_height()

    # advance one block at a time
    h = tip_height + 1
    while h <= chain_height:
        bh = await get_block_hash(h)
        blk = await get_block_verbose2(bh)

        # Mark spends first
        for tx in blk.get("tx", []):
            spending_txid = tx.get("txid")
            for vin in tx.get("vin", []):
                if "txid" in vin and "vout" in vin:
                    prev_txid = vin["txid"]
                    prev_vout = int(vin["vout"])
                    # Mark spent if it exists in our utxo table
                    db.mark_spent(prev_txid, prev_vout, spending_txid, h)

        # Add new UTXOs for watched scripts
        for tx in blk.get("tx", []):
            txid = tx.get("txid")
            for i, vout in enumerate(tx.get("vout", [])):
                script_hex = _script_hex_from_vout(vout)
                if script_hex and script_hex in watch_set:
                    value_btc = float(vout.get("value", 0.0))
                    value_sats = int(value_btc * 100_000_000)
                    db.upsert_utxo(txid, i, value_sats, script_hex, h)

        db.set_chain_state(network, h, bh)
        INDEX_HEIGHT.labels(network=network).set(h)
        h += 1