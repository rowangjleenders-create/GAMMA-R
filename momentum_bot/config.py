"""
Tunable strategy parameters.

SEED / day-one baseline (informed momentum defaults — NOT zeros):
  Classic 12–1 momentum ranking (momentum_lookback_days=252, momentum_skip_days=21),
  lookback_days=10 (short-term / volume context), volume_multiple=1.5 (of 20d avg),
  top_pct=0.10 (top 10%),
  stop_loss_pct=0.05, take_profit_pct=0.15, equal sector weights,
  plus advanced filter/exit/regime/ensemble defaults below.

Learning refines FROM these seeded values. Reset restores THIS baseline.
Historical train default years = 20 (max); 5/10/15 optional for speed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional


SEED_DEFAULTS: Dict[str, Any] = {
    "lookback_days": 10,
    "momentum_lookback_days": 252,
    "momentum_skip_days": 21,
    "top_n": 20,
    "top_pct": 0.10,
    "min_return": 0.05,
    "volume_avg_days": 20,
    "volume_multiple": 1.5,
    "risk_per_trade": 0.01,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.15,
    "max_position_pct": 0.10,
    "starting_equity": 10_000.0,
    "universe": "combined",
    "min_price": 5.0,
    "max_download": 900,
    "backtest_years": 2,
    "rebalance_every": 5,
    "learning_min_trades": 10,
    "forward_estimate_threshold": 0.55,
    "forward_estimate_horizon": 3,
    "use_forward_estimate": True,
    "historical_train_years": 20,
    # Advanced entry filters
    "max_realized_vol": 0.85,
    "vol_lookback": 10,
    "require_adx": True,
    "min_adx": 18.0,
    "adx_period": 14,
    "require_ma_alignment": True,
    "ma_fast": 10,
    "ma_slow": 20,
    # Smarter exits
    "use_trailing_stop": True,
    "trailing_stop_pct": 0.04,
    "use_partial_profits": True,
    "partial_take_pct": 0.10,
    "partial_fraction": 0.50,
    "time_exit_days": 10,
    "time_exit_min_move": 0.03,
    # Regime
    "use_regime_filter": True,
    "regime_high_vol": 0.22,
    "vix_high": 25.0,
    "regime_bear_size": 0.35,
    "regime_highvol_size": 0.50,
    "regime_sideways_size": 0.70,
    "regime_bear_highvol_size": 0.0,
    "pause_in_bear": False,
    "pause_in_high_vol": False,
    # Ensemble
    "use_ensemble": True,
    "ensemble_w_logreg": 0.40,
    "ensemble_w_gbdt": 0.35,
    "ensemble_w_rules": 0.25,
    "ensemble_min_votes": 2,
    "use_news_sentiment": True,
    "news_weight": 0.3,
    "news_blend_mode": "70_30",
    "news_spike_threshold": 0.35,
    "news_negative_threshold": -0.4,
    "news_positive_threshold": 0.4,
    "prefer_finbert": False,
    "news_block_on_negative": True,
    "use_currency_panel": True,
    "user_timezone": "America/Chicago",
    "market_exchange": "NYSE",
    "allow_after_hours_signals": True,
    "only_act_during_open": False,
    "use_per_ticker_sessions": True,
    "session_gate_entries": True,
    "exclude": [],
    "sector_weights": {},
    "realtime_sip_enabled": False,  # live-only Alpaca SIP; free default
    # Transaction costs (ON by default for realism)
    "fees_enabled": True,
    "commission_mode": "per_share",  # per_share | flat
    "commission_per_share": 0.005,
    "commission_flat": 1.0,
    "slippage_pct": 0.001,  # 0.1% of trade value
    # Auto loops (unattended learn + paper trade)
    "auto_learn_enabled": True,
    "auto_trade_enabled": True,
    "auto_learn_interval_minutes": 10,
    "auto_trade_interval_minutes": 15,
    "auto_exit_interval_seconds": 60,
    "max_concurrent_positions": 5,
    "auto_trade_max_new_per_cycle": 2,
    "auto_trade_require_forward_pass": True,
    "min_confidence": 0.45,
    "maintenance_windows_enabled": True,
    "maintenance_open_buffer_minutes": 15,
    "maintenance_close_buffer_minutes": 15,
    "maintenance_allow_exits": True,
    # Multi-strategy suite
    "strategy_enabled": {
        "momentum": True,
        "mean_reversion": True,
        "breakout": True,
        "relative_strength": True,
        "vol_target": True,
        "pairs": True,
        "fx_mean_reversion": True,
        "earnings_drift": True,
    },
    "router_mode": "auto",  # auto | manual
    "vol_target_annual": 0.15,
    "vol_target_lookback": 20,
    "vol_target_floor": 0.25,
    "vol_target_ceil": 1.5,
    "strategy_router_priors": {},
    "mr_rsi_max": 32.0,
    "mr_pullback_min": -0.04,
    "breakout_lookback": 20,
    "breakout_volume_multiple": 1.4,
    "rs_lookback": 20,
    "pairs_lookback": 20,
    "pairs_min_spread": 0.04,
    "pead_min_surprise": 0.05,
    # Policy firewall (deterministic pre-submit checks; paper-first)
    "firewall_enabled": True,
    "firewall_max_notional": 0.0,  # 0 = use max_pct_equity only
    "firewall_max_pct_equity": 0.10,
    "firewall_max_new_orders_per_day": 30,
    "firewall_max_new_orders_per_cycle": 5,
    "firewall_allowlist": [],
    "firewall_denylist": [],
    "firewall_human_approval_notional": 0.0,  # 0 = disabled; else block/queue above
    # Co-pilot
    "copilot_tools_enabled": True,
    "copilot_memory_enabled": True,
    "copilot_max_tool_rounds": 4,
    # Co-pilot allowlisted web (NOT open browsing)
    "copilot_web_enabled": True,
    "copilot_web_crypto_enabled": False,
    "copilot_web_allowlist": [
        "reuters.com",
        "bloomberg.com",
        "cnbc.com",
        "marketwatch.com",
        "ft.com",
        "wsj.com",
        "federalreserve.gov",
        "sec.gov",
        "investing.com",
        "yahoo.com",
        "finance.yahoo.com",
        "bbc.com",
        "bbc.co.uk",
    ],
    "copilot_web_rate_limit": 8,
    "copilot_web_timeout_sec": 8,
    "copilot_web_max_bytes": 400000,
    # Crash / regime-shock mode
    "crash_mode_enabled": True,
    "crash_lookback": 5,
    "crash_threshold_pct": -0.03,
    "crash_vol_mult": 2.0,
    "crash_cooldown_days": 3,
    "crash_size_mult": 0.25,
    # Walk-forward / paper scoreboard
    "scoreboard_min_trades": 10,
    "scoreboard_router_downweight": True,
    "scoreboard_recent_days": 30,
    "scoreboard_oos_days": 14,
    # Decision audit trail
    "decision_audit_enabled": True,
    # Scan freshness / speed
    "scan_cache_ttl_sec": 60,
    "scan_stale_warn_sec": 180,
    "auto_scan_interval_minutes": 5,
    "quick_scan_enabled": True,
    # Live-feeling mobile poll / sync
    "dashboard_poll_sec": 3,
    # Options research foothold (no order routing)
    "options_read_only": False,
    # Optional shorter bars for watchlist breakout (1d|1h|15m); daily 12-1 path unchanged
    "watchlist_bar_interval": "1d",
    "watchlist_intraday_period": "5d",
    "intraday_heat_enabled": True,
    "intraday_heat_interval": "5m",
    "intraday_heat_period": "5d",
    "intraday_heat_top_n": 12,
    "intraday_heat_liquid_n": 24,
    "intraday_heat_max_symbols": 40,
    # NBBO / quotes (L2-lite — top of book only)
    "quotes_enabled": True,
    # Scheduled allowlisted web learning
    "auto_web_learn_enabled": False,
    "auto_web_learn_interval_minutes": 360,
    "auto_web_learn_macro_topics": ["macro", "fed", "inflation", "earnings"],
    # Alerts polish
    "alerts_enabled": True,
    "alert_crash_mode": True,
    "alert_intraday_heat": True,
    "alert_strategy_cut": True,
    "alert_firewall_deny_streak": True,
    "alert_firewall_deny_threshold": 3,
    # Paper options simulator
    "paper_options_enabled": True,
}


@dataclass
class StrategyConfig:
    # --- Momentum (seeded) ---
    lookback_days: int = 10  # short-term / volume context
    # Classic 12–1: ~12m total return excluding most recent ~1m
    momentum_lookback_days: int = 252
    momentum_skip_days: int = 21
    top_n: int = 20
    top_pct: float = 0.10
    min_return: float = 0.05

    # --- Volume ---
    volume_avg_days: int = 20
    volume_multiple: float = 1.5

    # --- Risk ---
    risk_per_trade: float = 0.01
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.15
    max_position_pct: float = 0.10
    starting_equity: float = 10_000.0

    # --- Universe ---
    # combined/all = US (S&P500∪Nasdaq-100) + Canada (TSX 60) + UK (FTSE 100)
    # + Europe (EURO STOXX 50). Also: sp500, nasdaq100, tsx60, ftse100,
    # europe/eurostoxx50, international (non-US only). Not every stock worldwide.
    universe: str = "combined"
    min_price: float = 5.0
    max_download: int = 900  # room for multi-region combined (~700–800 names)

    # --- Backtest ---
    backtest_years: int = 2
    rebalance_every: int = 5

    # --- Learning / forward / historical ---
    learning_min_trades: int = 10
    forward_estimate_threshold: float = 0.55
    forward_estimate_horizon: int = 3
    use_forward_estimate: bool = True
    historical_train_years: int = 20  # default MAX

    # --- Advanced entry filters ---
    max_realized_vol: float = 0.85
    vol_lookback: int = 10
    require_adx: bool = True
    min_adx: float = 18.0
    adx_period: int = 14
    require_ma_alignment: bool = True
    ma_fast: int = 10
    ma_slow: int = 20

    # --- Smarter exits ---
    use_trailing_stop: bool = True
    trailing_stop_pct: float = 0.04
    use_partial_profits: bool = True
    partial_take_pct: float = 0.10
    partial_fraction: float = 0.50
    time_exit_days: int = 10
    time_exit_min_move: float = 0.03

    # --- Regime ---
    use_regime_filter: bool = True
    regime_high_vol: float = 0.22
    vix_high: float = 25.0
    regime_bear_size: float = 0.35
    regime_highvol_size: float = 0.50
    regime_sideways_size: float = 0.70
    regime_bear_highvol_size: float = 0.0
    pause_in_bear: bool = False
    pause_in_high_vol: bool = False

    # --- Ensemble ---
    use_ensemble: bool = True
    ensemble_w_logreg: float = 0.40
    ensemble_w_gbdt: float = 0.35
    ensemble_w_rules: float = 0.25
    ensemble_min_votes: int = 2

    # --- News sentiment ---
    use_news_sentiment: bool = True
    news_weight: float = 0.3  # 0=tech-only; 0.3≈70/30; 0.5=50/50
    news_blend_mode: str = "70_30"  # 70_30 | 50_50 | technical_only
    news_spike_threshold: float = 0.35
    news_negative_threshold: float = -0.4
    news_positive_threshold: float = 0.4
    prefer_finbert: bool = False
    news_block_on_negative: bool = True

    # --- Currency / FX panel (informational quotes on Dashboard) ---
    use_currency_panel: bool = True

    # --- Time zones / sessions ---
    user_timezone: str = "America/Chicago"  # app setting; default device-like Central
    market_exchange: str = "NYSE"  # NYSE|NASDAQ|LSE|TSE|HKEX
    allow_after_hours_signals: bool = True  # label after-hours; don't hide
    only_act_during_open: bool = False  # legacy global gate (also enables session gate)
    use_per_ticker_sessions: bool = True  # map .L/.TO/.DE… → home exchange hours
    session_gate_entries: bool = True  # skip NEW entries when home market closed

    exclude: List[str] = field(default_factory=list)
    sector_weights: Dict[str, float] = field(default_factory=dict)

    # --- Market data (live only; historical always free) ---
    realtime_sip_enabled: bool = False  # Alpaca SIP; needs Algo Trader Plus ~$99/mo

    # --- Transaction costs (paper + backtest) ---
    fees_enabled: bool = True
    commission_mode: str = "per_share"  # per_share | flat
    commission_per_share: float = 0.005
    commission_flat: float = 1.0
    slippage_pct: float = 0.001  # 0.1% of trade notional

    # --- Auto loops (paper-first; live still gated by LIVE_TRADING_ENABLED) ---
    auto_learn_enabled: bool = True
    auto_trade_enabled: bool = True
    auto_learn_interval_minutes: int = 10
    auto_trade_interval_minutes: int = 15
    auto_exit_interval_seconds: int = 60
    max_concurrent_positions: int = 5
    auto_trade_max_new_per_cycle: int = 2
    auto_trade_require_forward_pass: bool = True
    min_confidence: float = 0.45
    maintenance_windows_enabled: bool = True
    maintenance_open_buffer_minutes: int = 15
    maintenance_close_buffer_minutes: int = 15
    maintenance_allow_exits: bool = True

    # --- Multi-strategy suite ---
    strategy_enabled: Dict[str, bool] = field(default_factory=lambda: {
        "momentum": True,
        "mean_reversion": True,
        "breakout": True,
        "relative_strength": True,
        "vol_target": True,
        "pairs": True,
        "fx_mean_reversion": True,
        "earnings_drift": True,
    })
    router_mode: str = "auto"  # auto | manual
    vol_target_annual: float = 0.15
    vol_target_lookback: int = 20
    vol_target_floor: float = 0.25
    vol_target_ceil: float = 1.5
    strategy_router_priors: Dict[str, Any] = field(default_factory=dict)
    mr_rsi_max: float = 32.0
    mr_pullback_min: float = -0.04
    breakout_lookback: int = 20
    breakout_volume_multiple: float = 1.4
    rs_lookback: int = 20
    pairs_lookback: int = 20
    pairs_min_spread: float = 0.04
    pead_min_surprise: float = 0.05

    # --- Policy firewall (hard non-LLM; fail closed) ---
    firewall_enabled: bool = True
    firewall_max_notional: float = 0.0  # 0 → rely on firewall_max_pct_equity
    firewall_max_pct_equity: float = 0.10
    firewall_max_new_orders_per_day: int = 30
    firewall_max_new_orders_per_cycle: int = 5
    firewall_allowlist: List[str] = field(default_factory=list)
    firewall_denylist: List[str] = field(default_factory=list)
    firewall_human_approval_notional: float = 0.0  # 0 = off

    # --- Co-pilot ---
    copilot_tools_enabled: bool = True
    copilot_memory_enabled: bool = True
    copilot_max_tool_rounds: int = 4
    # Allowlisted web for co-pilot (educational macro/news; not open browsing)
    copilot_web_enabled: bool = True
    copilot_web_crypto_enabled: bool = False
    copilot_web_allowlist: List[str] = field(default_factory=lambda: [
        "reuters.com",
        "bloomberg.com",
        "cnbc.com",
        "marketwatch.com",
        "ft.com",
        "wsj.com",
        "federalreserve.gov",
        "sec.gov",
        "investing.com",
        "yahoo.com",
        "finance.yahoo.com",
        "bbc.com",
        "bbc.co.uk",
    ])
    copilot_web_rate_limit: int = 8
    copilot_web_timeout_sec: int = 8
    copilot_web_max_bytes: int = 400000

    # --- Crash / regime-shock mode ---
    crash_mode_enabled: bool = True
    crash_lookback: int = 5
    crash_threshold_pct: float = -0.03
    crash_vol_mult: float = 2.0
    crash_cooldown_days: int = 3
    crash_size_mult: float = 0.25

    # --- Walk-forward / paper scoreboard ---
    scoreboard_min_trades: int = 10
    scoreboard_router_downweight: bool = True
    scoreboard_recent_days: int = 30
    scoreboard_oos_days: int = 14

    # --- Decision audit ---
    decision_audit_enabled: bool = True

    # --- Scan freshness / speed ---
    scan_cache_ttl_sec: int = 60
    scan_stale_warn_sec: int = 180
    auto_scan_interval_minutes: int = 5
    quick_scan_enabled: bool = True

    # --- Live-feeling mobile poll ---
    dashboard_poll_sec: int = 3  # 2–5s typical; clamped in sync snapshot

    # --- Options research (Phase 2 foothold; no order routing) ---
    options_read_only: bool = False

    # --- Intraday / speed adjacent (watchlist breakout only) ---
    watchlist_bar_interval: str = "1d"  # 1d | 1h | 15m
    watchlist_intraday_period: str = "5d"

    # --- Intraday heat scanner (bar anomalies; not L2) ---
    intraday_heat_enabled: bool = True
    intraday_heat_interval: str = "5m"  # 1m|5m|15m
    intraday_heat_period: str = "5d"
    intraday_heat_top_n: int = 12
    intraday_heat_liquid_n: int = 24
    intraday_heat_max_symbols: int = 40


    # --- NBBO / top-of-book quotes (not L2 depth) ---
    quotes_enabled: bool = True

    # --- Scheduled allowlisted web learning ---
    auto_web_learn_enabled: bool = False
    auto_web_learn_interval_minutes: int = 360
    auto_web_learn_macro_topics: List[str] = field(default_factory=lambda: ["macro", "fed", "inflation", "earnings"])

    # --- Alerts ---
    alerts_enabled: bool = True
    alert_crash_mode: bool = True
    alert_intraday_heat: bool = True
    alert_strategy_cut: bool = True
    alert_firewall_deny_streak: bool = True
    alert_firewall_deny_threshold: int = 3

    # --- Paper options simulator (educational; no live options) ---
    paper_options_enabled: bool = True

    # --- Remote access (prefer Tailscale/Cloudflare/SSH; never naked public IP) ---
    remote_access_enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def seed(cls) -> "StrategyConfig":
        return cls.from_dict(dict(SEED_DEFAULTS))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyConfig":
        valid = {f.name for f in fields(cls)}
        cleaned = {k: v for k, v in data.items() if k in valid}
        return cls(**cleaned)

    def update(self, data: Dict[str, Any]) -> "StrategyConfig":
        merged = self.to_dict()
        valid = {f.name for f in fields(self)}
        for k, v in data.items():
            if k in valid:
                merged[k] = v
        return StrategyConfig(**merged)

    def effective_top_n(self, n_candidates: int) -> int:
        by_pct = max(1, int(round(n_candidates * self.top_pct)))
        return max(1, min(self.top_n, by_pct)) if n_candidates else self.top_n


_RUNTIME_CONFIG = StrategyConfig.seed()


def get_runtime_config() -> StrategyConfig:
    return _RUNTIME_CONFIG


def set_runtime_config(cfg: StrategyConfig) -> StrategyConfig:
    global _RUNTIME_CONFIG
    _RUNTIME_CONFIG = cfg
    return _RUNTIME_CONFIG


def reset_runtime_to_seed() -> StrategyConfig:
    return set_runtime_config(StrategyConfig.seed())


# Persist user/runtime overlays (auto flags + Settings) under data/
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "runtime_config.json"


def load_runtime_overlay() -> Dict[str, Any]:
    """Load data/runtime_config.json if present (user Settings + auto toggles)."""
    import json
    path = RUNTIME_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            return raw.get("params") if isinstance(raw.get("params"), dict) else raw
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_runtime_overlay(cfg: Optional["StrategyConfig"] = None) -> None:
    """Persist current runtime StrategyConfig to data/runtime_config.json."""
    import json
    from datetime import datetime, timezone
    cfg = cfg or get_runtime_config()
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": "runtime",
        "params": cfg.to_dict(),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "User Settings + auto-loop flags; overlaid last on startup after learned_config",
    }
    RUNTIME_CONFIG_PATH.write_text(json.dumps(payload, indent=2))
