import asyncio
import os
import logging
from fastapi import APIRouter

router = APIRouter()

@router.get("/healthz")
def healthz():
    return {"ok": True}

@router.get("/health")
async def health():
    return {
        "service": "middleware",
        "status": "ok"
    }


