import os
import asyncio
import subprocess
import json
import httpx
from embit.psbt import PSBT
from embit import bip32
from embit.script import p2wpkh

from .db import (
    get_wallet,
    insert_watchScript,
    update_wallet_usage,
    db_get_watchScripts,
    get_utxos,
    del_utxos,
    ins_utxo,
    db_rollback,
    get_wallet_ids,
    update_nextScan_index
)

SPARROW_CLI_PATH = os.getenv("SPARROW_CLI_PATH", "sparrow-cli")
WALLETS_DIR = os.getenv("WALLETS_DIR", "")



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


#Hilfsfunktion wie viele weitere wallets in die map kommen
def derive_p2wpkh(xpub: str, derivation_path: str, start: int, end: int):
    node = bip32.HDKey.from_string(xpub)

    scripts = []

    for i in range(start, end + 1):
        child = node.derive(f"0/{i}")
        pubkey = child.public_key
        script = p2wpkh(pubkey)

        scripts.append({
            "index": i,
            "script_hex": script.data.hex()
        })

    return scripts


#Finde nächsten adressen, um wallet tx nachverfolgen zukönnen
async def expand_watchScripts(wallet_id: str):
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

    scripts = derive_p2wpkh(xpub, path, start, end)

    for s in scripts:
        await asyncio.to_thread(
            insert_watchScript,
            s["script_hex"],
            wallet_id,
            s["index"],
            "p2wpkh"
        )

        #track usage index
        await asyncio.to_thread(
            update_nextScan_index,
            wallet_id,
            end + 1
        )

    return {
        "wallet_id": wallet_id,
        "expanded": len(scripts),
        "range": [start, end]
    }




#########################################################
#Sparrow
#Reorg trigger
async def ReconWallets():
    print("Starte automatischen UTXO-Abgleich nach Reorg...")
    
    #Alle watched wallets
    rows = await asyncio.to_thread(
        get_wallet_ids
    )

    wallet_ids = [
        r["wallet_id"]
        for r in rows
    ]

    for wallet_id in wallet_ids:
        wallet_file = f"/pfad/zu/deinen/wallets/{wallet_id}.wallet"
        
        # Sparrow CLI aufrufen
        cmd = ["sparrow-cli", "getutxos", "-w", wallet_file, "-f", "json"]
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, check=True
            )
            sparrow_utxos = json.loads(result.stdout)
            
            #Löschen aller UTXOs dieser Wallet in der DB
            #Nachbauen aus Sparrow-Daten auf
            await asyncio.to_thread(rebuild_walletUtxos, wallet_id, sparrow_utxos)
            print(f"[SPARROW AUDITOR] Wallet {wallet_id} erfolgreich nachgebaut.")
            
        except Exception as e:
            print(f"[SPARROW AUDITOR] Fehler beim Abgleich von {wallet_id}: {str(e)}")


def rebuild_walletUtxos(wallet_id: str, sparrow_utxos: list, db_connection):    
    try:
        #Löschen unbestätigter
        del_utxos(wallet_id)
        #Inserieren neuer

        for utxo in sparrow_utxos:
            ins_utxo(
                txid=utxo["txid"],
                vout=utxo["vout"],
                wallet_id=wallet_id,
                amount_sats=utxo["value"],
                script_pubkey=utxo["script_pubkey"],
                confirmed=True,
                block_height=utxo.get("height"),
                block_hash=None
            )

        print(f"[DB] Wallet {wallet_id} erfolgreich mit {len(sparrow_utxos)} UTXOs synchronisiert.")
        
    except Exception as e:
        db_rollback()
        print(f"[DB ERROR] Fehler beim Wiederaufbau der UTXOs: {str(e)}")
        raise e