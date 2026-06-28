import os
import requests
from decimal import Decimal

SAT = Decimal("100000000")


def btc_to_sats(v):
    return int((Decimal(str(v)) * SAT).to_integral_value())

RPC_URL = os.getenv("BTC-CORE_RPC_URL", "")
RPC_USER = os.getenv("BTC-CORE_RPC_USER", "")
RPC_PASS = os.getenv("BTC-CORE_RPC_PASS", "")


class BitcoindRPCError(RuntimeError):
    pass

def rpc_call(url, method, params=None, rpc_id="middleware"):
    payload = {
        "jsonrpc": "1.0",
        "id": rpc_id,
        "method": method,
        "params": params or []
    }

    response = requests.post(
        url,
        auth=(RPC_USER, RPC_PASS),
        json=payload,
        headers={"content-type": "text/plain;"}
    )

    # Zuerst versuchen, die JSON-Fehlermeldung von Bitcoin Core zu lesen
    try:
        result = response.json()
        if result.get("error") is not None:
            raise RuntimeError(
                f"RPC-Fehler bei '{method}': {result['error']}"
            )
        return result["result"]
    except ValueError:
        #error 500
        response.raise_for_status()
        raise

def broadcast_to_bitcoind(raw_tx_hex: str):
    return rpc_call(
        f"{RPC_URL}",
        "sendrawtransaction",
        [raw_tx_hex]
    )

def psbt_finalize(psbt_b64: str):
    final_result = rpc_call(
        RPC_URL,
        "finalizepsbt",
        [psbt_b64]
    )

    if not final_result.get("complete"):
        raise RuntimeError("PSBT konnte nicht vollständig finalisiert werden!")
    
    return final_result.get("hex")


def address_wallet_match(wallet_name: str, address: str) -> bool:
    result = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name}",
        "getaddressinfo",
        [address]
    )

    return result.get("ismine", False)

def get_walletBalance(wallet_name: str):
    result = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name}",
        "getbalances"
    )
    return result["mine"]["trusted"]




def extr_psbtInfo(psbt_b64: str, network: str = "regtest", wallet_name: str = "keyA"):

    processed = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name}",
        "walletprocesspsbt",
        [psbt_b64, True]
    )

    psbt_filled = processed["psbt"]
    fee_sats = processed.get("fee", None)

    decoded = rpc_call(
        f"{RPC_URL}/wallet/{wallet_name}",
        "decodepsbt",
        [psbt_filled]
    )

    tx = decoded.get("tx", {})
    vout = tx.get("vout", [])


    input_value_sats = 0

    for inp in decoded.get("inputs", []):
        utxo = inp.get("witness_utxo")
        if utxo:
            # Core gives BTC → convert
            input_value_sats += btc_to_sats(utxo["amount"])


    outputs = []
    output_value_sats = 0

    for i, o in enumerate(vout):
        script = o.get("scriptPubKey", {})
        addr = None

        if isinstance(script.get("address"), str):
            addr = script["address"]
        elif isinstance(script.get("addresses"), list):
            addr = script["addresses"][0]

        value_sats = btc_to_sats(o["value"])

        outputs.append({
            "address": addr,
            "value_sats": value_sats
        })

        output_value_sats += value_sats


    if fee_sats is None:
        fee_sats = input_value_sats - output_value_sats


    vsize = tx.get("vsize")
    fee_rate = (fee_sats / vsize) if fee_sats and vsize else None


    target_address = None
    amount_btc = 0

    psbt_outs = decoded.get("outputs", [])

    for i, o in enumerate(outputs):
        is_change = False

        if i < len(psbt_outs):
            if psbt_outs[i].get("bip32_derivs"):
                is_change = True

        if not is_change:
            amount_btc += o["value_sats"]
            if target_address is None:
                target_address = o["address"]
    
    amount_btc = Decimal(amount_btc)
    amount_sats = int(amount_btc * Decimal("100000000"))

    return {
        "amount_sats": amount_sats,
        "fee_sats": fee_sats,
        "fee_rate": fee_rate,
        "target_address": target_address,
        "outputs": outputs
    }