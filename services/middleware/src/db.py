import os
import json
import psycopg
from psycopg.rows import dict_row

from .models import PSBTModel, isModel

DATABASE_URL = os.getenv("DATABASE_URL", "")

def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


#Wenn error auftritt, dass die DB zurückgerollt werden kann
def rollback():
    with conn() as c:
        c.rollback()

   


#wallet
def get_wallet(wallet_id: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT wallet_id, xpub, derivation_path, gap_limit, last_used_index, next_scan_index
                FROM btc.wallet
                WHERE wallet_id = %s
            """, (wallet_id,))
            return cur.fetchone()

    

def get_wallet_ids():
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT wallet_id
                FROM btc.wallet
            """)
            return cur.fetchall()
       


def fetch_all(query: str, params: tuple = ()):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
        
def get_walletName(type: str) -> str:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT wallet_name
                FROM btc.wallet
                WHERE wallet_type = %s
                AND active = TRUE
            """, (type,))
            return [row["wallet_name"] for row in cur.fetchall()]

#One time pro wallet
def create_wallet(
    wallet_id: str,
    wallet_name: str,
    wallet_type: str,
    network: str,
    xpub: str | None,
    derivation_path: str | None,
    master_fingerprint: str | None,
    descriptor: str
):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO btc.wallet (
                    wallet_id,
                    wallet_name,
                    wallet_type,
                    network,
                    xpub,
                    derivation_path,
                    master_fingerprint,
                    descriptor
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (wallet_id)
                DO UPDATE SET
                    xpub = EXCLUDED.xpub,
                    derivation_path = EXCLUDED.derivation_path,
                    master_fingerprint = EXCLUDED.master_fingerprint
                """,
                (
                    wallet_id,
                    wallet_name,
                    wallet_type,
                    network,
                    xpub,
                    derivation_path,
                    master_fingerprint,
                    descriptor
                )
            )

        c.commit()

def archive_psbt(data: dict):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.psbt_archive (
                    psbt_id,
                    wallet_type,
                    network,
                    signed_psbt,
                    raw_tx,
                    txid,
                    source_address,
                    target_address,
                    amount_sats,
                    fee_sats,
                    fee_rate,
                    sha256,
                    meta
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s
                )
            """, (
                data.get("psbt_id"),
                data.get("wallet_type"),
                data.get("network", "regtest"),
                data.get("psbt"),
                data.get("final_tx"),
                data.get("txid"),
                data.get("source_address"),
                data.get("target_address"),
                data.get("amount_sats"),
                data.get("fee_sats"),
                data.get("fee_rate"),
                data.get("sha256"),
                json.dumps(data.get("meta", {}))
            ))
        c.commit()

#State logging für psbts (unterscheidung zu intent möglcih, aber unnötig kompliziert)
def insert_psbt(psbt: PSBTModel):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.psbt (
                    psbt_id,
                    psbt_type,
                    psbt_state,
                    network,
                    amount_sats,
                    source_address,
                    target_address,
                    meta,
                    error_code
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                psbt.psbt_id,
                psbt.wallet_type,
                psbt.state,
                psbt.network,
                psbt.amount_sats,
                psbt.source_address,
                psbt.target_address,
                json.dumps(psbt.meta),
                json.dumps(psbt.error_code)
            ))
        c.commit()

def psbt_id_exists(psbt_id: str) -> bool:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM btc.psbt
                WHERE psbt_id = %s
                LIMIT 1
            """, (psbt_id,))
            
            return cur.fetchone() is not None



def insert_opa_decision(
    psbt_id: str,
    policy_name: str,
    actor: str,
    action: bool,
    reasons: list,
    input_data: str,
    result: dict
):
    with conn() as c:
        with c.cursor() as cur:

            # 1. resolve internal psbt DB id
            if psbt_id != "refill_check":
                db_psbt_id = get_psbt_db_id(psbt_id)
                if db_psbt_id is None:
                    raise RuntimeError(f"psbt_id not found: {psbt_id}")
            else: db_psbt_id = psbt_id

            reasons = normalize(result)
            input_data = normalize(input_data)
            result = normalize(result)

            # 2. insert policy decision
            cur.execute("""
                INSERT INTO btc.opa_decision (
                    psbt_id,
                    policy_name,
                    actor,
                    allowed,
                    reasons,
                    input,
                    result
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                db_psbt_id,
                policy_name,
                actor,
                action,
                json.dumps(reasons),
                input_data,
                result
            ))

        c.commit()

def normalize(value):
    if isModel(value):
        return value.model_dump_json()
    elif isinstance(value, (dict, list)):
        return json.dumps(value)
    else:
        return str(value)

#Hilfsfunktion psbt_id zu letzter id (unique) für referenzen auflösen
def get_psbt_db_id(psbt_id: str) -> int | None:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT id
                FROM btc.psbt
                WHERE psbt_id = %s
                ORDER BY id DESC
                LIMIT 1
            """, (psbt_id,))
            row = cur.fetchone()
            return row["id"] if row else None
        c.commit()
        

#Deduplication check, ob es psbt schon gab
def psbt_created_seen(psbt_id: str, state: str = "INTENT_CREATED") -> bool:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM btc.psbt
                WHERE psbt_id = %s
                  AND psbt_state = %s
                LIMIT 1
            """, (psbt_id, state))
            return cur.fetchone() is not None