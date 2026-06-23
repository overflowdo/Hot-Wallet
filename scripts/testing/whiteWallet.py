import requests
import json
import os

BASE = "http://localhost:8080/api/v1/request/importWallet"
from pathlib import Path




def import_external_wallet(
    wallet_name: str,
    network: str,
    xpub: str = "",
    descriptor: str = "",
    derivation_path: str = "",
    master_fingerprint: str = ""
):
    payload = {
        "wallet_type": "ext",
        "name": wallet_name,
        "network": network,
        "xpub": xpub,
        "descriptor": descriptor,
        "derivation_path": derivation_path,
        "master_fingerprint": master_fingerprint
    }

    r = requests.post(
        BASE,
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    if r.status_code != 200:
        raise RuntimeError(f"Import failed: {r.text}")

    return r.json()


if __name__ == "__main__":
    file_path = Path("./data/wallet2.descriptors.json")
    with file_path.open(mode="r", encoding="utf-8") as file:
        content = file.read()
    result = import_external_wallet(
        wallet_name="wallet2",
        network="regtest",
        descriptor=content
    )

    print(json.dumps(result, indent=2))