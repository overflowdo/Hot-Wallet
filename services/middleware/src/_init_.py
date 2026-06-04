import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "")


@dataclass
class ArchivedTxRecord:
    id: str
    network: str
    source: str
    txid: str
    broadcast_utc: str  # ISO string ok; Postgres parses timestamptz
    archive_path: str
    final_psbt_path: str
    final_psbt_sha256: str
    rawtx_hex_path: Optional[str] = None
    rawtx_sha256: Optional[str] = None
    approval_json_path: Optional[str] = None
    approval_sig_path: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL)


def upsert_archived_tx(rec: ArchivedTxRecord) -> None:
    sql = """
    INSERT INTO btc.archived_tx (
      id, network, source,
      txid, broadcast_utc, archived_utc,
      archive_path, final_psbt_path, final_psbt_sha256,
      rawtx_hex_path, rawtx_sha256,
      approval_json_path, approval_sig_path,
      meta
    ) VALUES (
      %(id)s, %(network)s, %(source)s,
      %(txid)s, %(broadcast_utc)s, now(),
      %(archive_path)s, %(final_psbt_path)s, %(final_psbt_sha256)s,
      %(rawtx_hex_path)s, %(rawtx_sha256)s,
      %(approval_json_path)s, %(approval_sig_path)s,
      %(meta)s
    )
    ON CONFLICT (id) DO UPDATE SET
      txid = EXCLUDED.txid,
      broadcast_utc = EXCLUDED.broadcast_utc,
      archived_utc = now(),
      archive_path = EXCLUDED.archive_path,
      final_psbt_path = EXCLUDED.final_psbt_path,
      final_psbt_sha256 = EXCLUDED.final_psbt_sha256,
      rawtx_hex_path = EXCLUDED.rawtx_hex_path,
      rawtx_sha256 = EXCLUDED.rawtx_sha256,
      approval_json_path = EXCLUDED.approval_json_path,
      approval_sig_path = EXCLUDED.approval_sig_path,
      meta = EXCLUDED.meta;
    """

    params = {
        "id": rec.id,
        "network": rec.network,
        "source": rec.source,
        "txid": rec.txid,
        "broadcast_utc": rec.broadcast_utc,
        "archive_path": rec.archive_path,
        "final_psbt_path": rec.final_psbt_path,
        "final_psbt_sha256": rec.final_psbt_sha256,
        "rawtx_hex_path": rec.rawtx_hex_path,
        "rawtx_sha256": rec.rawtx_sha256,
        "approval_json_path": rec.approval_json_path,
        "approval_sig_path": rec.approval_sig_path,
        "meta": Jsonb(rec.meta or {}),
    }

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def upsert_psbt_artifact(intent_id: str, stage: str, file_path: str, sha256: str, size_bytes: Optional[int] = None) -> None:
    sql = """
    INSERT INTO btc.psbt_artifact (
      intent_id, stage, file_path, sha256, size_bytes
    ) VALUES (
      %(intent_id)s, %(stage)s::btc.psbt_stage, %(file_path)s, %(sha256)s, %(size_bytes)s
    )
    ON CONFLICT (intent_id, stage) DO UPDATE SET
      file_path = EXCLUDED.file_path,
      sha256 = EXCLUDED.sha256,
      size_bytes = EXCLUDED.size_bytes,
      created_utc = now();
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "intent_id": intent_id,
                "stage": stage,
                "file_path": file_path,
                "sha256": sha256,
                "size_bytes": size_bytes
            })
        conn.commit()


def update_intent_state(intent_id: str, new_state: str) -> None:
    sql = """
    UPDATE btc.intent
    SET state = %(state)s::btc.intent_state
    WHERE intent_id = %(intent_id)s;
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"intent_id": intent_id, "state": new_state})
        conn.commit()