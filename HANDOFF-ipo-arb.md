# IPO Arb Monitor — Handoff for Next Chat

## What this is

A three-leg cross-exchange arbitrage monitor for Anthropic pre-IPO perpetual futures / CFDs. Tracks real-time price differences between Hyperliquid, Binance, and IG Markets, computes directional spreads across all venue pairs, logs ticks to Supabase, displays a live dashboard on Vercel, and sends push notifications via ntfy.sh when alert conditions fire.

## Architecture

```
arb_monitor.py (runs locally on Brad's Windows PC)
  ├── Hyperliquid WebSocket  → io:ANTH (HIP-3 perp via EntropyIO)
  ├── Binance WebSocket      → ANTHROPICUSDT (USDⓈ-M futures bookTicker)
  ├── IG Markets REST poll   → IX.D.ANTHGREY.IFD.IP (OAuth, 5s interval)
  ├── Writes every 5s to     → Supabase `spread_ticks` table
  ├── Reads alert config from → Supabase `alert_config` table (every ~60 ticks)
  ├── Sends push alerts via  → ntfy.sh POST
  └── Optional local CSV log → --log flag

index.html (deployed on Vercel, vanilla HTML/JS — NOT React)
  ├── Supabase JS v2 CDN     → realtime subscription on spread_ticks
  ├── KPI queries             → direct Supabase REST reads
  └── Alert config panel      → writes to alert_config table
```

## Files (all in C:\ccode\projects\ipo-arb\)

| File | Purpose | Status |
|---|---|---|
| `arb_monitor.py` | Three-leg monitor, Supabase writer, ntfy sender | Working — streams HL + BN, IG auth working |
| `index.html` | Live dashboard | Deployed, connected to Supabase, rendering correctly |
| `setup-database.sql` | Supabase schema (spread_ticks + alert_config) | Run in Supabase SQL Editor |
| `hl_discover.py` | Hyperliquid HIP-3 ticker discovery tool | Utility, not part of main stack |
| `ig_find_epic.py` | IG Markets epic code finder | Utility, not part of main stack |

## Credentials hardcoded in arb_monitor.py

- **IG Markets**: username `TheGreyHill`, epic `IX.D.ANTHGREY.IFD.IP`, OAuth v3 with bearer token + `IG-ACCOUNT-ID: KU4EE`
- **Supabase**: passed via env vars `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (set in terminal before running, or via a run.bat)
- **Hyperliquid**: no auth needed for reads; coin passed via `--hl-coin io:ANTH`
- **Binance**: no auth needed for market data WebSocket

## Supabase schema

**spread_ticks** — one row per sample (~every 5s):
`id, ts, hl_bid, hl_ask, bn_bid, bn_ask, ig_bid, ig_ask, best_spread, best_pair, alert`

**alert_config** — single row (id=1), editable from dashboard:
`threshold_pct, notify_enabled, ntfy_topic, cooldown_mins, updated_at`

RLS: anon key can read both tables + update alert_config. Service role key (monitor) can insert ticks.

## What needs doing in next chat

### 1. Dashboard design fixes
- **Font size minimum 13px** — current build violates this in several places (11px labels, 12px table text)
- **4.5:1 contrast ratio** — current dim text (#7a7a8e on #06060b) is roughly 3.5:1, needs to come up
- Both are non-negotiable rules from Brad's build checklist

### 2. Per-pair spread display
Replace the single "Best spread" banner with three dedicated spread boxes:
- **IG ↔ Binance spread** (both directions)
- **IG ↔ Hyperliquid spread** (both directions)
- **Binance ↔ Hyperliquid spread** (both directions)

Each box shows current spread % and the better direction.

### 3. Per-pair KPIs
For each of the three venue pairs, show:
- Max spread (24h)
- Min spread (24h)
- Max spread (7d)
- Min spread (7d)

This likely means the `spread_ticks` table needs additional columns for per-pair spreads, OR compute them client-side from the raw bid/ask data. Client-side is simpler (no schema change) but heavier on the browser. Schema change is cleaner for KPI queries. Decide with Brad.

### 4. Custom alert condition builder
Brad wants conditions beyond simple threshold, e.g.:
- "If IG offer ≤ Binance bid, trigger alert"
- Other cross-venue conditional rules

He hasn't sent the full set of conditions yet — ask him for these before building. The `alert_config` table will need new columns or a JSON conditions field to store arbitrary rules. The monitor's alert logic needs to evaluate them.

### 5. Potential schema additions for per-pair spreads
If going the schema route, add columns to spread_ticks:
```sql
ig_bn_spread numeric,  -- IG ask vs BN bid (buy IG, sell BN)
bn_ig_spread numeric,  -- BN ask vs IG bid (buy BN, sell IG)
ig_hl_spread numeric,
hl_ig_spread numeric,
bn_hl_spread numeric,
hl_bn_spread numeric
```
And compute in arb_monitor.py before writing. Dashboard KPI queries then just do max/min on each column.

## Key technical notes

- **Hyperliquid HIP-3 markets** don't appear in the standard `meta` endpoint — need to pass `"dex": "io"` to the meta query. The coin name from the API is already prefixed: `io:ANTH`, not `ANTH`.
- **IG Markets auth** is OAuth v3 only (account is migrated). Session returns bearer token + refresh token in body, NOT CST headers. Token expires in 30 mins, monitor auto-refreshes at 25 mins. The `IG-ACCOUNT-ID` header must be sent with every request.
- **Supabase writes are throttled** to every 5 seconds to stay well within free tier limits (~17k rows/day, ~3-4MB/day, 500MB storage = ~5 months before needing cleanup).
- **Monitor reads alert_config every ~60 ticks** so dashboard settings changes take effect within ~5 minutes without restarting the monitor.
- **ntfy.sh** — free, no account, no API key. Brad installs the ntfy app on his phone and subscribes to the topic name. Monitor POSTs to `https://ntfy.sh/{topic}` on alert.

## Build rules that apply

- Vanilla HTML/JS only — no React/JSX unless Brad says otherwise
- 4.5:1 minimum contrast on all text
- 13px minimum font size
- Dark backgrounds: text must be off-white or strong contrast colour, never gray-on-gray
- All interactive elements need visible hover feedback
- Buttons must be unmistakably clickable (filled or bordered)
- Think once, build once — don't iterate through broken versions
- Don't build until Brad gives the go-ahead
