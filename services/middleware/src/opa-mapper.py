def to_opa_input(intent: dict) -> dict:
    return {
        "amount_sats": intent.get("amount_sats", 0),
        "target_address": intent.get("target_address", ""),
        "request_id": intent.get("intent_id", ""),
        "network": intent.get("network", "regtest"),
        "actor": "middleware",
        "reason": intent.get("reason", ""),
        "meta": intent.get("meta", {}),
        "velocity": intent.get("velocity", {}),
    }