from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal,Any
import json
import hashlib


class PaymentIntent(BaseModel):
    id: str

    type: Literal["hot-tx", "refill"]

    rail: Literal["bip21", "psbt"]

    network: str

    amount_sats: Optional[int] = None
    amount_msat: Optional[int] = None

    source_address: Optional[str] = None
    target_address: Optional[str] = None

    psbt: Optional[str] = None

    meta: Dict = {}


async def create_paymentIntent(
    *,
    intent_id: str | None = None,
    rail: str,
    network: str,
    amount_sats: int | None = None,
    target_address: str | None = None,
    meta: dict | None = None,
) -> PaymentIntent:
        

    return PaymentIntent(
        id=intent_id,
        rail=rail,
        network=network,
        amount_sats=amount_sats,
        source_address="hot",
        target_address=target_address,
        meta=meta
    )

async def create_paymentIntent_msg(
    msg,
) -> PaymentIntent:
    data = json.loads(msg)

    return await create_paymentIntent(
        intent_id=data.get("intent_id"),
        rail=data["rail"],
        network=data.get("network", "regtest"),
        amount_sats=data.get("amount_sats"),
        target_address=data.get("target_address"),
        meta=data.get("meta"),
    )



class PSBTModel(BaseModel):

    psbt_id: str
    wallet_type: str

    #Core PSBT data
    psbt: str  # base64 PSBT
    network: str = "regtest"
    source_address: str
    target_address: str

    #Fee / construction metadata
    amount_sats: int
    fee_sats: Optional[int] = None
    fee_rate: Optional[float] = None
    changepos: Optional[int] = None

    #Integrity / traceability
    sha256: Optional[str] = None


    #routing / state
    state: str

    # extensibility
    meta: dict[str, Any] = Field(default_factory=dict)
    error_code: dict[str, Any] = Field(default_factory=dict)

async def create_psbt(
    *,
    psbt_id: str | None = None,
    wallet_type: str,
    psbt: str,
    rail: str | None = None,
    network: str,
    amount_sats: int | None = None,
    fee_sats: int | None = None,
    fee_rate: int | None = None,
    changepos: int | None = None,
    target_address: str | None = None,
    source_address: str | None = None,
    sha256: str | None = None,
    state: str,
    meta: dict | None = None,
    error_code: dict | None = None,
) -> PSBTModel:

    if sha256 is None:
        sha256 = hashlib.sha256(psbt.encode()).hexdigest()

    meta = meta or {}

    if rail is not None:
        meta["rail"] = rail

    return PSBTModel(
        psbt_id=psbt_id,
        wallet_type=wallet_type,
        psbt=psbt,
        network=network,
        amount_sats=amount_sats,
        fee_sats = fee_sats,
        fee_rate = fee_rate,
        changepos = changepos,
        target_address=target_address,
        source_address=source_address,
        sha256=sha256,
        state=state,
        meta=meta,
        error_code=error_code
    )

async def create_psbt_msg(msg) -> PSBTModel:
    data = json.loads(msg)

    return await create_psbt(
        psbt_id=data.get("psbt_id"),
        wallet_type=data["wallet_type"],
        psbt=data["psbt"],
        network=data.get("network", "regtest"),
        amount_sats=data.get("amount_sats"),
        info_sats=data.get("info_sats"),
        fee_rate=data.get("fee_rate"),
        changepos=data.get("changepos"),
        target_address=data.get("target_address"),
        source_address=data.get("source_address"),
        sha256=data.get("sha256"),
        state=data["state"],
        meta=data.get("meta"),
        error_code=data.get("error_code"),
    )
