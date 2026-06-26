import os
import httpx
import asyncio
import logging
from uuid import uuid4 
from decimal import Decimal, ROUND_HALF_UP

from .db import insert_psbt, insert_opa_decision, psbt_id_exists, get_walletName
from .models import PSBTModel
from .api.btc_core import get_walletBalance

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
SERVICE_NAME = os.getenv("SERVICE_NAME", "middleware")
log = logging.getLogger(SERVICE_NAME)


async def send_to_opa(psbt: PSBTModel) -> dict:
    payload = {"input": parseOPA_PSBT(psbt)}

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
        
        # normalize reasons into list
        reasons_raw = (raw.get("reasons", {}))

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
    
def parseOPA_PSBT(psbt: PSBTModel) -> dict:
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
        policy_name="policy.hot.tx",
        actor="middleware",
        action=allowed,
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


async def check_walletBalance(wallet_name: str):
    balance = get_walletBalance(wallet_name)

    payload = {
        "balance": balance
    }

    log.info(
        "sending wallet balance to OPA",
        extra={"payload": payload}
    )

    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.post(
            f"{OPA_URL}/v1/data/policy/hot/limits",
            json=payload,
        )
        resp.raise_for_status()

        raw = resp.json().get("result", {})
        execution = raw.get("execution", {})

        return {
            "action": raw.get("action"),
            "balance": raw.get("balance"),
            "amount": raw.get("amount", 0),
            "target": raw.get("target", 0),
            "risk_score": raw.get("risk_score", 0),
            "reason": raw.get("reason"),

            "confirmation_blocks": execution.get("confirmation_blocks", 1),
            "broadcast_mode": execution.get("broadcast_mode" "immediate"),
            "fee_mode": execution.get("fee_mode", "normal"),
        }
    
async def handle_refillDecision(decision: dict):
    action = decision.get("action")
    amount = decision.get("amount", 0)
    execution = decision.get("execution", {})
    reason = decision.get("reason")

    log.info("OPA decision received", extra=decision)
    await asyncio.to_thread(
        insert_opa_decision,
        psbt_id="refill_check",
        policy_name="policy.hot.limits",
        actor="middleware",
        action=action,
        reasons=reason,
        input_data=decision.get("balance"),
        result = decision
    )

    amount_btc = Decimal(amount)
    amount_sats = int(amount_btc * Decimal("100000000"))


    if action == "hold":
        log.info("no fund swap required")
        return None

    intent_id = ""
    while True:
        intent_id = str(uuid4())
        exists = await asyncio.to_thread(psbt_id_exists, intent_id)
        if not exists:
            break

    if action == "hot_to_cold":
        source_address = get_walletName("hot")
        target_address = get_walletName("cold-multi")
        type = "hot-tx"
        rail = "OPA"

    elif action == "cold_to_hot":
        source_address = get_walletName("cold-multi")
        target_address = get_walletName("hot")
        type = "refill"
        rail = "OPA"
    else:
        raise ValueError(f"Unknown action: {action}")
    
    return{
        "id": intent_id,
        "type": type,
        "rail": rail,
        "network": "regtest",
        "source_address": source_address,
        "target_address": target_address,
        "amount_sats": amount_sats,
        "meta": execution
    }