import json
import uuid
import asyncio
from datetime import datetime, timezone

from nats.aio.client import Client as NATS


NATS_URL = "nats://localhost:4222"
SUBJECT = "intent.created"


def create_intent():
    return {
        "intent_id": str(uuid.uuid4()),
        "type": "refill",
        "amount_sats": 10000,
        "target_address": "bcrt1qexampledestinationaddress000000000000000000",
        "network": "regtest",
        "reason": "ops",
        "meta": {"tag": "auto-test"},
        "created_utc": datetime.now(timezone.utc).isoformat()
    }


async def main():
    nc = NATS()
    await nc.connect(servers=[NATS_URL])

    intent = create_intent()

    print("PUBLISHING:")
    print(json.dumps(intent, indent=2))

    await nc.publish(
        SUBJECT,
        json.dumps(intent).encode()
    )

    await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())