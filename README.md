# GAMMA-R

Educational **cross-platform** momentum stock scanner + paper trader.

> **Not financial advice. Not a live brokerage product by default.**  
> Paper trading is the active path. Live brokerage adapters exist but are **DISABLED** until you explicitly enable them.

## What this is

- **Backend (Python):** whole-market scan over **liquid large caps in the US, Canada, UK, and Eurozone** (`universe=combined`), risk-sized signals, backtests, paper portfolio, watchlist, rule-based learning, historical walk-forward training, forward-estimate / ensemble gates, regime filters, news sentiment, timezone-aware sessions.
- **Mobile (Expo / React Native):** dark UI with Scan, Paper portfolio, Watchlist, Learning, **E-ve** (voice), Settings (Install QR + locked Live Trading).

True “all stocks worldwide” is rate-limit heavy on free Yahoo data; **S&P 500 ∪ Nasdaq-100 ∪ S&P/TSX 60 ∪ FTSE 100 ∪ EURO STOXX 50** is the practical multi-region broad scan (not every listed name).

---

## Day-one SEED defaults (learning starts here — never from zeros)

| Param | Seed |
|------|------|
| Momentum ranking | **Classic 12–1** — `momentum_lookback_days=252`, `momentum_skip_days=21` |
| `lookback_days` | **10** (short-term / volume context + 12–1 fallback) |
| Volume | **1.5×** the **20-day** average |
| Momentum cut | **top 10%** (`top_pct=0.10`) of filtered gainers |
| `stop_loss_pct` | **5%** |
| `take_profit_pct` | **15%** |
| Sector weights | **Equal** (1.0) |
| Fees | **ON** — $0.005/share + 0.1% slippage (entry & exit) |
| Session gate | **ON** — `use_per_ticker_sessions=true`, `session_gate_entries=true` (home market must be open for NEW entries) |
| Policy firewall | **ON** — deterministic pre-submit checks; live still needs `LIVE_TRADING_ENABLED=1` |

**Reset to defaults** restores this SEED baseline (not blank/zero).

### Config merge order on startup

1. Day-one **SEED**  
2. `data/historical_baseline.json` if present (“historical baseline”)  
3. `data/learned_config.json` if present (live paper learning overlay)

---

## Study upgrades (sessions / 12–1 / firewall)

1. **Multi-exchange session gates** — Universe spans US, Canada (`.TO`), UK (`.L`), Europe (`.DE`/`.PA`/`.AS`/…). NEW entries respect each ticker’s **home** session (`timezone_util.exchange_for_ticker` → NYSE/TSX/LSE/Xetra/Euronext…). Exits and risk management still run when the home market is closed. Knobs: `use_per_ticker_sessions` (default true), `session_gate_entries` (default true), plus legacy `only_act_during_open`.
2. **Classic 12–1 momentum** — Strategy id `momentum` ranks by ~12-month return excluding the most recent month (`momentum_lookback_days=252`, `momentum_skip_days=21`), with scaled / short-history fallbacks. Router may still pick other strategies.
3. **Hard non-LLM policy firewall** — `momentum_bot/policy_firewall.py` runs before every paper or live submit (API, auto-loops, E-ve assistant `paper_this_order`). Checks mode/live flag, allow/deny lists, max notional / pct equity, daily & cycle order caps, circuit breaker, optional human-approval threshold. Fail closed; audit log at `data/policy_firewall_audit.jsonl`. Status: `GET /firewall/status`.

Smoke: `python scripts/smoke_session_firewall_momentum.py`


## World-class controls

Paper-first overlays on top of the multi-strategy router, E-ve assistant, session gates, 12–1 momentum, and policy firewall:

1. **Crash / regime-shock mode** — Detects sharp SPY/QQQ short-window drops/rebounds + vol spikes (`crash_mode.py`). When active: auto-cuts **momentum** + **breakout** size (or pauses new entries); prefers mean-reversion / defensive; **exits still allowed**. Knobs: `crash_mode_enabled`, `crash_lookback`, `crash_threshold_pct`, `crash_vol_mult`, `crash_cooldown_days`, `crash_size_mult`. Status: `GET /crash-mode` (also on `GET /auto/status` + Dashboard/Settings: “Crash mode: ON until …”).
2. **Walk-forward scoreboard** — Per-strategy paper journal metrics (trades, win rate, expectancy, max DD, profit factor, Sharpe-ish / simple return) with rolling **OOS proxy** labeling (`GET /strategies/scoreboard`). Mobile Learning shows ranked **keep / watch / cut**. Optional router down-weight when `scoreboard_router_downweight` and `scoreboard_min_trades` met (default on with min trades).
3. **Decision audit trail** — Append-only `data/decision_audit.jsonl` for each auto/E-ve/API decision (regime, crash_mode, router, signals, strategy_id, firewall allow/deny, order id or skip, session gate). `GET /audit/decisions?limit=` · Learning → Recent decisions · E-ve tool `get_recent_decisions`.
4. **E-ve propose → one-tap paper** — `paper_this_order` always through policy firewall (+ session/crash gates); replies cite `strategy_id` + firewall/session; UI surfaces deny reason.

Smoke: `python scripts/smoke_world_class_controls.py`

Live remains locked unless `LIVE_TRADING_ENABLED=1` is already set by the owner.


## Backend setup

```bash
cd /workspace/momentum-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### CLI

```bash
python -m momentum_bot scan
python -m momentum_bot backtest --years 2
python -m momentum_bot serve --host 0.0.0.0 --port 8000
python -m momentum_bot historical-train --years 20   # default MAX=20; also 5|10|15
python -m momentum_bot learn
python -m momentum_bot learn --reset
```

### API (FastAPI)

- `GET /health` · `GET/PUT /config` · `GET /regime` · `GET /session`
- `POST /scan` · `GET /signals` (includes `scan_status`) · `GET /signals/{ticker}`
- `POST /backtest`
- Paper: `GET /portfolio` · `POST /portfolio/orders` · `POST /portfolio/close/{id}` · `GET /portfolio/performance` · `POST /portfolio/mode` · `POST /portfolio/reset`
- Watchlist: `GET/PUT/POST/DELETE /watchlist`
- Learning: `GET /learning/stats` · `GET /learning/history` · `GET /learning/baseline` · `POST /learning/run` · `POST /learning/reset`
- External trades (learn from brokerage outside this app): `POST /trades/import` · `POST /trades/import/alpaca` · `GET /trades/external` · `GET /trades/learning-stats`
- Historical: `POST /learning/historical-train` `{ "years": 20 }` · `GET /learning/historical-baseline`
- News: `GET /news` · `GET /news/impact` · `GET /news/eod` · `GET /news/{ticker}` (also `GET /news?eod=1`)
- Currency / FX (informational): `GET /currency` (alias `/fx`) · `GET /currency/{pair}` — toggle `use_currency_panel` (default true)
- Data source: `GET /data-source/status` · `PUT /data-source` · `GET /data-source/events` · `POST /data-source/reset-fallback`
- Strategies: `GET /strategies` · `GET /strategies/{id}`
- E-ve: `POST /copilot` (alias `POST /chat`)


### E-ve (co-pilot) v2

- Richer tools: crash mode, scoreboard (keep/watch/cut), paper report, decision audit, strategy packs (preview vs confirm-apply), scan status, per-ticker session, firewall status, **external trades**.
- Local offline answers for crash / scoreboard / packs / firewall / external WR; refuses hard buy/sell advice.
- Structured `proposals[]` cards (symbol, strategy_id, thesis, risks, size_hint) — Paper (firewall) one-tap; never auto-live.
- **External fills:** `POST /trades/import` (CSV/JSON), optional Alpaca history; `origin=external` in journal for learning/scoreboard; paper equity stays separate; deduped; never places live from import.
- Mobile Learning: paste CSV → dry-run → import. E-ve shows crash badge, scoreboard snippet, tools used, proposal cards.
- Smoke: `python scripts/smoke_copilot_v2.py`

### E-ve upgrade (tool use + memory)

- With `OPENAI_API_KEY` (or `LLM_API_KEY`): multi-step tools instead of a static JSON dump — `get_regime`, `get_session`, `get_top_signals`, `get_signal`, `get_portfolio_paper`, `get_watchlist`, `get_news_eod` / `get_news_ticker`, `get_currency`, `get_strategy_plan` (strategies.router), `get_recent_performance`, `get_external_learning_stats`, `get_config_summary`, `get_memory` / `remember_fact`.
- Response adds optional `tools_used`, `memory_updated`, `strategy_plan` (backward compatible).
- Offline local brain still answers strategy/regime/FX/news; prefs like “prefer tech” / “no biotech” round-trip via memory.
- Smoke: `python scripts/smoke_copilot.py`


### E-ve allowlisted web (controlled internet)

Not open browsing. When `copilot_web_enabled` is true (default), E-ve may call:

- `web_search_finance(query)` — multi-fetch **allowlisted** finance/macro outlets only
- `web_fetch_url(url)` — fetch+extract text **only** if the URL host is allowlisted
- `learn_from_web(topic)` — distill short notes into `data/web_learning.jsonl` (dated, sourced URLs, tags)
- `get_web_learning(topic?)` — offline recall (“what did you learn about X”)

**Default allowlist:** reuters.com, bloomberg.com, cnbc.com, marketwatch.com, ft.com, wsj.com (paywalls handled softly), federalreserve.gov, sec.gov, investing.com, yahoo.com / finance.yahoo.com, bbc.com / bbc.co.uk. Optional `coindesk.com` only when `copilot_web_crypto_enabled=1` (prefer equity/macro).

**Hard blocks:** `file://`, localhost / private IPs, arbitrary IP literals, link shorteners, non-allowlisted domains. Timeouts, size caps, rate limits, no credentials in requests, HTML→text only (no code execution), secret redaction. Fetches lightly audited to `data/web_audit.jsonl` (+ decision audit breadcrumb).

**Disable:** set `copilot_web_enabled=0` in Settings/runtime config, or `export COPILOT_WEB_ENABLED=0`. Override hosts with `COPILOT_WEB_ALLOWLIST=reuters.com,sec.gov,...`.

Still refuses hard buy/sell advice; web context is educational. Paper-first; existing tools/firewall unchanged.

Smoke: `python scripts/smoke_copilot_web.py`

- Owner (optional `OWNER_SHARED_SECRET`): `GET /owner/status` · `GET /owner/files` · `GET /owner/export/{name}` · `PUT /owner/import/{name}`
- Broker (off by default — needs `LIVE_TRADING_ENABLED=1`): `GET /broker/status` · `GET /broker/balance` · `GET /broker/positions` · `POST /broker/orders` · `POST /broker/kill`
- Push stub: `POST /notify/register`

---

## How to run (API + mobile) — private owner install

**1. API (paper-first, open on LAN by default)**

```bash
cd /workspace/momentum-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m momentum_bot serve --host 127.0.0.1 --port 8000   # loopback default
# LAN: --host 0.0.0.0 (auto-requires owner secret; prefer Tailscale)
export OWNER_SHARED_SECRET='your-secret'   # or let hardened mode auto-create data/.owner_secret
# export GAMMA_R_HARDENED=1
```

- No login/JWT. `GET /health` · `GET /owner/status` · import/export under `/owner/export|import/{name}`.
- Live trading stays **OFF** until `LIVE_TRADING_ENABLED=1`.

**2. Mobile (Expo)**

```bash
cd mobile
npm install
npx expo start
# iOS Simulator: npm run ios
```

- Default API: `http://localhost:8000` (Simulator). Physical iPhone → Settings → **API server** = your LAN IP.
- API URL + optional owner secret are remembered on-device (SecureStore).
- **E-ve:** `POST /copilot` local answers offline; optional `OPENAI_API_KEY` enables a **tool-calling** loop (regime, signals, paper portfolio, watchlist, EOD/ticker news, FX, strategy router plan, learning, redacted config, memory, **allowlisted web** for macro/earnings). Light prefs in `data/copilot_memory.json`; web notes in `data/web_learning.jsonl`. Flags: `copilot_tools_enabled`, `copilot_memory_enabled`, `copilot_max_tool_rounds` (default 4), `copilot_web_enabled` (default true; set `0` / `COPILOT_WEB_ENABLED=0` to disable). Always refuses buy/sell advice. Voice STT needs EAS/iOS build; TTS works in Expo Go.


## Security (private trading OS — honest hardening)

This is **not** SOC2 / bank-grade multi-tenant SaaS. It is a **private single-owner** paper-first trading OS with practical hardening:

| Control | Behavior |
|--------|----------|
| Owner secret | `OWNER_SHARED_SECRET` or `API_SHARED_SECRET`, else `data/.owner_secret` (0600, auto-created when hardened) |
| Hardened mode | Non-loopback bind **or** `GAMMA_R_HARDENED=1` **or** `REQUIRE_API_SECRET=1` → secret required for all non-`/health` routes |
| Auth headers | **Only** `X-Owner-Secret` or `Authorization: Bearer …` — `?owner_secret=` is **rejected** (400) to avoid URL/log leaks |
| Compare | `hmac.compare_digest` |
| `/docs` | Locked in hardened mode (and when env flags set at process start) |
| `/health` | Public probe: `status`, `auth`, `hardened`, `live_trading_enabled` (no inventory / secrets) |
| CORS | Allowlist via `CORS_ALLOW_ORIGINS` (alias `CORS_ORIGINS`) (comma-separated). **Never** `*` with credentials. Defaults cover localhost + Expo |
| Rate limit | In-memory per-IP on mutating methods + `/copilot` → **429** (`API_RATE_LIMIT`, `API_RATE_WINDOW_SEC`) |
| Redaction | Secrets stripped from errors, access logs, E-ve context, owner exports |
| Mobile | Owner secret in **SecureStore**; header only; Settings warns on non-localhost without secret |
| Live | Still fail-closed: `LIVE_TRADING_ENABLED=1` **and** firewall **and** (when hardened) owner secret |

### Exact env vars

```bash
# Recommended private LAN / Tailscale
export OWNER_SHARED_SECRET='long-random-string'   # or API_SHARED_SECRET
# Force secret even on 127.0.0.1:
export GAMMA_R_HARDENED=1          # alias: REQUIRE_API_SECRET=1
# Bind (serve also sets GAMMA_R_BIND_HOST)
python -m momentum_bot serve --host 127.0.0.1 --port 8000   # default host is loopback
# LAN phone access (auto-requires secret):
python -m momentum_bot serve --host 0.0.0.0 --port 8000
# Optional CORS / rate limit
export CORS_ALLOW_ORIGINS='http://localhost:8081,http://127.0.0.1:8081'
export API_RATE_LIMIT=60
export API_RATE_WINDOW_SEC=60
# Live remains OFF unless you explicitly unlock (firewall must stay on):
# export LIVE_TRADING_ENABLED=1
```

**Public internet:** put a TLS reverse proxy in front, keep the owner secret, prefer **localhost or Tailscale** over raw `0.0.0.0`.

Smoke: `python scripts/smoke_security.py`


### iPhone standalone (private TestFlight / sideload)

→ **[`mobile/IOS_INSTALL.md`](mobile/IOS_INSTALL.md)**  
Bundle ID `com.momentumbot.app`, EAS profiles `preview` / `production` (iOS-focused).  
Do not enroll Apple Developer from this environment — you enroll yourself, then `eas build --platform ios --profile preview`.

### Quick install page / Expo Go

See [`mobile/INSTALL.md`](mobile/INSTALL.md) and [`mobile/web/install.html`](mobile/web/install.html).  
Settings → **Install on your iPhone** shows a QR. `npm run install-page` serves it on :3333.

### Voice permissions (iOS)

`NSMicrophoneUsageDescription` + `NSSpeechRecognitionUsageDescription` in `app.json` (plus `expo-speech-recognition` plugin).

---

## Whole-market universe

`universe.py` loads public Wikipedia index lists and normalizes symbols for yfinance (class-share dots → hyphens; regional exchange suffixes).

| Region | Source | yfinance form | Approx. size |
|--------|--------|---------------|--------------|
| US | S&P 500 ∪ Nasdaq-100 | `AAPL`, `BRK-B` | ~500–530 unique |
| Canada | S&P/TSX 60 | `RY.TO`, `TECK-B.TO` | ~60 |
| UK / England | FTSE 100 | `AZN.L`, `BT-A.L` | ~100 |
| Europe (Eurozone) | EURO STOXX 50 | `ADS.DE`, `AIR.PA`, `ASML.AS` | ~50 |

**Default `universe=combined` (also `all`)** = US + Canada + UK + Europe (~700–800 liquid large caps after de-dupe). Optional modes: `sp500`, `nasdaq100`, `tsx60`, `ftse100`, `europe` / `eurostoxx50`, `international` (non-US only).

If a regional Wikipedia fetch fails, that region is skipped with a warning — other regions still load (a bad Canada fetch will not wipe the US list). `max_download` defaults to **900** so combined is not truncated early.

**Limitations:** free Yahoo/yfinance rate limits still apply; session calendars (`market_exchange`) remain mostly US-centric with LSE/TSE/HKEX hour stubs; this is **not** every stock in the world.

---

## Paper trading + watchlist

- Paper portfolio persists to `data/paper_portfolio.json`.
- Mobile **Paper** tab shows equity, total P&L / return %, unrealized vs realized (net), and fees.
- Execute from signal detail → `POST /portfolio/orders`.
- Watchlist tickers are scored with `source: "watchlist"` and can surface outside the market top-10% cut.
- Mode toggle paper/live: **live is a stub** unless brokerage is enabled (below).

---

## Transaction costs (fees + slippage)

Realistic drag is **ON by default** for paper trading and backtests. Costs are deducted on **both entry and exit** so round-trip impact is visible in P&L.

| Setting | Default | Notes |
|---------|---------|--------|
| `fees_enabled` | **true** | Toggle in Settings / `PUT /config` |
| `commission_mode` | `per_share` | Or `flat` |
| `commission_per_share` | **$0.005** | Used when mode=`per_share` |
| `commission_flat` | **$1.00** | Used when mode=`flat` |
| `slippage_pct` | **0.001** (0.1%) | Fraction of trade notional (market impact) |

**How it is applied**

- Entry: cash -= shares×price + commission + slippage  
- Exit: cash += shares×price − commission − slippage; `realized_pnl` is **net** of both legs  
- Backtests (`POST /backtest`) and historical walk-forward use the same model  
- Learning / Performance shows **total fees paid**, fees as % of gross profit, and **gross vs net return**

**Tune**

```bash
# Example: flat $1/trade, 5 bps slippage
curl -X PUT http://localhost:8000/config -H 'Content-Type: application/json' \
  -d '{"commission_mode":"flat","commission_flat":1.0,"slippage_pct":0.0005}'

# Disable for a frictionless educational run
curl -X PUT http://localhost:8000/config -H 'Content-Type: application/json' \
  -d '{"fees_enabled":false}'
```

Or use **Settings → Transaction costs** in the mobile app. Module: `momentum_bot/fees.py`.

---

## How the learning loop works

1. Closed paper trades are journaled to `data/trade_journal.json` with the signal params used at entry.  
2. After N closes (default 10) or `POST /learning/run`, rule-based adjustments nudge lookback / stops / volume / TP / sector weights — **from the SEED**, never from empty zeros.  
3. Each change is logged with a human-readable **WHY** in `data/learning_history.json`.  

### Learn from trades done outside this app

Import brokerage fills so they journal (`origin=external`) and feed learning / walk-forward scoreboard / E-ve — **without** mixing into app-paper cash equity and **without** auto live trading.

**Mobile:** Learning → **Import outside trades** — paste CSV → Dry-run preview → Confirm import.

**API**

```bash
# Dry-run preview
curl -s -X POST http://127.0.0.1:8000/trades/import   -H 'Content-Type: application/json'   -d "{"format":"csv","dry_run":true,"content":$(python -c 'import json,pathlib; print(json.dumps(pathlib.Path("scripts/fixtures/external_trades_sample.csv").read_text()))')}"

# Confirm import
curl -s -X POST http://127.0.0.1:8000/trades/import   -H 'Content-Type: application/json'   -d '{"format":"csv","dry_run":false,"content":"symbol,side,qty,price,datetime\nAAPL,buy,10,190,2026-08-01T14:00:00Z\nAAPL,sell,10,198,2026-08-08T15:00:00Z"}'

# Optional Alpaca history (ALPACA_API_KEY + ALPACA_API_SECRET; import only)
curl -s -X POST http://127.0.0.1:8000/trades/import/alpaca -H 'Content-Type: application/json' -d '{"dry_run":false,"limit":100}'

curl -s 'http://127.0.0.1:8000/trades/learning-stats'
curl -s 'http://127.0.0.1:8000/trades/external?limit=20'
```

Flexible CSV headers: `symbol`/`ticker`, `side`/`buy`/`sell`, `qty`/`quantity`/`shares`, `price`, `datetime`/`date`/`time`, optional `fee`/`commission`, `order_id`, `notes`, `strategy`. JSON list also supported. Dedupe by `broker_order_id` or hash(symbol, side, qty, price, ts). Fills stored in `data/external_trades.jsonl`; closed round-trips merge into the journal with `origin=external`.

Smoke: `python scripts/smoke_external_trades.py` · sample: `scripts/fixtures/external_trades_sample.csv`.

4. Live-learned params → `data/learned_config.json`.  
5. Forward-estimate accuracy and ensemble votes also feed interpretable threshold/weight nudges.

---

## Historical training (walk-forward)

- Default history length: **20 years** (maximum). Shorter **5 / 10 / 15** for faster runs.  
- Train window ~5y → test 1y, roll forward; regime tags (bull/bear/sideways, high/low vol via SPY).  
- Forward models / ensembles retrain on **pre-test data only** (no look-ahead).  
- Bars filtered to exchange sessions (no weekend/holiday) via `exchange-calendars` when installed.  
- Runtime: depends on network/CPU; 5y is much faster than 20y; training uses a sampled ticker subset for speed.

Checkpoints: `data/historical_baseline.json`.

---

## Forward estimates & ensemble (no look-ahead)

At each timestamp, features use **only bars ≤ that date**.  
Ensemble: **LogisticRegression + GradientBoosting + rule scorer**; configurable vote/weight consensus.  
Entry requires momentum+volume (+ advanced filters) **and** forward/ensemble pass (unless watchlist labeling).

**Disclaimer:** statistical estimate, not a guarantee of future returns.

---

## Advanced optimizations (short)

| Layer | What it does |
|-------|----------------|
| Vol / ADX / MA filters | Skip extreme vol & weak-trend entries; min price avoids pennies |
| Trailing stop / partial TP / time exit | Lock gains, scale out at +10% (default), exit stale trades |
| Regime (SPY + VIX proxy) | Shrink or pause size in bear/high-vol |
| Ensemble | Consensus reduces single-model false positives |
| News sentiment | Boost/warn priority from RSS (+ optional APIs) |
| Time zones | Act/label by NYSE hours; dual user+market clocks |

---


## Strategies

GAMMA-R runs a **multi-strategy suite** (package `momentum_bot.strategies`). Momentum remains one strategy among several; a **router** selects which plugins are active each cycle.

| Strategy | Role |
|----------|------|
| `momentum` | Core short-term price + volume trend (existing scanner path) |
| `mean_reversion` | Oversold / pullback (RSI + MA) |
| `breakout` | N-day high on elevated volume |
| `relative_strength` | Outperform SPY / sector proxies |
| `earnings_drift` | PEAD — best-effort; needs `FINNHUB_API_KEY` or no-ops |
| `pairs` | Long strong / underweight weak twin |
| `fx_mean_reversion` | Majors mean-reversion — informational / paper only |
| `vol_target` | **Overlay** — scales size toward `vol_target_annual` (not an entry) |

**Router** (`router_mode=auto|manual`): uses regime (bull/bear/sideways, high/low vol), optional news tilt, and recent journal performance. Example priors (tunable via `strategy_router_priors`, not dogma): trend/bull → momentum + breakout; sideways → mean reversion + pairs; high-vol → shrink via vol-target + prefer RS; FX when currency panel on; PEAD when earnings events exist.

**Config:** `strategy_enabled` map, `router_mode`, `vol_target_annual` (default 0.15). Defaults enable momentum + mean_reversion + breakout + relative_strength + vol_target; pairs/FX/PEAD stay on but degrade safely if data is thin.

**API:** `GET /strategies` · `GET /strategies/{id}` · scan/auto status include `strategies_last_cycle`.

**Paper-first only.** Live trading stays gated by `LIVE_TRADING_ENABLED`.

## News sentiment flow

1. Pull **RSS** (Yahoo/CNBC/MarketWatch/Nasdaq) — free. Optional `FINNHUB_API_KEY` / `NEWSAPI_KEY`.  
2. Score with **VADER** (default). Optional FinBERT if `transformers` installed (`prefer_finbert`).  
3. Aggregate 24h / 7d per ticker & sector; detect spikes.  
4. Blend with technicals via `news_blend_mode`: `70_30` (default), `50_50`, `technical_only`.  
5. Strong positive → priority boost; sudden negative → warning / block new entries.  
6. Backtests/historical: pass `as_of` so **only news published before** that time is used.  
7. **End-of-day digest** (`GET /news/eod`): last ~24h equity + FX/macro headlines, sector/ticker impacts, bullish/bearish tilt — shown on the mobile Dashboard.

---

## Currency / FX panel

Informational major-pair quotes (yfinance symbols like `EURUSD=X`) for equity context — **not** live FX trading.

- Pairs: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, plus EURGBP / EURCAD crosses.
- API: `GET /currency` (alias `/fx`) returns last, daily `%` change, session note, top movers; `GET /currency/{pair}` for one pair.
- Config: `use_currency_panel` (default `true`) — hide the Dashboard panel when false.
- Mobile Dashboard shows a compact Currency row (name / last / day change green-red) plus the End of day news card.

---

## Time zone handling

- Internal storage: **UTC**.  
- Display: **market TZ + user TZ** dual label (e.g. `3:00 PM EDT / 9:00 PM CEST`).  
- Setting: `user_timezone` (IANA, default `America/Chicago`); `market_exchange` `NYSE|NASDAQ|LSE|TSE|HKEX` (LSE/TSE/HKEX stubbed hours).  
- Signals labeled `open|pre|after|closed|holiday`; `only_act_during_open` can pause entries.  
- Learning logs `session_bucket` (`us_rth`, `us_extended`, `asia`, …).

---

## Market data sources (free default · optional SIP)

| Mode | Source | Used for | Cost |
|------|--------|----------|------|
| **free** (default) | yfinance delayed | Historical training, backtests, live (when SIP off) | $0 |
| **alpaca_sip** | Alpaca WebSocket `wss://stream.data.alpaca.markets/v2/sip` | **Live scans & forward-estimate only** | Algo Trader Plus **~$99/mo** |

SIP is **never** used for historical training or backtests. Paper trading remains the default execution path.
**Not a Level-2 order book** — realtime means last trade/quote (IEX or SIP), not depth-of-book / full tape.

### Enable real-time SIP (optional)

1. Alpaca account with **Algo Trader Plus** (~$99/mo) for SIP entitlement.  
2. API key + secret (same keys as brokerage; store in env / SecureStore — never commit).  
3. Server:
   ```bash
   export DATA_SOURCE=alpaca_sip          # or REALTIME_SIP_ENABLED=1
   export ALPACA_API_KEY=...
   export ALPACA_API_SECRET=...
   # optional aliases: ALPACA_DATA_KEY / ALPACA_DATA_SECRET
   pip install websockets                 # already in requirements.txt
   python -m momentum_bot serve
   ```
4. Or toggle from the app: **Settings → Real-time data (Alpaca SIP)** (`PUT /data-source`).  
5. Status: `GET /data-source/status` (active source, `fallback_active`, last warning).  
6. If the SIP socket disconnects or errors, the bot **auto-falls back to free** and logs a warning (`data/data_source_events.json`). Retry with `POST /data-source/reset-fallback`.

Adapter layout: `momentum_bot/data_sources/` (`base.py`, `yfinance_source.py`, `alpaca_sip.py`).

---

## Live brokerage (DISABLED by default)

Adapters in `momentum_bot/brokers/`:

- **Alpaca** — paper + live REST (keys via env).  
- **IBKR** — stub for later.

### Activate when ready

1. Create Alpaca account; generate API key/secret.  
2. Prefer **paper** endpoint first: `ALPACA_PAPER=1`.  
3. Server:
   ```bash
   export LIVE_TRADING_ENABLED=1
   export ALPACA_API_KEY=...
   export ALPACA_API_SECRET=...
   export BROKER=alpaca
   python -m momentum_bot serve
   ```
4. App Settings → unlock **Live Trading** (risk warning) → enter keys → saved with **expo-secure-store** (Keychain/Keystore), never plain text.  
5. Kill switch: `POST /broker/kill` (cancel orders + flatten).

Until `LIVE_TRADING_ENABLED=1`, all `/broker/*` mutating routes return 403; paper flow is unchanged.

---

## Push notifications

`POST /notify/register` stores device tokens in `data/push_tokens.json`.  
On scan with new signals, `_stub_notify` logs a payload. Hook:

- Expo: `POST https://exp.host/--/api/v2/push/send`  
- or FCM

---

## What to customize

- SEED / risk caps in `momentum_bot/config.py`  
- Transaction costs (`fees_enabled`, commission mode/amount, `slippage_pct`)  
- Universe mode, filters, ensemble weights, news blend, TZ  
- Historical years & ticker sample size  
- Broker credentials via env / SecureStore only  
- `DATA_SOURCE=free|alpaca_sip` / Settings SIP toggle (live-only)  

---



## Beat retail bots (honest edge)

GAMMA-R aims to **beat retail signal bots** on process, risk, and learning — not on fake Level-2 or marketed live track records.
Paper-first; `LIVE_TRADING_ENABLED` stays off unless you unlock it. Auth + policy firewall stay on.

## Competitive gaps (closed vs open)

Honest comparison vs day-trading scanners / template SaaS. **Paper-first; live stays locked unless you unlock it.**
**Not Level-2:** feed badges are **Delayed | IEX | SIP | NBBO** (last trade / **top-of-book**). We do **not** ship an order-book / full tape.

### Closed (this wave + prior)

| Gap | What we shipped |
|-----|-----------------|
| **Speed / freshness** | Dashboard data age, last scan, stale warnings, **feed badge Delayed | IEX | SIP | NBBO**. `GET /data-source/status` includes enable checklist + connection health. |
| **NBBO / quotes (L2-lite)** | `GET /quotes?symbols=` best bid/ask/mid/spread/size when Alpaca keys or SIP/IEX cache exist. Included in `/sync/ticks` + `/sync/snapshot`. **Top-of-book only — not full depth.** |
| **Watchlist push** | WebSocket `/ws/watchlist` + dense SSE `/events/quotes`. Mobile Watchlist/Dashboard subscribe while focused with reconnect backoff. |
| **Intraday heat (not L2)** | `GET /scan/intraday-heat` bar anomalies on watchlist + liquid subset. Explicitly **not** a Level-2 book. |
| **Live-feeling ticks** | `GET /sync/ticks` fast poll (realtime cache or delayed labeled). |
| **Public PAPER leaderboard** | `GET /paper/leaderboard` + `/public/paper-stats` + HTML share card. Watermark **PAPER — not live audited**. |
| **Paper options simulator** | `POST /options/paper` long call/put from research chain; journal `origin=paper_options`; firewall size caps; **no live options**. UI: Paper buy call/put on signal card. |
| **Scheduled web learning** | Optional `auto_web_learn_enabled` loop → `learn_from_web` on macro + open/watchlist tickers → `web_learning.jsonl`. E-ve **Overnight research**. |
| **Alerts polish** | Crash mode ON, heat spike, strategy cut, firewall deny streak. Settings toggles. `GET /alerts` · `POST /alerts/evaluate`. |
| **IBKR path** | Solid `brokers/ibkr.py` stub + Settings **planned** + setup doc steps. Does not block paper path. |
| **Edge / differentiation** | `GET /edge/status` · `/edge/why` · `/edge/gaps` · `/edge/improvements` · `/edge/overnight` · `/edge/critique`. Dashboard **BEAT RETAIL** card. |
| **E-ve as trading OS** | Tools: `get_edge_status`, `get_competitive_gaps`, `get_feed_health`, `propose_next_improvements`, `get_overnight_research`, `get_quotes`, `paper_option_order`. Chips: Our edge · vs other bots · What to improve · Overnight research. System prompt: always cite regime+firewall+scoreboard; never claim L2 / live-audited. |
| **Broker connect (marketplace-lite)** | paper sim / alpaca paper / alpaca live(**locked**) / ibkr(**planned**). |
| **Options research** | Read-only IV/expiry sketch + idea journal. |
| **Continuous improvement hooks** | `data/ai_process_log.jsonl` on edge reports; `propose_next_improvements` from live health; overnight research loop — durable paper-first upgrade path. |
| **Daily self-critique** | E-ve tool `run_daily_self_critique` · `GET /edge/critique` · `POST /edge/critique/run`. Chip **Daily self-critique**. |
| **Overnight → learning ingest** | After scheduled/manual web learn, distill `web_learning.jsonl` → `data/overnight_learning_digest.json` surfaced in `GET /learning/stats` (`overnight_web`). `POST /edge/overnight/ingest`. |
| **Beat retail / ahead on AI card** | Dashboard edge card (`GET /edge/why`) — **AHEAD ON AI** vs pro terminals; honest behind on BLP data. |
| **Pro terminal wave** | Charts `/bars` · tape lite · NBBO ladder · `/scan/custom` · options chain+greeks · paper stop/TP/bracket/OCO · econ calendar · pro layout. **Not full L2.** |
| **Bloomberg-inspired desk** | GO command bar · multi-panel presets · monitor launchpad · cross-asset board · watchlist columns · E-ve AI briefs. **Not a BLP license.** |

### Better than signal bots (honest win column)

| We win (process / intelligence / risk) | They still win (intentionally open) |
|----------------------------------------|-------------------------------------|
| Multi-strategy **regime router** vs single-indicator spam | True **Level-2 / full tape** scanners (Trade Ideas class) |
| Hard **policy firewall** + **decision audit** | Marketed **live-audited** return dashboards |
| **Crash mode** + scoreboard keep/watch/cut | Full **live options / futures** order routing |
| **External-trade learning** + allowlisted overnight web | — |
| Honest **PAPER** watermark (no fake track record) | — |
| E-ve that **compares proposals to firewall+regime+scoreboard** before suggesting paper | — |
| NBBO top-of-book when keys exist — **labeled not L2** | — |

### Still open (intentionally / hard)

- Trade Ideas–class **true Level-2 order book / tape**
- Marketed **live audited** returns (we only publish **PAPER**)
- **Full options execution** and **futures**
- Full IBKR TWS live trading (stub/planned only)
- **Bloomberg proprietary data / BLP universe** (we do not claim a license)

### Continuous improvement (always on)

1. `GET /edge/improvements` — ranked next upgrades from feed health + learning stats  
2. `GET /edge/overnight` + scheduled web learn — compound research memory  
3. `data/ai_process_log.jsonl` — E-ve remembers the improvement journey  
4. Ask E-ve: **What to improve next** / **Our edge** / **vs other bots**

### World-class controls (already in tree)

Crash mode · walk-forward paper scoreboard · decision audit · policy firewall · owner auth — not weakened.

### Verify this pass

```bash
python scripts/smoke_competitive_gaps.py
python -m compileall momentum_bot
```




## vs Bloomberg / pro terminals (honest)

GAMMA-R closes the **workflow UX** gap with a Bloomberg-inspired desk — **not** a Bloomberg data license.

| Ahead (AI / automation / learning) | Behind (intentional) |
|------------------------------------|----------------------|
| **E-ve** desk AI — briefs, monitor, ladder explain, GO help; always cites regime/firewall/scoreboard | Proprietary **Bloomberg / BLP** data universe |
| Personal learning loops (external fills, overnight web, self-critique) | Licensed full news + analytics catalog |
| Paper-first automation + fail-closed policy firewall | True **Level-2** / exchange depth |
| GO command bar · multi-panel desk · monitor launchpad · cross-asset board | Co-lo / exchange-proximate infra |

**API:** `POST /desk/command` · `GET /desk/layout` · `GET /desk/monitor` · `GET /desk/cross-asset` · `GET /desk/brief?symbol=` · `GET /desk/eve-brief` · `GET /portfolio/analytics` · `GET/PUT /watchlist/columns`  
**Mobile:** sticky GO bar on Pro Dashboard · **Pro Desk** (layout presets · pull-to-refresh · empty/loading panels) · monitor strip · E-ve chips: **Full desk brief** · Portfolio risk · Command help · Desk brief · Monitor  
**E-ve depth:** tools `eve_desk_brief` (regime/signals/crash/scoreboard/overnight) + `portfolio_risk_snapshot`; persona **E-ve**  
**Portfolio analytics:** `GET /portfolio/analytics` — allocation, P&L, win rate, exposure, drawdown (PAPER · live locked · not Bloomberg PORT)  
**Honesty:** `not_bloomberg_licensed: true` · `not_level2: true` · live locked · PAPER watermarks  

`GET /edge/status` and `GET /edge/why` report the same vs-Bloomberg framing.

### Keep-working verify (Pro Desk + E-ve + analytics)

```bash
python scripts/smoke_desk.py
python -m compileall momentum_bot
```


## Pro terminal gap (vs Thinkorswim / Trade Ideas / IB TWS class)

Honest close-the-gap wave: **paper-first**, live locked, **no fake full L2 depth**, auth + firewall intact.

### Closed this wave

| Capability | Ship |
|------------|------|
| **Pro charts** | `GET /bars/{symbol}?interval=1d\|1h\|15m\|5m&limit=` — OHLCV + VWAP. Mobile candle chart on Signal detail with interval switch + volume. |
| **Tape lite** | `GET /tape/{symbol}` (alias `/trades/{symbol}`) — recent prints when Alpaca keys exist; else honest empty + label. Time & Sales panel on Signal detail. |
| **NBBO ladder** | `GET /ladder/{symbol}` — price ladder centered on mid; bid/ask sizes from NBBO. Caption: **Top-of-book ladder — not full exchange depth.** |
| **Pro scanner builder** | `POST /scan/custom` filters: min volume / % change / RS / news tilt / strategy / region / price range. Mobile **Pro scanner** screen. |
| **Options chain + greeks** | `GET /options/{ticker}/chain` — strike, bid/ask, IV, delta/gamma/theta/vega (Black-Scholes approx when needed). Tap row → paper buy call/put. |
| **Paper pro orders** | `POST /portfolio/orders/pro` — stop, take-profit, bracket, OCO. Working-order list + manage/cancel. Portfolio UI. Long-press Signal title = paper bracket. |
| **Economic calendar** | `GET /calendar/economic` curated rail on Dashboard. |
| **Pro layout / hotkeys** | `GET /layout/pro` denser Dashboard; web hotkey doc; mobile long-press bracket. |
| **E-ve** | Tools: `get_bars`, `get_tape`, `get_ladder_quote`, `run_custom_scan`, `get_economic_calendar`. Chips: **Pro chart · Tape · Custom scan**. |

### Still open (hard / intentional)

- True **Level-2 / full exchange depth** and full tape (Trade Ideas class)
- **Futures** execution
- **Colocation** / exchange-proximate infra
- Marketed **live-audited** returns (we publish **PAPER** only)
- Full **live options** order routing

### Verify

```bash
python scripts/smoke_competitive_gaps.py
python -m compileall momentum_bot
```


## Verify

```bash
python -m compileall momentum_bot
```

---

## What changed (feature stack)

Paper trading · realistic transaction costs (commission + slippage, ON by default) · manual watchlist · seeded learning · 20y historical walk-forward · forward estimates · ensemble · regime · trailing/partial/time exits · news sentiment · timezone/session awareness · optional Alpaca SIP real-time data (off by default, ~$99/mo) · Alpaca broker adapter (off by default) · Expo mobile tabs · easy private iPhone install (Expo Go / EAS IPA / TestFlight) · E-ve voice (on-device STT/TTS).

---

## Unattended auto-learn + auto-trade (paper-first)

When you start the API (`python -m momentum_bot serve`), background loops start automatically:

| Loop | Default | What it does |
|------|---------|----------------|
| **Auto-learn** | every **10 min** (+ when journal grows) | Ingests closed-trade journal (with context tags), updates thresholds → `learned_config.json` + runtime |
| **Auto-trade** | every **15 min** | Scan → confidence/risk gates → paper orders (no manual tap). Exits managed on a ~60s cadence |
| **Circuit breaker** | continuous | Halts **new** auto entries on stale/broken data; auto-resumes when healthy. Learning continues |

### Config flags (Settings or `PUT /config` / `PUT /auto`)

- `auto_learn_enabled` (default **True**)
- `auto_trade_enabled` (default **True** — paper)
- `min_confidence`, `max_position_pct`, `max_concurrent_positions`
- `maintenance_windows_enabled` + open/close buffers (US/Eastern session)

### Key endpoints

- `GET /auto/status` — loops, last scan/trade/learn, maintenance, circuit breaker
- `POST /auto/trade/run` / `POST /auto/learn/run` — manual one-shots
- `GET /circuit-breaker` + false-trip / missed-bad / resume
- `POST /learning/replay` — replay recent sessions with today’s learned params vs prior
- `POST /portfolio/feedback/{id}` — like/dislike + note for richer learning

### Still requires a manual flip

- **LIVE_TRADING_ENABLED=1** — never set by the bot; live broker routing stays off until you enable it
- **Alpaca keys** / SIP subscription for paid realtime
- **Apple / EAS** build & install for the mobile app on a physical iPhone
- `OWNER_SHARED_SECRET` / `GAMMA_R_HARDENED=1` / `REQUIRE_API_SECRET=1` — see **Security** section

### Config merge on startup

1. Day-one SEED → 2. `historical_baseline.json` → 3. `learned_config.json` → 4. `runtime_config.json` (Settings + auto flags)

State persisted under `data/` (`auto_loop_state.json`, `circuit_breaker_state.json`, journal, paper portfolio, learned config).
