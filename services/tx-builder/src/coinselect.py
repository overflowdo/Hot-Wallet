from typing import List, Dict, Tuple

def estimate_vbytes(n_in: int, n_out: int, vin_vb: int, vout_vb: int, base_vb: int = 10) -> int:
    return base_vb + n_in * vin_vb + n_out * vout_vb

def select_utxos(utxos: List[Dict], target_sats: int) -> Tuple[List[Dict], int]:
    chosen = []
    total = 0
    for u in utxos:
        chosen.append(u)
        total += int(u["value_sats"])
        if total >= target_sats:
            return chosen, total
    return [], 0