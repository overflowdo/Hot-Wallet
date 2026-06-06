import os
import httpx

OPA_URL = os.getenv("OPA_URL", "http://opa:8181/v1/data/policy/hot/allow")

async def check_hot_policy(input_data: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            OPA_URL,
            json={"input": input_data}
        )
        resp.raise_for_status()
        return resp.json()["result"]