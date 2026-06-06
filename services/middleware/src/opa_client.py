import os
import httpx

OPA_URL = os.getenv("OPA_URL", "http://opa:8181")

class OPAClient:
    def __init__(self):
        self.base = OPA_URL

    async def evaluate_hot_intent(self, intent: dict) -> dict:
        payload = {
            "input": intent
        }

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{self.base}/v1/data/policy/hot/allow",
                json=payload
            )
            resp.raise_for_status()
            return resp.json()