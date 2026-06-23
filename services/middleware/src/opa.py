import os
import httpx
import asyncio
import logging

from .db import insert_psbt, insert_opa_decision
from .models import PSBTModel

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)


async def send_to_opa(psbt: PSBTModel) -> dict:
    payload = {"input": to_opa_input(psbt)}

    log.info(
        "sending to OPA",
        extra={
            "payload": payload
        }
    )

    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.post(
            f"{OPA_URL}/v1/data/policy/hot/decision",
            json=payload,
        )
        resp.raise_for_status()

        raw = resp.json().get("result", {})

        reasons_raw = raw.get("reasons", {})
        
        # normalize reasons into list
        if isinstance(reasons_raw, dict):
            reasons = [k for k, v in reasons_raw.items() if v]
        elif isinstance(reasons_raw, list):
            reasons = reasons_raw
        else:
            reasons = []

        return {
            "allow": raw.get("allow", False),
            "reasons": reasons,
            "limits": raw.get("limits", {}),
        }


def to_opa_input(psbt: PSBTModel) -> dict:
    return {
        "psbt_id": psbt.psbt_id,
        "wallet_type": psbt.wallet_type,
        "psbt": psbt.psbt,
        "network": psbt.network,
        "target_address": psbt.target_address,
        "source_address": psbt.target_address,

        "amount_sats": psbt.amount_sats,
        "fee_sats": psbt.fee_sats,
        "fee_rate": psbt.fee_rate,
    }
    

async def opa_evaluate(psbt: PSBTModel) -> bool:

    #Weiterleitung zu OPA bei hot-tx, nicht benötigt für refill (mensch)
    decision = await send_to_opa(psbt)

    allowed = decision.get("allow", False)
    reasons = decision.get("reasons", [])

    #DB logging
    await asyncio.to_thread(
        insert_opa_decision,
        psbt_id=psbt.psbt_id,
        policy_name="policy.hot",
        actor="middleware",
        allow=allowed,
        reasons=reasons,
        input_data=psbt,
        result = decision
    )

    psbt.state = "OPA_REJECTED"
    psbt.error_code = psbt.error_code or reasons

    if not allowed:
        await asyncio.to_thread(
            insert_psbt, psbt
        )

        log.info(
            "not permitted",
            extra={
                "payload": psbt
            }
        )
        return False

    psbt.state = "OPA_APPROVED"
    await asyncio.to_thread(
        insert_psbt, psbt
    )
    log.info(
        "Permitted",
        extra={
            "payload": psbt
        }
    )
    return True