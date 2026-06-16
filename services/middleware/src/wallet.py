from embit.psbt import PSBT
from embit import bip32
from embit.script import p2wpkh
import asyncio

from .db import (
    get_wallet,
    insert_watchScript,
    update_wallet_usage
)

def derive_p2wpkh_scripts(xpub: str, derivation_path: str, start: int, end: int):
    node = bip32.HDKey.from_string(xpub)

    scripts = []

    for i in range(start, end + 1):
        child = node.derive(f"{derivation_path}/{i}")
        pubkey = child.public_key
        script = p2wpkh(pubkey)

        scripts.append({
            "index": i,
            "script_hex": script.data.hex()
        })

    return scripts

#Entfernen? kann sparrow für cold finalizen?
def extract_rawtx_hex_from_final_psbt(psbt_bytes: bytes) -> str:
    #Extract raw tx hex from a FINALIZED PSBT using embit.
    psbt = PSBT.parse(psbt_bytes)

    # Try finalize (idempotent when already finalized)
    try:
        psbt.finalize()
    except Exception:
        pass

    # Some embit versions provide extraction helpers.
    for name in ("extract_tx", "final_tx", "extract_transaction", "finalize_tx"):
        fn = getattr(psbt, name, None)
        if callable(fn):
            tx = fn()
            if hasattr(tx, "serialize"):
                return tx.serialize().hex()
            if isinstance(tx, (bytes, bytearray)):
                return bytes(tx).hex()

    # Fallback: serialize tx object directly
    tx = getattr(psbt, "tx", None)
    if tx is not None and hasattr(tx, "serialize"):
        raw_hex = tx.serialize().hex()
        if len(raw_hex) >= 20:
            return raw_hex

    raise ValueError("cannot extract raw tx (psbt not finalized or unsupported embit version)")


async def expand_watch_scripts(wallet_id: str):
    wallet = await asyncio.to_thread(get_wallet, wallet_id)

    if not wallet:
        raise RuntimeError("wallet not found")

    xpub = wallet["xpub"]
    path = wallet["derivation_path"] or "m/84'/0'/0'"
    gap = wallet["gap_limit"] or 20
    last = wallet["last_used_index"] or 0
    next_scan = wallet["next_scan_index"] or 0

    #range
    start = next_scan
    end = last + gap

    scripts = derive_p2wpkh_scripts(xpub, path, start, end)

    for s in scripts:
        await asyncio.to_thread(
            insert_watchScript,
            s["script_hex"],
            wallet_id,
            "p2wpkh"
        )

        # optional: track usage index
        await asyncio.to_thread(
            update_wallet_usage,
            wallet_id,
            s["index"]
        )

    return {
        "wallet_id": wallet_id,
        "expanded": len(scripts),
        "range": [start, end]
    }