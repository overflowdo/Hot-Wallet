BEGIN;

CREATE SCHEMA IF NOT EXISTS btc;

-- -----------------------------
-- ENUMS
DO $$
BEGIN
  
END $$;


-- CHAIN STATE
CREATE TABLE IF NOT EXISTS btc.chain_state (
  network      TEXT PRIMARY KEY,
  tip_height   INTEGER NOT NULL DEFAULT 0,
  tip_hash     TEXT NOT NULL DEFAULT '',
  updated_utc  TIMESTAMPTZ NOT NULL DEFAULT now()
);


--Reorg Implementierung, block tracking
CREATE TABLE IF NOT EXISTS btc.blocks (
    height INTEGER PRIMARY KEY,
    hash TEXT NOT NULL,
    previous_hash TEXT NOT NULL
);


-- WATCHED SCRIPTS
CREATE TABLE IF NOT EXISTS btc.watch_script (
  script_pubkey_hex TEXT PRIMARY KEY,
  wallet_id         TEXT NOT NULL REFERENCES btc.wallet(wallet_id) ON DELETE CASCADE,
  label             TEXT NOT NULL DEFAULT '',
  input_type        TEXT NOT NULL DEFAULT 'p2wsh',
  created_utc       TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- UTXO set derived from chain for scripts in watch_script
CREATE TABLE IF NOT EXISTS btc.utxos (
    txid TEXT NOT NULL,
    vout INTEGER NOT NULL,

    wallet_id TEXT NOT NULL REFERENCES btc.wallet(wallet_id) ON DELETE CASCADE,

    amount_sats BIGINT NOT NULL,

    script_pubkey TEXT NOT NULL,

    confirmed BOOLEAN NOT NULL DEFAULT FALSE,

    block_height INTEGER,
    block_hash TEXT,

    spent BOOLEAN NOT NULL DEFAULT FALSE,

    spent_txid TEXT,
    spent_block_height INTEGER,

    created_at TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY(txid,vout)
);

--views
CREATE VIEW hot_utxos AS
SELECT *
FROM btc.utxos
WHERE wallet_id = 'hot';

CREATE VIEW cold_utxos AS
SELECT *
FROM btc.utxos
WHERE wallet_id = 'cold';

CREATE VIEW btc.wallet_balance AS
SELECT
    wallet_id,
    SUM(amount_sats) AS balance_sats
FROM btc.utxos
WHERE spent = false
GROUP BY wallet_id;


COMMIT;