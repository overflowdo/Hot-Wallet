import requests
import json
import os

API_URL = os.getenv("WALLET_API_URL", "http://localhost:8000/api/v1/importWallet")


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
        API_URL,
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    if r.status_code != 200:
        raise RuntimeError(f"Import failed: {r.text}")

    return r.json()


if __name__ == "__main__":
    result = import_external_wallet(
        wallet_name="wallet2",
        network="regtest",
        descriptor=""
    )

    print(json.dumps(result, indent=2))