import os
import httpx
import asyncio

from .db import insert_psbt, psbt_created_seen, insert_opa_decision

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")


async def evaluate_hot_intent(self, intent: dict) -> dict:
    payload = {"input": self.to_opa_input(intent)}

    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.post(
            f"{self.base}/v1/data/policy/hot/decision",
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


def to_opa_input(intent: dict) -> dict:
    return {
        "amount_sats": intent.get("amount_sats", 0),
        "target_address": intent.get("target_address", ""),
        "request_id": intent.get("id", ""),
        "network": intent.get("network", "regtest"),
        "actor": "middleware",
        "reason": intent.get("reason", ""),
        "meta": intent.get("meta", {}),
        "velocity": intent.get("velocity", {}),
    }
    

async def handle_intent(psbt: dict):

    #Deduplication of Tx because of race conditions check
    if await asyncio.to_thread(psbt_created_seen, psbt.get("id"), "INTENT_CREATED"):
        return

    if psbt.get("type") == "refill":
        psbt["source_address"] = "cold"
    elif psbt.get("type") == "hot-tx":
        psbt["source_address"] = "hot"

    await asyncio.to_thread(
        insert_psbt,{
            "id": psbt.get("id"),
            "type": psbt.get("type"),
            "state": "INTENT_CREATED",        
            "amount_sats": psbt.get("amount_sats"),
            "source_address": psbt.get("source_address"),
            "target_address": psbt.get("target_address"),
            "meta": {},
            "error_code": "-",
        }
    )

    if psbt.get("type") == "hot-tx":
        #Weiterleitung zu OPA bei hot-tx, nicht benötigt für refill (mensch)
        decision = await evaluate_hot_intent(psbt)

        allowed = decision.get("allow", False)
        reasons = decision.get("reasons", [])

        #DB logging
        await asyncio.to_thread(
            insert_opa_decision,
            psbt_id=psbt.get("id"),
            policy_name="policy.hot",
            actor="middleware",
            allow=allowed,
            reasons=reasons,
            input_data=psbt,
            result = decision
        )

        if not allowed:
            await asyncio.to_thread(
                insert_psbt, {
                    "id": psbt.get("id"),
                    "type": psbt.get("type"),
                    "state": "OPA_REJECTED",        
                    "amount_sats": psbt.get("amount_sats"),
                    "source_address": psbt.get("source_address"),
                    "target_address": psbt.get("target_address"),
                    "meta": {},
                    "error_code": psbt.get("error_code") or reasons,
                }
            )
            return

        await asyncio.to_thread(
            insert_psbt, {
                "id": psbt.get("id"),
                "type": psbt.get("type"),
                "state": "OPA_APPROVED",        
                "amount_sats": psbt.get("amount_sats"),
                "source_address": psbt.get("source_address"),
                "target_address": psbt.get("target_address"),
                "meta": {},
                "error_code": psbt.get("error_code"),
            }
        )