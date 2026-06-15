import os
import httpx

OPA_URL = os.getenv("OPA_URL", "http://opa:8181/v1/data/policy/hot/decision")

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")

class OPAClient:
    def __init__(self, base_url: str = OPA_URL):
        self.base = base_url

    async def evaluate_hot_intent(self, intent: dict) -> dict:
        payload = {"input": self.to_opa_input(intent)}

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{self.base}/v1/data/policy/hot/decision",
                json=payload,
            )
            resp.raise_for_status()

            raw = resp.json().get("result", {})

            if isinstance(raw, dict):
                return {
                    "allow": raw.get("allow", False),
                    "reasons": raw.get("reasons", []),
                    "limits": raw.get("limits", {}),
                }

            return {
                "allow": bool(raw),
                "reasons": [],
                "limits": {},
            }

    @staticmethod
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