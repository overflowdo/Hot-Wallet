class ArchivedTxRecord:
    pass

async def upsert_archived_tx(*args, **kwargs):
    return None

async def upsert_psbt_artifact(*args, **kwargs):
    return None

def update_intent_state(intent_id: str, state: str, meta: dict = None):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE btc.intent
                SET state = %s,
                    updated_utc = now(),
                    meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb
                WHERE intent_id = %s
            """, (state, json.dumps(meta or {}), intent_id))
        c.commit()