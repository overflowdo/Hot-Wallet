BEGIN;

CREATE SCHEMA IF NOT EXISTS btc;

-- -----------------------------
-- ENUMS
-- -----------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'psbt_type') THEN
    CREATE TYPE btc.psbt_type AS ENUM ('hot', 'cold');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'psbt_state') THEN
    CREATE TYPE btc.psbt_state AS ENUM ('INTENT_CREATED', 'PSBT_CREATED', 'PSBT_FAILED', 'OPA_APPROVED', 'OPA_REJECTED', 'WAITING_HUMAN', 'COLD_STARTED', 'COLD_STOPPED', 'WAITING_RETRY', 'SIGNING_FAILED', 'SIGNED', 'PSBT_FINALIZED', 'BROADCASTED');
  END IF;
  
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'wallet_type') THEN
    CREATE TYPE btc.wallet_type AS ENUM ('hot', 'cold', 'ext');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS btc.wallet (
    wallet_id        TEXT PRIMARY KEY,
    wallet_name        TEXT NOT NULL,
    wallet_type      btc.wallet_type NOT NULL,
    network          TEXT NOT NULL,

    xpub             TEXT,

    derivation_path  TEXT,
    master_fingerprint TEXT,

    active           BOOLEAN NOT NULL DEFAULT true,
    next_scan_index  INTEGER DEFAULT 0, 
    descriptor        TEXT NOT NULL,

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
  psbt_id           TEXT,

  policy_name      TEXT NOT NULL,              -- e.g. "policy.hot" / "policy.refill"
  actor            TEXT NOT NULL,              -- e.g. "middleware" / "tx-builder" / "policy-signer"
  allowed            BOOLEAN NOT NULL,
  reasons           JSONB NOT NULL DEFAULT '{}'::jsonb,

  input            JSONB NOT NULL DEFAULT '{}'::jsonb,             -- exact OPA input
  result           JSONB NOT NULL DEFAULT '{}'::jsonb,           -- exact OPA output

  created_utc      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- gen_random_uuid() needs pgcrypto
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------
-- ARCHIVE INDEX (keine verbindeungen zu anderen Tabellen
-- -----------------------------
CREATE TABLE IF NOT EXISTS btc.psbt_archive (
    id                 BIGSERIAL PRIMARY KEY,
    archived_utc       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- PSBT
    psbt_id            TEXT NOT NULL,
    wallet_type        TEXT NOT NULL,
    network            TEXT NOT NULL,

    signed_psbt        TEXT NOT NULL,
  
    -- Finalisierung
    raw_tx             TEXT NOT NULL,
    txid               TEXT NOT NULL,

    -- Routing
    source_address     TEXT,
    target_address     TEXT NOT NULL,

    -- Beträge
    amount_sats        BIGINT NOT NULL,
    fee_sats           BIGINT,
    fee_rate           DOUBLE PRECISION,

    sha256             TEXT,

    meta               JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMIT;