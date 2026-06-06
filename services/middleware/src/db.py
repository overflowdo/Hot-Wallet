import os
import json
from typing import List, Optional, Tuple, Dict, Any
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")

def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def get_chain_state(network: str) -> Tuple[int, str]:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT tip_height, tip_hash FROM btc.chain_state WHERE network=%s", (network,))
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO btc.chain_state(network, tip_height, tip_hash) VALUES(%s,0,'')", (network,))
                c.commit()
                return (0, "")
            return (row["tip_height"], row["tip_hash"])

def set_chain_state(network: str, height: int, tip_hash: str):
    with conn() as c:
        c.commit()

def upsert_psbt_artifact(psbt_id: str, artifact_type: str, artifact: dict):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.psbt_artifact (psbt_id, artifact_type, artifact)
                VALUES (%s, %s, %s)
                ON CONFLICT (psbt_id, artifact_type) DO UPDATE SET artifact = EXCLUDED.artifact
            """, (psbt_id, artifact_type, json.dumps(artifact)))
        c.commit()

def archive_txRecord(network: str, height: int, tip_hash: str):
    with conn() as c:
        c.commit()

def list_unspent(label: str, limit: int = 500) -> List[Dict[str, Any]]:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
              SELECT u.txid, u.vout, u.value_sats, u.script_pubkey_hex, w.input_type
              FROM btc.utxo u
              JOIN btc.watch_script w ON w.script_pubkey_hex=u.script_pubkey_hex
              WHERE u.spent=false AND w.label=%s
              ORDER BY u.value_sats DESC
              LIMIT %s
            """, (label, limit))
            return cur.fetchall()

def count_unspent(label: str) -> int:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
              SELECT count(*) AS n
              FROM btc.utxo u
              JOIN btc.watch_script w ON w.script_pubkey_hex=u.script_pubkey_hex
              WHERE u.spent=false AND w.label=%s
            """, (label,))
            return int(cur.fetchone()["n"])

def insert_psbt(psbt: dict):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.psbt (
                    psbt_id,
                    psbt_type,
                    psbt_state,
                    network,
                    amount_sats,
                    target_address,
                    meta
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                psbt.get("id"),
                psbt.get("type"),
                psbt.get("state"),
                psbt.get("network", "regtest"),
                psbt.get("amount_sats"),
                psbt.get("target_address"),
                json.dumps(psbt.get("meta", {}))
            ))
        c.commit()