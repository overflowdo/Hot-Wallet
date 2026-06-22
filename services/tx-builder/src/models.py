from pydantic import BaseModel
from typing import Optional, Dict, Literal, Any
from typing import Union
import json


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
    