from typing import List, Dict, Tuple
from embit.transaction import Transaction, TransactionInput, TransactionOutput
from embit.psbt import PSBT
from embit.script import Script

def build_psbt(
    inputs: List[Dict],
    outputs: List[Tuple[str, int]],
    change_script_hex: str,
    change_sats: int
) -> bytes:
    """
    Build PSBT bytes:
    - inputs: [{txid,vout,value_sats,script_pubkey_hex}, ...]
    - outputs: [(script_hex, value_sats), ...]
    - change output optional if change_sats > 0
    """

    txins = []
    for u in inputs:
        txins.append(TransactionInput(bytes.fromhex(u["txid"])[::-1], int(u["vout"])))

    txouts = []
    for script_hex, val in outputs:
        txouts.append(TransactionOutput(int(val), Script(bytes.fromhex(script_hex))))

    if change_sats > 0:
        txouts.append(TransactionOutput(int(change_sats), Script(bytes.fromhex(change_script_hex))))

    tx = Transaction(version=2, vin=txins, vout=txouts, locktime=0)
    psbt = PSBT(tx)

    # Add witness_utxo for each input
    for idx, u in enumerate(inputs):
        spk = Script(bytes.fromhex(u["script_pubkey_hex"]))
        val = int(u["value_sats"])
        psbt.inputs[idx].witness_utxo = TransactionOutput(val, spk)

    return psbt.serialize()