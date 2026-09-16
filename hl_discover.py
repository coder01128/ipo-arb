"""
Hyperliquid ticker discovery — finds HIP-3 and native perps.
Usage: python hl_discover.py ANTH
       python hl_discover.py          (lists all HIP-3 deployers + their perps)
"""
import requests
import sys

keyword = sys.argv[1].upper() if len(sys.argv) > 1 else None
BASE = "https://api.hyperliquid.xyz/info"
HDR = {"Content-Type": "application/json"}

print("Fetching HIP-3 deployers (perpDexs)...\n")
dexes = requests.post(BASE, json={"type": "perpDexs"}, headers=HDR, timeout=10).json()
deployers = [d for d in dexes if d is not None]
print(f"Found {len(deployers)} HIP-3 deployer(s):\n")
for d in deployers:
    print(f"  name: {d['name']:<12}  fullName: {d.get('fullName','?')}")
print()

all_hip3_coins = []
for d in deployers:
    resp = requests.post(BASE, json={"type": "meta", "dex": d["name"]}, headers=HDR, timeout=10)
    for coin in resp.json().get("universe", []):
        coin["_dex"] = d["name"]
        # The API already returns names like "io:ANTH" — use as-is
        all_hip3_coins.append(coin)

print(f"Total HIP-3 perps across all deployers: {len(all_hip3_coins)}\n")

if keyword:
    matches = [c for c in all_hip3_coins if keyword in c["name"].upper()]
    if matches:
        print(f"Matches for '{keyword}':\n")
        for c in matches:
            print(f"  coin (use this) : {c['name']}")
            print(f"  deployer        : {c['_dex']}")
            print(f"  maxLeverage     : {c.get('maxLeverage', '?')}")
            print(f"  szDecimals      : {c.get('szDecimals', '?')}")
            print()
        print(f">>> Use in monitor:  python arb_monitor.py --hl-coin {matches[-1]['name']}")
    else:
        print(f"No HIP-3 perps matching '{keyword}'. All available:\n")
        for c in all_hip3_coins:
            print(f"  {c['name']:<25}  dex={c['_dex']}")
else:
    for c in all_hip3_coins:
        print(f"  {c['name']:<25}  dex={c['_dex']}  maxLev={c.get('maxLeverage','?')}")
