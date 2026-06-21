from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal,Any
from uuid import uuid4 
from src.db import psbt_id_exists
import asyncio


class PaymentIntent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4())) #praktisch keine Kollision mit 2^122 werden

    type: Literal["payment_intent"] = "payment_intent"

    rail: Literal["bip21", "bolt11", "psbt"]

    network: str

    amount_sats: Optional[int] = None
    amount_msat: Optional[int] = None

    source_address: Optional[str] = None
    target_address: Optional[str] = None

    invoice: Optional[str] = None
    psbt: Optional[str] = None

    meta: Dict = {}


async def create_payment_intent(
    *,
    intent_id: str | None = None,
    rail: str,
    network: str,
    amount_sats: int | None = None,
    target_address: str | None = None,
) -> PaymentIntent:
    if intent_id is None:
        while True:
            intent_id = str(uuid4())
            exists = await asyncio.to_thread(psbt_id_exists, intent_id)
            if not exists:
                break
        

    return PaymentIntent(
        id=intent_id,
        rail=rail,
        network=network,
        amount_sats=amount_sats,
        target_address=target_address,
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
    meta: Dict[str, Any] = {}
    error_code: Dict[str, Any] = {}

from typing import Union
import json

from app.models.psbtModel import PSBTModel


def normalize_psbt(msg: Union[bytes, str, dict, PSBTModel]) -> PSBTModel:

    # already psbtModel
    if isinstance(msg, PSBTModel):
        return msg


    #NATS raw bytes
    if isinstance(msg, (bytes, str)):
        data = json.loads(msg.decode() if isinstance(msg, bytes) else msg)
        return PSBTModel(**data)


    # dict input
    if isinstance(msg, dict):
        return PSBTModel(**msg)

    raise TypeError(f"Unsupported PSBT format: {type(msg)}")
    