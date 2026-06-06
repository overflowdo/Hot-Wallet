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
        with c.cursor() as cur:
            cur.execute("""
              INSERT INTO btc.chain_state(network, tip_height, tip_hash, updated_utc)
              VALUES(%s,%s,%s,now())
              ON CONFLICT(network) DO UPDATE SET tip_height=EXCLUDED.tip_height, tip_hash=EXCLUDED.tip_hash, updated_utc=now()
            """, (network, height, tip_hash))
        c.commit()

def watch_scripts() -> List[Dict[str, Any]]:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT script_pubkey_hex, label, input_type FROM btc.watch_script")
            return cur.fetchall()

def upsert_utxo(txid: str, vout: int, value_sats: int, script_hex: str, height: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
              INSERT INTO btc.utxo(txid,vout,value_sats,script_pubkey_hex,height,confirmed,spent)
              VALUES(%s,%s,%s,%s,%s,true,false)
              ON CONFLICT(txid,vout) DO UPDATE SET
                value_sats=EXCLUDED.value_sats,
                script_pubkey_hex=EXCLUDED.script_pubkey_hex,
                height=EXCLUDED.height,
                confirmed=true,
                spent=false,
                spent_by_txid=NULL,
                spent_height=NULL
            """, (txid, vout, value_sats, script_hex, height))
        c.commit()

def mark_spent(prev_txid: str, prev_vout: int, spending_txid: str, spend_height: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
              UPDATE btc.utxo
              SET spent=true, spent_by_txid=%s, spent_height=%s
              WHERE txid=%s AND vout=%s
            """, (spending_txid, spend_height, prev_txid, prev_vout))
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

def upsert_intent(intent: dict):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.intent (
                    intent_id,
                    type,
                    state,
                    network,
                    amount_sats,
                    target_address,
                    reason,
                    meta
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (intent_id)
                DO UPDATE SET
                    updated_utc = now(),
                    state = EXCLUDED.state,
                    meta = EXCLUDED.meta
            """, (
                intent.get("intent_id"),
                intent.get("type", "refill"),
                intent.get("state", "CREATED"),
                intent.get("network", "regtest"),
                intent.get("amount_sats"),
                intent.get("target_address"),
                intent.get("reason"),
                json.dumps(intent.get("meta", {}))
            ))
        c.commit()


def update_intent_state(intent_id: str, state: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE btc.intent
                SET state = %s,
                    updated_utc = now()
                WHERE intent_id = %s
            """, (state, intent_id))
        c.commit()