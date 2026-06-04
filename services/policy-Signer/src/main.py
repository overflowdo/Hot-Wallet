import os
from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI()

OPA_URL = os.getenv("OPA_URL", "")
HOT_SIGNING_KEY = os.getenv("HOT_SIGNING_KEY", "")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/api/v1/sign")
async def sign(req: dict):
    # expected: tx_hex + policy_context + tx_hash binding (TODO)
    tx_hex = req.get("unsigned_rawtx_hex")
    if not tx_hex:
        raise HTTPException(400, "unsigned_rawtx_hex required")

    # TODO: call OPA to verify allowed for this exact tx_hash
    # Placeholder: deny if missing key
    if not HOT_SIGNING_KEY or HOT_SIGNING_KEY == "REPLACE_ME":
        raise HTTPException(503, "signing key not configured")

    # TODO: real signing (HSM/KMS). Currently not implemented.
    raise HTTPException(501, "signing not implemented (placeholder)")