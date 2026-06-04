#!/usr/bin/env python3
import sys

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

addr = sys.argv[1].strip()
net = (sys.argv[2].strip() if len(sys.argv) >= 3 else "regtest").lower()

try:
    from embit import networks
except Exception as e:
    die(f"embit import failed: {e}")

# pick network params
if net in ("regtest", "bcrt"):
    N = networks.NETWORKS["regtest"]
elif net in ("testnet", "tb"):
    N = networks.NETWORKS["test"]
elif net in ("mainnet", "bc"):
    N = networks.NETWORKS["main"]
else:
    die(f"unknown network: {net}")

script = None
err = None

# try common embit APIs (version dependent)
try:
    from embit.script import Script
    if hasattr(Script, "from_address"):
        script = Script.from_address(addr, network=N)
except Exception as e:
    err = e

if script is None:
    try:
        from embit import addresses
        if hasattr(addresses, "address_to_scriptpubkey"):
            script = addresses.address_to_scriptpubkey(addr, network=N)
        elif hasattr(addresses, "to_scriptpubkey"):
            script = addresses.to_scriptpubkey(addr, network=N)
    except Exception as e:
        err = e

if script is None:
    die(f"could not derive scriptPubKey from address (embit API mismatch?) last_error={err}")

# script may be Script or bytes
if hasattr(script, "data"):
    spk = script.data
elif isinstance(script, (bytes, bytearray)):
    spk = bytes(script)
else:
    # last fallback
    try:
        spk = bytes(script)
    except Exception:
        die("unexpected script type")

print(spk.hex())
print(f"ERROR: {msg}", file=sys.stderr)
sys.exit(1)
