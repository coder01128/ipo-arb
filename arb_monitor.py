"""
Pre-IPO — Six-Leg Cross-Exchange Spread Monitor (Anthropic + OpenAI)
=====================================================================
Anthropic:
  Hyperliquid (io:ANTH)       — WebSocket l2Book
  Binance     (ANTHROPICUSDT) — WebSocket bookTicker
  IG Markets  (IX.D.ANTHGREY.IFD.IP) — REST polling (OAuth, 5s interval)

OpenAI:
  Hyperliquid (io:OPENAI)     — WebSocket l2Book
  Binance     (OPENAIUSDT)    — WebSocket bookTicker
  IG Markets  (IX.D.OPENAGREY.IFD.IP) — REST polling (same session, same cycle)

Requirements:
    pip install websockets requests

Usage:
    python arb_monitor.py --hl-coin io:ANTH --log spread_log.csv
    python arb_monitor.py --hl-coin io:ANTH --threshold 0.3
"""

import asyncio
import json
import time
import csv
import sys
import os
import requests as http_req
from datetime import datetime, timezone
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
THRESHOLD_PCT = 0.5
LOG_FILE = None
HEARTBEAT_INTERVAL = 15
RECONNECT_DELAY = 5
STALE_MS = 2000
IG_STALE_MS = 12000        # IG polls every 5s, allow more slack
IG_POLL_INTERVAL = 5       # seconds between IG price polls
IG_TOKEN_REFRESH = 1500    # refresh OAuth token every 25 mins (expires at 30)

# IG credentials
IG_USERNAME = "TheGreyHill"
IG_PASSWORD = "Pr0pp3rJ0b"
IG_API_KEY = "9608874347aac4b3c8997ec5a60743f2f32d294a"
IG_EPIC = "IX.D.ANTHGREY.IFD.IP"
IG_OAI_EPIC = "IX.D.OPENAGREY.IFD.IP"
IG_BASE = "https://api.ig.com/gateway/deal"

OAI_HL_COIN = "io:OPENAI"

# Parse CLI overrides
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--threshold" and i + 1 < len(args):
        THRESHOLD_PCT = float(args[i + 1]); i += 2
    elif args[i] == "--log" and i + 1 < len(args):
        LOG_FILE = args[i + 1]; i += 2
    else:
        i += 1

HL_COIN = "ANTH"
for _i, _a in enumerate(args):
    if _a == "--hl-coin" and _i + 1 < len(args):
        HL_COIN = args[_i + 1]

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
@dataclass
class VenueQuote:
    venue: str
    best_bid: float = 0.0
    best_ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    updated_ms: int = 0
    stale_limit: int = 2000

    @property
    def is_stale(self) -> bool:
        return (time.time() * 1000 - self.updated_ms) > self.stale_limit

    @property
    def live(self) -> bool:
        return self.best_bid > 0 and self.best_ask > 0 and not self.is_stale

    @property
    def mid(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0.0


hl_quote = VenueQuote(venue="HL", stale_limit=STALE_MS)
bn_quote = VenueQuote(venue="BN", stale_limit=STALE_MS)
ig_quote = VenueQuote(venue="IG", stale_limit=IG_STALE_MS)

venues = [hl_quote, bn_quote, ig_quote]

oai_hl_quote = VenueQuote(venue="HL", stale_limit=STALE_MS)
oai_bn_quote = VenueQuote(venue="BN", stale_limit=STALE_MS)
oai_ig_quote = VenueQuote(venue="IG", stale_limit=IG_STALE_MS)

oai_venues = [oai_hl_quote, oai_bn_quote, oai_ig_quote]

# CSV logger
csv_writer = None
csv_file = None
if LOG_FILE:
    csv_file = open(LOG_FILE, "a", newline="")
    csv_writer = csv.writer(csv_file)
    if os.path.getsize(LOG_FILE) == 0:
        csv_writer.writerow([
            "timestamp",
            "hl_bid", "hl_ask", "bn_bid", "bn_ask", "ig_bid", "ig_ask",
            "best_spread_pct", "best_pair", "alert",
            "oai_hl_bid", "oai_hl_ask", "oai_bn_bid", "oai_bn_ask",
            "oai_ig_bid", "oai_ig_ask",
        ])

# ---------------------------------------------------------------------------
# Spread computation — all pairs
# ---------------------------------------------------------------------------
def compute_and_display():
    """Check all venue pairs for arbitrage spreads."""
    live = [v for v in venues if v.live]
    if len(live) < 2:
        return

    # Compute spread for every directed pair: buy on A (ask), sell on B (bid)
    best_spread_pct = -999
    best_label = ""
    all_spreads = []

    for a in live:
        for b in live:
            if a is b:
                continue
            spread = b.best_bid - a.best_ask
            spread_pct = (spread / a.best_ask) * 100
            label = f"BUY {a.venue} / SELL {b.venue}"
            all_spreads.append((spread_pct, label))
            if spread_pct > best_spread_pct:
                best_spread_pct = spread_pct
                best_label = label

    alert = best_spread_pct >= THRESHOLD_PCT
    alert_marker = " *** ALERT ***" if alert else ""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

    # Build venue price string — show all three, dim stale ones
    parts = []
    for v in venues:
        if v.live:
            parts.append(f"{v.venue} {v.best_bid:.1f}/{v.best_ask:.1f}")
        elif v.best_bid > 0:
            parts.append(f"{v.venue} (stale)")
        else:
            parts.append(f"{v.venue} ---")

    oai_parts = []
    for v in oai_venues:
        if v.live:
            oai_parts.append(f"{v.venue} {v.best_bid:.1f}/{v.best_ask:.1f}")
        elif v.best_bid > 0:
            oai_parts.append(f"{v.venue} (stale)")
        else:
            oai_parts.append(f"{v.venue} ---")

    sys.stdout.write(
        f"\r{now}  ANTH: {'  '.join(parts)}  "
        f"Best: {best_spread_pct:+.3f}% ({best_label})"
        f"{alert_marker}  |  OAI: {'  '.join(oai_parts)}          "
    )
    sys.stdout.flush()

    if alert:
        print(
            f"\n{'='*80}\n"
            f"  ARBITRAGE SIGNAL  {now}\n"
            f"  Direction : {best_label}\n"
            f"  Spread    : {best_spread_pct:.3f}%\n"
        )
        for v in live:
            print(f"  {v.venue:2s} bid/ask: {v.best_bid:.2f} / {v.best_ask:.2f}")
        print(f"\n  All pairs:")
        for pct, lbl in sorted(all_spreads, reverse=True):
            print(f"    {pct:+.3f}%  {lbl}")
        print(f"{'='*80}")

    if csv_writer:
        csv_writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            hl_quote.best_bid, hl_quote.best_ask,
            bn_quote.best_bid, bn_quote.best_ask,
            ig_quote.best_bid, ig_quote.best_ask,
            round(best_spread_pct, 4), best_label,
            "YES" if alert else "",
            oai_hl_quote.best_bid, oai_hl_quote.best_ask,
            oai_bn_quote.best_bid, oai_bn_quote.best_ask,
            oai_ig_quote.best_bid, oai_ig_quote.best_ask,
        ])
        csv_file.flush()


# ---------------------------------------------------------------------------
# Hyperliquid WebSocket
# ---------------------------------------------------------------------------
HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

async def hyperliquid_feed():
    import websockets
    import requests as _req

    # Pre-flight check
    _hdrs = {"Content-Type": "application/json"}
    _base = "https://api.hyperliquid.xyz/info"
    try:
        _found = False
        if ":" in HL_COIN:
            _dex = HL_COIN.split(":")[0]
            _meta = _req.post(_base, json={"type": "meta", "dex": _dex},
                              headers=_hdrs, timeout=10).json()
            _coins = [c["name"] for c in _meta.get("universe", [])]
            if HL_COIN in _coins:
                _found = True
                print(f"[HL] Confirmed '{HL_COIN}' in deployer '{_dex}'")
            else:
                print(f"[HL] WARNING: '{HL_COIN}' not found. Available: {_coins[:10]}")
        else:
            _meta = _req.post(_base, json={"type": "meta"}, headers=_hdrs, timeout=10).json()
            if HL_COIN in [c["name"] for c in _meta.get("universe", [])]:
                _found = True
        if not _found:
            return
    except Exception as e:
        print(f"[HL] Pre-flight failed ({e}), proceeding...")

    async with websockets.connect(HL_WS_URL) as ws:
        await ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "l2Book", "coin": HL_COIN}
        }))
        print(f"[HL] Subscribed to {HL_COIN} l2Book")

        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    return

        hb_task = asyncio.create_task(heartbeat())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                ch = msg.get("channel", "")
                if ch in ("subscriptionResponse", "pong"):
                    continue
                if ch != "l2Book":
                    continue
                levels = msg.get("data", {}).get("levels", [])
                if len(levels) >= 2:
                    bids, asks = levels[0], levels[1]
                    if bids:
                        hl_quote.best_bid = float(bids[0]["px"])
                        hl_quote.bid_qty = float(bids[0]["sz"])
                    if asks:
                        hl_quote.best_ask = float(asks[0]["px"])
                        hl_quote.ask_qty = float(asks[0]["sz"])
                    hl_quote.updated_ms = int(time.time() * 1000)
                    compute_and_display()
        finally:
            hb_task.cancel()


# ---------------------------------------------------------------------------
# Hyperliquid WebSocket — OpenAI
# ---------------------------------------------------------------------------
async def hyperliquid_oai_feed():
    import websockets
    import requests as _req

    _hdrs = {"Content-Type": "application/json"}
    _base = "https://api.hyperliquid.xyz/info"
    try:
        _dex = OAI_HL_COIN.split(":")[0]
        _meta = _req.post(_base, json={"type": "meta", "dex": _dex},
                          headers=_hdrs, timeout=10).json()
        _coins = [c["name"] for c in _meta.get("universe", [])]
        if OAI_HL_COIN in _coins:
            print(f"[OAI-HL] Confirmed '{OAI_HL_COIN}' in deployer '{_dex}'")
        else:
            print(f"[OAI-HL] WARNING: '{OAI_HL_COIN}' not found. Available: {_coins[:10]}")
            return
    except Exception as e:
        print(f"[OAI-HL] Pre-flight failed ({e}), proceeding...")

    async with websockets.connect(HL_WS_URL) as ws:
        await ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "l2Book", "coin": OAI_HL_COIN}
        }))
        print(f"[OAI-HL] Subscribed to {OAI_HL_COIN} l2Book")

        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    return

        hb_task = asyncio.create_task(heartbeat())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                ch = msg.get("channel", "")
                if ch in ("subscriptionResponse", "pong"):
                    continue
                if ch != "l2Book":
                    continue
                levels = msg.get("data", {}).get("levels", [])
                if len(levels) >= 2:
                    bids, asks = levels[0], levels[1]
                    if bids:
                        oai_hl_quote.best_bid = float(bids[0]["px"])
                        oai_hl_quote.bid_qty = float(bids[0]["sz"])
                    if asks:
                        oai_hl_quote.best_ask = float(asks[0]["px"])
                        oai_hl_quote.ask_qty = float(asks[0]["sz"])
                    oai_hl_quote.updated_ms = int(time.time() * 1000)
                    compute_and_display()
        finally:
            hb_task.cancel()


# ---------------------------------------------------------------------------
# Binance WebSocket — Anthropic
# ---------------------------------------------------------------------------
BN_WS_URL = "wss://fstream.binance.com/public/ws/anthropicusdt@bookTicker"

async def binance_feed():
    import websockets
    async with websockets.connect(BN_WS_URL) as ws:
        print(f"[BN] Connected to ANTHROPICUSDT bookTicker")
        async for raw in ws:
            msg = json.loads(raw)
            if "b" in msg and "a" in msg:
                bn_quote.best_bid = float(msg["b"])
                bn_quote.bid_qty = float(msg["B"])
                bn_quote.best_ask = float(msg["a"])
                bn_quote.ask_qty = float(msg["A"])
                bn_quote.updated_ms = int(time.time() * 1000)
                compute_and_display()


# ---------------------------------------------------------------------------
# Binance WebSocket — OpenAI
# ---------------------------------------------------------------------------
BN_OAI_WS_URL = "wss://fstream.binance.com/public/ws/openaiusdt@bookTicker"

async def binance_oai_feed():
    import websockets
    async with websockets.connect(BN_OAI_WS_URL) as ws:
        print(f"[OAI-BN] Connected to OPENAIUSDT bookTicker")
        async for raw in ws:
            msg = json.loads(raw)
            if "b" in msg and "a" in msg:
                oai_bn_quote.best_bid = float(msg["b"])
                oai_bn_quote.bid_qty = float(msg["B"])
                oai_bn_quote.best_ask = float(msg["a"])
                oai_bn_quote.ask_qty = float(msg["A"])
                oai_bn_quote.updated_ms = int(time.time() * 1000)
                compute_and_display()


# ---------------------------------------------------------------------------
# IG Markets REST poller (OAuth)
# ---------------------------------------------------------------------------
ig_oauth = {"token": None, "account_id": None, "created": 0, "refresh_token": None}

def ig_login():
    """Create IG session, get OAuth token."""
    resp = http_req.post(f"{IG_BASE}/session", json={
        "identifier": IG_USERNAME,
        "password": IG_PASSWORD
    }, headers={
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "X-IG-API-KEY": IG_API_KEY,
        "Version": "3"
    }, timeout=15)

    if resp.status_code != 200:
        err = resp.json().get("errorCode", resp.text)
        print(f"[IG] Login failed: {err}")
        return False

    body = resp.json()
    ig_oauth["token"] = body["oauthToken"]["access_token"]
    ig_oauth["refresh_token"] = body["oauthToken"]["refresh_token"]
    ig_oauth["account_id"] = body["accountId"]
    ig_oauth["created"] = time.time()
    print(f"[IG] Logged in — Account: {body['accountId']}")
    return True


def ig_refresh():
    """Refresh the OAuth token before it expires."""
    resp = http_req.post(f"{IG_BASE}/session/refresh-token", json={
        "refresh_token": ig_oauth["refresh_token"]
    }, headers={
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "X-IG-API-KEY": IG_API_KEY,
        "Authorization": f"Bearer {ig_oauth['token']}",
        "IG-ACCOUNT-ID": ig_oauth["account_id"],
    }, timeout=15)

    if resp.status_code == 200:
        body = resp.json()
        ig_oauth["token"] = body.get("access_token", ig_oauth["token"])
        ig_oauth["refresh_token"] = body.get("refresh_token", ig_oauth["refresh_token"])
        ig_oauth["created"] = time.time()
        print(f"\n[IG] Token refreshed")
        return True
    else:
        print(f"\n[IG] Refresh failed ({resp.status_code}), re-logging in...")
        return ig_login()


def ig_get_price():
    """Fetch current bid/offer for the Anthropic epic."""
    hdrs = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "X-IG-API-KEY": IG_API_KEY,
        "Authorization": f"Bearer {ig_oauth['token']}",
        "IG-ACCOUNT-ID": ig_oauth["account_id"],
    }
    resp = http_req.get(f"{IG_BASE}/markets/{IG_EPIC}", headers=hdrs, timeout=10)
    if resp.status_code == 200:
        snap = resp.json().get("snapshot", {})
        bid = snap.get("bid")
        offer = snap.get("offer")
        if bid is not None and offer is not None:
            ig_quote.best_bid = float(bid)
            ig_quote.best_ask = float(offer)
            ig_quote.updated_ms = int(time.time() * 1000)
            return True
    elif resp.status_code == 401:
        ig_refresh()
    else:
        print(f"\n[IG] Price fetch error: {resp.status_code}")
    return False


def ig_get_oai_price():
    """Fetch current bid/offer for the OpenAI epic."""
    hdrs = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "X-IG-API-KEY": IG_API_KEY,
        "Authorization": f"Bearer {ig_oauth['token']}",
        "IG-ACCOUNT-ID": ig_oauth["account_id"],
    }
    resp = http_req.get(f"{IG_BASE}/markets/{IG_OAI_EPIC}", headers=hdrs, timeout=10)
    if resp.status_code == 200:
        snap = resp.json().get("snapshot", {})
        bid = snap.get("bid")
        offer = snap.get("offer")
        if bid is not None and offer is not None:
            oai_ig_quote.best_bid = float(bid)
            oai_ig_quote.best_ask = float(offer)
            oai_ig_quote.updated_ms = int(time.time() * 1000)
            return True
    elif resp.status_code == 401:
        pass  # auth refresh handled by the Anthropic call in the same cycle
    else:
        print(f"\n[OAI-IG] Price fetch error: {resp.status_code}")
    return False


async def ig_feed():
    """Poll IG REST API for prices (Anthropic + OpenAI)."""
    if not ig_login():
        print("[IG] Skipping IG feed — login failed")
        return

    while True:
        # Refresh token if approaching expiry
        if time.time() - ig_oauth["created"] > IG_TOKEN_REFRESH:
            ig_refresh()

        try:
            ig_get_price()
            ig_get_oai_price()
            compute_and_display()
        except Exception as e:
            print(f"\n[IG] Poll error: {e}")

        await asyncio.sleep(IG_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Reconnection wrapper
# ---------------------------------------------------------------------------
async def resilient(coro_func, label):
    while True:
        try:
            await coro_func()
        except Exception as e:
            print(f"\n[{label}] Disconnected: {e}. Reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    print(
        f"Pre-IPO Arb Monitor (6-leg: Anthropic + OpenAI)\n"
        f"  Anthropic:\n"
        f"    Hyperliquid : {HL_COIN}-USDC  (WebSocket)\n"
        f"    Binance     : ANTHROPICUSDT   (WebSocket)\n"
        f"    IG Markets  : {IG_EPIC}  (REST poll {IG_POLL_INTERVAL}s)\n"
        f"  OpenAI:\n"
        f"    Hyperliquid : {OAI_HL_COIN}-USDC  (WebSocket)\n"
        f"    Binance     : OPENAIUSDT   (WebSocket)\n"
        f"    IG Markets  : {IG_OAI_EPIC}  (REST poll {IG_POLL_INTERVAL}s)\n"
        f"  Threshold   : {THRESHOLD_PCT}%\n"
        f"  Log file    : {LOG_FILE or '(none)'}\n"
        f"{'-'*60}\n"
        f"Connecting...\n"
    )

    await asyncio.gather(
        resilient(hyperliquid_feed, "HL"),
        resilient(binance_feed, "BN"),
        resilient(ig_feed, "IG"),
        resilient(hyperliquid_oai_feed, "OAI-HL"),
        resilient(binance_oai_feed, "OAI-BN"),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
    finally:
        if csv_file:
            csv_file.close()
