from prometheus_client import Counter, Gauge

INTENTS_TOTAL_HEIGHT = Gauge("btc_indexer_tip_height", "Indexer tip height", ["network"])
INTENTS_TOTAL = Counter("btc_intents_total", "Number of intents processed", ["type", "result"])
PSBT_BUILT_TOTAL = Counter("btc_psbt_built_total", "PSBTs built", ["result"])

UTXO_UNSPENT_GAUGE = Gauge("btc_utxo_unspent", "Unspent UTXOs in DB", ["label"])
