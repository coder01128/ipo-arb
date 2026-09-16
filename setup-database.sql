-- ============================================================
-- IPO Arb Monitor — Supabase Schema
-- ============================================================
-- Source of truth for: table names, columns, types, indexes.
-- Run this in Supabase SQL Editor BEFORE starting the monitor.
--
-- Env vars the codebase expects:
--   SUPABASE_URL         (Project Settings → API → URL)
--   SUPABASE_ANON_KEY    (Project Settings → API → anon/public key)
--   SUPABASE_SERVICE_KEY  (Project Settings → API → service_role key)
-- ============================================================

-- Spread tick data — one row per sample (throttled to ~every 5s)
create table if not exists spread_ticks (
  id           bigserial    primary key,
  ts           timestamptz  default now(),
  hl_bid       numeric,
  hl_ask       numeric,
  bn_bid       numeric,
  bn_ask       numeric,
  ig_bid       numeric,
  ig_ask       numeric,
  oai_hl_bid   numeric,
  oai_hl_ask   numeric,
  oai_bn_bid   numeric,
  oai_bn_ask   numeric,
  oai_ig_bid   numeric,
  oai_ig_ask   numeric,
  best_spread  numeric,     -- best spread % across all pairs
  best_pair    text,        -- e.g. "BUY BN / SELL IG"
  alert        boolean      default false
);

-- Alert configuration — single row, editable from dashboard
create table if not exists alert_config (
  id              int          primary key default 1,
  threshold_pct   numeric      default 0.5,
  notify_enabled  boolean      default true,
  ntfy_topic      text         default 'ipo-arb-alerts',
  cooldown_mins   int          default 15,
  updated_at      timestamptz  default now()
);

-- Seed default config
insert into alert_config (id) values (1)
on conflict (id) do nothing;

-- Indexes for KPI queries
create index if not exists idx_spread_ticks_ts on spread_ticks (ts desc);
create index if not exists idx_spread_ticks_alert on spread_ticks (alert) where alert = true;

-- Enable realtime subscriptions
alter publication supabase_realtime add table spread_ticks;
alter publication supabase_realtime add table alert_config;

-- RLS — dashboard reads with anon key, monitor writes with service key
alter table spread_ticks enable row level security;
alter table alert_config enable row level security;

-- Anyone can read ticks
create policy "anon_read_ticks" on spread_ticks
  for select using (true);

-- Only service role can insert ticks
create policy "service_insert_ticks" on spread_ticks
  for insert with check (true);

-- Anyone can read config
create policy "anon_read_config" on alert_config
  for select using (true);

-- Anyone can update config (dashboard uses anon key)
create policy "anon_update_config" on alert_config
  for update using (true);

-- Retention: auto-delete ticks older than 30 days (run manually or as cron)
-- delete from spread_ticks where ts < now() - interval '30 days';
