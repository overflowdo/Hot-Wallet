import os
import json
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")

def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

#UTXOs
#Für TX-Builder
def get_utxos(wallet_id: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT
                    txid,
                    vout,
                    wallet_id,
                    amount_sats,
                    script_pubkey,
                    confirmed,
                    block_height
                FROM btc.utxos
                WHERE wallet_id = %s
                  AND spent = false
                ORDER BY amount_sats DESC
            """, (wallet_id,))

            return cur.fetchall()
        

#Für ZMQ-listener
def insert_watchScript(script_pubkey_hex: str, wallet_id: str, input_type: str = "p2wpkh"):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.watch_script (
                    script_pubkey_hex,
                    wallet_id,
                    input_type
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (script_pubkey_hex)
                DO NOTHING
            """, (
                script_pubkey_hex,
                wallet_id,
                input_type
            ))
        c.commit()

def db_get_watchScripts():
    with conn() as c:
        with c.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        script_pubkey_hex, 
                        wallet_id
                    FROM btc.watch_script
                """)
        rows = cur.fetchall()
        return {
            r["script_pubkey_hex"]: r["wallet_id"]
            for r in rows
        }
    

def mark_utxo_spent(txid: str, vout: int, spent_txid: str, block_height=None):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE btc.utxos
                SET spent = true,
                    spent_txid = %s,
                    spent_block_height = %s
                WHERE txid = %s AND vout = %s
            """, (
                spent_txid,
                block_height,
                txid,
                vout
            ))


def insert_utxo(
    txid: str,
    vout: int,
    wallet_id: str,
    amount_sats: int,
    script_pubkey: str,
    confirmed: bool,
    block_height=None,
    block_hash=None
):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.utxos (
                    txid,
                    vout,
                    wallet_id,
                    amount_sats,
                    script_pubkey,
                    confirmed,
                    block_height,
                    block_hash
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (txid, vout)
                DO UPDATE SET
                    confirmed = EXCLUDED.confirmed,
                    block_height = EXCLUDED.block_height,
                    block_hash = EXCLUDED.block_hash
            """, (
                txid,
                vout,
                wallet_id,
                amount_sats,
                script_pubkey,
                confirmed,
                block_height,
                block_hash
            ))

#ZMQ Reorg logik
def get_block(height: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT height, hash, previous_hash
                FROM btc.blocks
                WHERE height = %s
            """, (height,))
            return cur.fetchone()


def get_tip():
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                SELECT height, hash
                FROM btc.chain_state
                WHERE network = 'regtest'
            """)
            return cur.fetchone()


def set_tip(height, hash_):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.chain_state (network, tip_height, tip_hash)
                VALUES ('regtest', %s, %s)
                ON CONFLICT (network)
                DO UPDATE SET
                    tip_height = EXCLUDED.tip_height,
                    tip_hash = EXCLUDED.tip_hash
            """, (height, hash_))

def upsert_block(height: int, hash_: str, prev_hash: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO btc.blocks (height, hash, previous_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT (height)
                DO UPDATE SET
                    hash = EXCLUDED.hash,
                    previous_hash = EXCLUDED.previous_hash
            """, (height, hash_, prev_hash))

#Undo all UTXO effects of a block.
def rollback_block(height: int):
    with conn() as c:
        with c.cursor() as cur:

            #unspend outputs that were spent in this block
            cur.execute("""
                UPDATE btc.utxos
                SET spent = false,
                    spent_txid = NULL,
                    spent_block_height = NULL
                WHERE spent_block_height = %s
            """, (height,))

            #remove utxos created in block
            cur.execute("""
                DELETE FROM btc.utxos
                WHERE block_height = %s
            """, (height,))


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
    
def update_wallet_usage(wallet_id: str, last_used_index: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE btc.wallet
                SET last_used_index = GREATEST(last_used_index, %s)
                WHERE wallet_id = %s
            """, (last_used_index, wallet_id))
        c.commit()

def fetch_all(query: str, params: tuple = ()):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()



def archive_txRecord(network: str, height: int, tip_hash: str):
    with conn() as c:
        c.commit()


#One time pro wallet
def create_wallet(
    wallet_id: str,
    wallet_type: str,
    network: str,
    xpub: str,
    derivation_path: str | None,
    master_fingerprint: str | None
):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO btc.wallet (
                    wallet_id,
                    wallet_type,
                    network,
                    xpub,
                    derivation_path,
                    master_fingerprint
                )
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (wallet_id)
                DO UPDATE SET
                    xpub = EXCLUDED.xpub,
                    derivation_path = EXCLUDED.derivation_path,
                    master_fingerprint = EXCLUDED.master_fingerprint
                """,
                (
                    wallet_id,
                    wallet_type,
                    network,
                    xpub,
                    derivation_path,
                    master_fingerprint
                )
            )

        c.commit()

def upsert_psbt_artifact():
    return


#State logging für psbts (unterscheidung zu intent möglcih, aber unnötig kompliziert)
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
                    source_address,
                    target_address,
                    meta,
                    error_code
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                psbt.get("id"),
                psbt.get("type"),
                psbt.get("state"),
                psbt.get("network", "regtest"),
                psbt.get("amount_sats"),
                psbt.get("source_address"),
                psbt.get("target_address"),
                json.dumps(psbt.get("meta", {})),
                psbt.get("error_code")
            ))
        c.commit()


#Abfrage von tx-builder
def get_spendable_utxos(wallet_id: str):
    return fetch_all("""
        SELECT
            *
        FROM btc.utxos
        WHERE 
                spent = false
            AND wallet_id = %s
    """, (wallet_id,))


#Nach jedem tx-broadcast
def update_spendable_utxos(txid: str, inputs: list, outputs: list, height: int):
    with conn() as c:
        with c.cursor() as cur:
            # 1. mark inputs as spent
            for inp in inputs:
                cur.execute("""
                    UPDATE btc.utxos
                    SET spent = true,
                        spent_by_txid = %s,
                        spent_height = %s,
                        updated_utc = now()
                    WHERE txid = %s AND vout = %s
                """, (txid, height, inp["txid"], inp["vout"]))

            # 2. insert outputs
            for idx, out in enumerate(outputs):
                cur.execute("""
                    INSERT INTO btc.utxos (
                        txid, vout, value_sats, script_pubkey_hex,
                        height, confirmed, spent
                    )
                    VALUES (%s, %s, %s, %s, %s, false, false)
                    ON CONFLICT DO NOTHING
                """, (
                    txid,
                    idx,
                    out["value"],
                    out["script"],
                    height
                ))
        c.commit()

def insert_opa_decision(
    psbt_id: str,
    policy_name: str,
    actor: str,
    allow: bool,
    reasons: list,
    input_data: dict,
    result: dict
):
    with conn() as c:
        with c.cursor() as cur:

            # 1. resolve internal psbt DB id
            db_psbt_id = get_psbt_db_id(psbt_id)
            if db_psbt_id is None:
                raise RuntimeError(f"psbt_id not found: {psbt_id}")

            # 2. insert policy decision
            cur.execute("""
                INSERT INTO btc.opa_decision (
                    psbt_id,
                    policy_name,
                    actor,
                    allow,
                    reasons,
                    input,
                    result
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                db_psbt_id,
                policy_name,
                actor,
                allow,
                reasons,
                json.dumps(input_data),
                json.dumps(result)
            ))

        c.commit()

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