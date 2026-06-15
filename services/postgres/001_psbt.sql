-- Schema: btc
-- Target: PostgreSQL >= 13

BEGIN;

CREATE SCHEMA IF NOT EXISTS btc;

-- -----------------------------
-- ENUMS
-- -----------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'psbt_type') THEN
    CREATE TYPE btc.psbt_type AS ENUM ('hot-tx', 'refill');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'psbt_state') THEN
    CREATE TYPE btc.psbt_state AS ENUM ('INTENT_CREATED', 'OPA_APPROVED', 'OPA_REJECTED', 'PSBT_FAILED', 'PSBT_CREATED', 'UNSIGNED', 'WAITING_HUMAN', 'WAITING_RETRY', 'SIGNING_FAILED', 'SIGNED', 'BROADCAST');
  END IF;
  
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'wallet_type') THEN
    CREATE TYPE btc.wallet_type AS ENUM ('hot', 'cold');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS btc.wallet (
    wallet_id        TEXT PRIMARY KEY,
    wallet_type      btc.wallet_type NOT NULL,
    network          TEXT NOT NULL,

    xpub             TEXT NOT NULL,

    derivation_path  TEXT,
    master_fingerprint TEXT,

    active           BOOLEAN NOT NULL DEFAULT true,

    created_utc      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- -----------------------------
-- PSBT
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.psbt (
  id               bigserial PRIMARY KEY,
  psbt_id          TEXT NOT NULL,
  psbt_type        btc.psbt_type NOT NULL,
  psbt_state       btc.psbt_state NOT NULL DEFAULT 'INTENT_CREATED',
  network          TEXT NOT NULL DEFAULT 'regtest',
  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),

  amount_sats      BIGINT,
  source_address   TEXT REFERENCES btc.wallet(wallet_id) ON DELETE CASCADE,
  target_address   TEXT,
  meta             JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_code        TEXT
);

CREATE INDEX IF NOT EXISTS idx_psbt_type_created ON btc.psbt (psbt_type, created_utc DESC);
CREATE INDEX idx_psbt_psbt_id_created ON btc.psbt (psbt_id, created_utc DESC);



-- -----------------------------
-- POLICY DECISIONS (OPA)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.opa_decision (
  decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  psbt_id           BIGINT REFERENCES btc.psbt(id) ON DELETE CASCADE,

  policy_name      TEXT NOT NULL,              -- e.g. "policy.hot" / "policy.refill"
  actor            TEXT NOT NULL,              -- e.g. "middleware" / "tx-builder" / "policy-signer"
  allow            BOOLEAN NOT NULL,
  reasons          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

  input            JSONB NOT NULL,             -- exact OPA input
  result           JSONB NOT NULL,             -- exact OPA output

  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- gen_random_uuid() needs pgcrypto
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------
-- PSBT METADATA (paths + hashes, no blobs)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.psbt_artifact (
  artifact_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  psbt_id        BIGINT REFERENCES btc.psbt(id) ON DELETE CASCADE,

  -- Where the file lives (USB temp paths are optional; archive path is durable)
  file_path        TEXT NOT NULL,              -- e.g. "usb:/mnt/usb/psbt/final.<id>.psbt" OR "archive:/psbt-archive/<id>/final.<id>.psbt"
  sha256           TEXT NOT NULL,
  size_bytes       BIGINT,
  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(psbt_id)
);

-- -----------------------------
-- HOT SIGNING REQUESTS (zu NixOs bei HTTP)
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.hot_sign_request (
  request_id           TEXT PRIMARY KEY,       -- idempotency key (from middleware)
  psbt_id            BIGINT REFERENCES btc.psbt(id) ON DELETE SET NULL,

  network              TEXT NOT NULL DEFAULT 'regtest',
  state                btc.psbt_state NOT NULL DEFAULT 'WAITING_RETRY',
  created_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),

  tx_hash              TEXT NOT NULL,           -- canonical binding hash
  unsigned_rawtx_sha256 TEXT,                   -- hash of rawtx template
  signed_rawtx_sha256   TEXT,                   -- hash after signing

  txid                 TEXT,                   -- after broadcast
  error                TEXT
);

CREATE INDEX IF NOT EXISTS idx_hotreq_txid ON btc.hot_sign_request (txid);

-- -----------------------------
-- ARCHIVE INDEX (nicht refreshen, anderen psbt_tables können mit details resetted werden)
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

COMMIT;