import asyncio
import logging
import os
from embit.psbt import PSBT
from embit.transaction import Transaction
from embit.script import Script
from embit.networks import NETWORKS

from .db import insert_psbt
from .models import PSBTModel


SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)

# Nach OPA senden zu Tx-builder (forwarding in middleware nc subscribe (oben))
#Nach Tx-builder, WENN FEHLSCHLUG
async def handle_psbt_failed(psbt: PSBTModel):

    log.info(
        "PSBT build failed",
        extra={
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_FAILED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code")
        }
    )

    await asyncio.to_thread(
        insert_psbt, {
            psbt
        }
    )


#Hier funktion nach Tx-builder, wenn ERFOLGREICH
async def handle_psbt_created(psbt: PSBTModel):
    
    log.info(
        "PSBT build success",
        extra={
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "PSBT_CREATED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": psbt.get("error_code")
        }
    )

    await asyncio.to_thread(
        insert_psbt, {
            psbt
        }
    )




def extr_psbtInfo(psbt_b64: str, network: str = "regtest") -> dict[str]:
    psbt = PSBT.from_string(psbt_b64)
    net = NETWORKS.get(network, NETWORKS["regtest"])

    #inputs
    input_value = sum(
        inp.witness_utxo.value
        for inp in psbt.inputs
        if inp.witness_utxo
    )

    #outputs/target_adress
    outputs = []
    output_value = 0

    for out in psbt.tx.vout:
        output_value += out.value

        try:
            addr = out.script_pubkey.address(net)
        except Exception:
            addr = None

        outputs.append({
            "address": addr,
            "value": out.value,
        })

    #fee
    fee_sats = input_value - output_value if input_value else None

    #fee rate
    vsize = getattr(psbt.tx, "vsize", None)
    fee_rate = fee_sats / vsize if fee_sats is not None and vsize else None

    #target
    target_address = outputs[0]["address"] if outputs else None

    #amount (largest output = change)
    amount_sats = None
    if outputs:
        if len(outputs) == 1:
            amount_sats = outputs[0]["value"]
        else:
            change_value = max(o["value"] for o in outputs)
            amount_sats = sum(o["value"] for o in outputs if o["value"] != change_value)

    #changepos
    changepos = None
    for i, out in enumerate(psbt.outputs):
        if getattr(out, "bip32_derivations", None):
            changepos = i
            break

    return {
        "amount_sats": amount_sats,
        "fee_sats": fee_sats,
        "fee_rate": fee_rate,
        "target_address": target_address,
        "changepos": changepos,
        "outputs": outputs,
    }