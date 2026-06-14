BEGIN;

CREATE SCHEMA IF NOT EXISTS btc;

-- -----------------------------
-- ENUMS
-- -----------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'wallet_type') THEN
    CREATE TYPE btc.wallet_type AS ENUM ('hot', 'cold');
  END IF;
END $$;


-- Track chain tip per network
CREATE TABLE IF NOT EXISTS btc.chain_state (
  network      TEXT PRIMARY KEY,
  tip_height   INTEGER NOT NULL DEFAULT 0,
  tip_hash     TEXT NOT NULL DEFAULT '',
  updated_utc  TIMESTAMPTZ NOT NULL DEFAULT now()
);



-- Scripts / addresses we care about (watch-only filter)
-- Store scriptPubKey as hex; easiest to match from decoded tx outputs
CREATE TABLE IF NOT EXISTS btc.watch_script (
  script_pubkey_hex TEXT PRIMARY KEY,
  wallet_id         TEXT NOT NULL REFERENCES btc.wallet(wallet_id) ON DELETE CASCADE,
  label             TEXT NOT NULL DEFAULT 'cold',
  input_type        TEXT NOT NULL DEFAULT 'p2wsh',  -- p2wpkh|p2wsh|p2tr (for fee estimate)
  created_utc       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- UTXO set derived from chain for scripts in watch_script
CREATE TABLE IF NOT EXISTS btc.utxo (
  txid              TEXT NOT NULL,
  wallet_id         TEXT NOT NULL REFERENCES btc.wallet(wallet_id) ON DELETE CASCADE,
  vout              INTEGER NOT NULL,
  value_sats        BIGINT NOT NULL,
  script_pubkey_hex TEXT NOT NULL REFERENCES btc.watch_script(script_pubkey_hex) ON DELETE RESTRICT,

  height            INTEGER NOT NULL,              -- block height where created
  confirmed         BOOLEAN NOT NULL DEFAULT true,

  spent             BOOLEAN NOT NULL DEFAULT false,
  spent_by_txid     TEXT,
  spent_height      INTEGER,

  created_utc       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_utc       TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (txid, vout)
);

CREATE INDEX IF NOT EXISTS idx_utxo_unspent ON btc.utxo (spent) WHERE spent = false;
CREATE INDEX IF NOT EXISTS idx_utxo_script_unspent ON btc.utxo (script_pubkey_hex, spent) WHERE spent = false;
CREATE INDEX IF NOT EXISTS idx_utxo_created_height ON btc.utxo (height);

-- Update trigger
CREATE OR REPLACE FUNCTION btc.set_updated_utc()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_utc = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_utxo_updated ON btc.utxo;
CREATE TRIGGER trg_utxo_updated
BEFORE UPDATE ON btc.utxo
FOR EACH ROW EXECUTE FUNCTION btc.set_updated_utc();

--View
CREATE VIEW btc.wallet_balance AS
SELECT
    wallet_id,
    SUM(value_sats) AS balance_sats
FROM btc.utxo
WHERE spent = false
GROUP BY wallet_id;


COMMIT;