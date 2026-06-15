import httpx

async def broadcast_to_bitcoind(rawtx_hex: str, user: str, passW: str, url: str):
    payload = {
        "jsonrpc": "1.0",
        "id": "b",
        "method": "sendrawtransaction",
        "params": [rawtx_hex]
    }

    auth = (user, passW)

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(url, json=payload, auth=auth)
        r.raise_for_status()

        data = r.json()

        if data.get("error"):
            raise RuntimeError(data["error"])

        return data["result"]