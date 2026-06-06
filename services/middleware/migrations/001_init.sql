-- 001_init.sql
-- Schema: btc (namespaced to avoid collisions)
-- Target: PostgreSQL >= 13

BEGIN;

CREATE SCHEMA IF NOT EXISTS btc;

-- -----------------------------
-- ENUMS
-- -----------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'intent_type') THEN
    CREATE TYPE btc.intent_type AS ENUM ('hot_tx', 'refill');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'intent_state') THEN
    CREATE TYPE btc.intent_state AS ENUM ('CREATED', 'OPA_APPROVED', 'OPA_REJECTED');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'psbt_state') THEN
    CREATE TYPE btc.psbt_state AS ENUM ('PSBT_FAILED', 'PSBT_CREATED', 'UNSIGNED', 'WAITING_HUMAN', 'WAITING_RETRY', 'SIGNED', 'BROADCAST');
  END IF;
END $$;

-- -----------------------------
-- CORE: INTENTS
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.intent (
  intent_id        TEXT PRIMARY KEY,
  type             btc.intent_type NOT NULL,
  state            btc.intent_state NOT NULL DEFAULT 'CREATED',
  network          TEXT NOT NULL DEFAULT 'regtest',
  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),

  amount_sats      BIGINT,
  target_address   TEXT,
  reason           TEXT,
  meta             JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_code        TEXT
);

CREATE INDEX IF NOT EXISTS idx_intent_type_created ON btc.intent (type, created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_intent_state_updated ON btc.intent (state, updated_utc DESC);

-- Keep updated_utc in sync
CREATE OR REPLACE FUNCTION btc.set_updated_utc()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_utc = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_intent_updated ON btc.intent;
CREATE TRIGGER trg_intent_updated
BEFORE UPDATE ON btc.intent
FOR EACH ROW EXECUTE FUNCTION btc.set_updated_utc();

-- -----------------------------
-- POLICY DECISIONS (OPA)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.policy_decision (
  decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_id        TEXT REFERENCES btc.intent(intent_id) ON DELETE CASCADE,

  policy_name      TEXT NOT NULL,              -- e.g. "policy.hot" / "policy.refill"
  actor            TEXT NOT NULL,              -- e.g. "middleware" / "tx-builder" / "policy-signer"
  allow            BOOLEAN NOT NULL,
  reasons          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

  input            JSONB NOT NULL,             -- exact OPA input
  result           JSONB NOT NULL,             -- exact OPA result

  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_intent_created ON btc.policy_decision (intent_id, created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_policy_name_created ON btc.policy_decision (policy_name, created_utc DESC);

-- gen_random_uuid() needs pgcrypto
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------
-- PSBT METADATA (paths + hashes, no blobs)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.psbt_artifact (
  artifact_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_id        TEXT REFERENCES btc.intent(intent_id) ON DELETE CASCADE,
  stage            btc.psbt_stage NOT NULL,

  -- Where the file lives (USB temp paths are optional; archive path is durable)
  file_path        TEXT NOT NULL,              -- e.g. "usb:/mnt/usb/psbt/final.<id>.psbt" OR "archive:/psbt-archive/<id>/final.<id>.psbt"
  sha256           TEXT NOT NULL,
  size_bytes       BIGINT,
  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(intent_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_psbt_intent_stage ON btc.psbt_artifact (intent_id, stage);

-- -----------------------------
-- HOT SIGNING REQUESTS (Policy-Signer)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.hot_sign_request (
  request_id           TEXT PRIMARY KEY,       -- idempotency key (from middleware)
  intent_id            TEXT REFERENCES btc.intent(intent_id) ON DELETE SET NULL,

  network              TEXT NOT NULL DEFAULT 'regtest',
  state                btc.psbt_state NOT NULL DEFAULT 'WAITING_RETRY',
  created_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),

  tx_hash              TEXT NOT NULL,           -- canonical binding hash
  unsigned_rawtx_sha256 TEXT,                   -- hash of rawtx template
  signed_rawtx_sha256   TEXT,                   -- hash after signing

  txid                 TEXT,                   -- after broadcast
  error                TEXT
);

CREATE INDEX IF NOT EXISTS idx_hotreq_state_updated ON btc.hot_sign_request (state, updated_utc DESC);
CREATE INDEX IF NOT EXISTS idx_hotreq_txid ON btc.hot_sign_request (txid);

DROP TRIGGER IF EXISTS trg_hotreq_updated ON btc.hot_sign_request;
CREATE TRIGGER trg_hotreq_updated
BEFORE UPDATE ON btc.hot_sign_request
FOR EACH ROW EXECUTE FUNCTION btc.set_updated_utc();

-- -----------------------------
-- ARCHIVE INDEX (Talos PVC)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.archived_tx (
  id                   TEXT PRIMARY KEY,       -- same <id> used in filenames and archive folder
  network              TEXT NOT NULL DEFAULT 'regtest',
  source               TEXT NOT NULL DEFAULT 'manual-usb', -- or "hot-auto"
  created_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),

  txid                 TEXT NOT NULL,
  broadcast_utc         TIMESTAMPTZ NOT NULL,
  archived_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),

  archive_path          TEXT NOT NULL,          -- e.g. "psbt-archive/<id>/"
  final_psbt_path       TEXT NOT NULL,          -- e.g. "/var/lib/btc-archive/psbt-archive/<id>/final.<id>.psbt"
  final_psbt_sha256     TEXT NOT NULL,

  rawtx_hex_path        TEXT,                   -- optional: "/var/lib/.../rawtx_hex.txt"
  rawtx_sha256          TEXT,                   -- optional

  approval_json_path    TEXT,                   -- optional
  approval_sig_path     TEXT,                   -- optional

  meta                  JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_archived_tx_txid ON btc.archived_tx (txid);
CREATE INDEX IF NOT EXISTS idx_archived_tx_broadcast ON btc.archived_tx (broadcast_utc DESC);

-- -----------------------------
-- EVENT AUDIT LOG (optional but recommended)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.event_log (
  event_id             BIGSERIAL PRIMARY KEY,
  topic                TEXT NOT NULL,           -- NATS subject
  related_intent_id    TEXT,                   -- optional
  payload              JSONB NOT NULL,
  created_utc          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_event_topic_created ON btc.event_log (topic, created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_intent_created ON btc.event_log (related_intent_id, created_utc DESC);

-- -----------------------------
-- IDEMPOTENCY (HTTP + Events)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.idempotency_key (
  scope                TEXT NOT NULL,          -- e.g. "middleware:hot_tx", "policy-signer:sign"
  key                  TEXT NOT NULL,
  request_sha256       TEXT NOT NULL,
  response_json        JSONB,
  created_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_utc          TIMESTAMPTZ,

  PRIMARY KEY (scope, key)
);

CREATE INDEX IF NOT EXISTS idx_idempo_expires ON btc.idempotency_key (expires_utc);

COMMIT;