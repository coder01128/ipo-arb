"""IG Markets epic finder — OAuth auth working."""
import requests, json

API_KEY = "9608874347aac4b3c8997ec5a60743f2f32d294a"
USERNAME = "TheGreyHill"
PASSWORD = "Pr0pp3rJ0b"
BASE = "https://api.ig.com/gateway/deal"

# Create session
resp = requests.post(f"{BASE}/session", json={
    "identifier": USERNAME,
    "password": PASSWORD
}, headers={
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json; charset=UTF-8",
    "X-IG-API-KEY": API_KEY,
    "Version": "3"
})

body = resp.json()
token = body["oauthToken"]["access_token"]
account_id = body["accountId"]
print(f"Logged in — Account: {account_id}\n")

# Search with OAuth + account ID
search_hdrs = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json; charset=UTF-8",
    "X-IG-API-KEY": API_KEY,
    "Authorization": f"Bearer {token}",
    "IG-ACCOUNT-ID": account_id,
}

for term in ["Openai", "IPO"]:
    sr = requests.get(f"{BASE}/markets", params={"searchTerm": term}, headers=search_hdrs)
    print(f"Search '{term}': {sr.status_code}")
    if sr.status_code == 200:
        markets = sr.json().get("markets", [])
        if markets:
            for m in markets:
                print(f"\n  EPIC : {m.get('epic')}")
                print(f"  Name : {m.get('instrumentName')}")
                print(f"  Bid  : {m.get('bid')}  Offer: {m.get('offer')}")
            break
        else:
            print("  No results, trying next term...")
    else:
        print(f"  {sr.text[:300]}")
        break
