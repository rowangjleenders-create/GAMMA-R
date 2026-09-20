"""
CLI entry: python -m momentum_bot scan|backtest|serve|historical-train|learn
"""

from __future__ import annotations

import argparse
import json
import sys


def cmd_scan(args: argparse.Namespace) -> int:
    from .config import get_runtime_config
    from .learning import apply_learned_on_startup
    from .scanner import run_scan, signals_to_dicts
    from .watchlist import load_watchlist

    apply_learned_on_startup()
    cfg = get_runtime_config()
    signals = run_scan(cfg, watchlist=load_watchlist())
    print(json.dumps(signals_to_dicts(signals), indent=2))
    print(f"\n{len(signals)} signal(s)", file=sys.stderr)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from .backtest import run_backtest
    from .config import get_runtime_config
    from .learning import apply_learned_on_startup

    apply_learned_on_startup()
    cfg = get_runtime_config()
    if args.years:
        cfg = cfg.update({"backtest_years": args.years})
    result = run_backtest(cfg)
    out = result.to_dict()
    # Trim trades for console
    if not args.full:
        out["trades"] = out.get("trades", [])[:20]
        out["trades_truncated"] = True
    print(json.dumps(out, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn
    from .learning import apply_learned_on_startup
    from .security import ensure_owner_secret_for_serve, hardened_mode

    # Advertise bind host so middleware / hardened_mode agree with CLI
    os.environ["GAMMA_R_BIND_HOST"] = args.host
    ensure_owner_secret_for_serve(args.host)
    if hardened_mode(args.host) and args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "[security] Binding non-loopback. Prefer Tailscale/VPN or localhost; "
            "never expose 0.0.0.0 to the public internet without TLS reverse proxy + secret."
        )

    apply_learned_on_startup()
    uvicorn.run(
        "momentum_bot.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_historical_train(args: argparse.Namespace) -> int:
    from .config import get_runtime_config
    from .historical import ALLOWED_YEARS, DEFAULT_YEARS, run_historical_train
    from .learning import apply_learned_on_startup

    years = args.years if args.years in ALLOWED_YEARS else DEFAULT_YEARS
    print(f"Historical walk-forward train for {years} years (default max=20)...")
    result = run_historical_train(
        years=years,
        cfg=get_runtime_config(),
        max_tickers=args.max_tickers,
    )
    apply_learned_on_startup()
    # Compact print
    summary = {
        "label": result.get("label"),
        "years": result.get("years"),
        "params": result.get("params"),
        "summary": result.get("summary"),
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    from .learning import apply_learned_on_startup, reset_learning, run_learning

    apply_learned_on_startup()
    if args.reset:
        print(json.dumps(reset_learning(wipe_journal=args.wipe_journal), indent=2))
    else:
        print(json.dumps(run_learning(force=True, reason="cli"), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="momentum_bot", description="Momentum trading bot (educational)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Run whole-market momentum scan")
    p_scan.set_defaults(func=cmd_scan)

    p_bt = sub.add_parser("backtest", help="Run simple historical backtest")
    p_bt.add_argument("--years", type=int, default=None)
    p_bt.add_argument("--full", action="store_true", help="Include all trades in JSON")
    p_bt.set_defaults(func=cmd_backtest)

    p_serve = sub.add_parser("serve", help="Start FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1; use 0.0.0.0 for LAN — requires owner secret)")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_ht = sub.add_parser("historical-train", help="Walk-forward historical training")
    p_ht.add_argument(
        "--years",
        type=int,
        default=20,
        choices=[5, 10, 15, 20],
        help="History length (default 20 = maximum)",
    )
    p_ht.add_argument("--max-tickers", type=int, default=80)
    p_ht.set_defaults(func=cmd_historical_train)

    p_learn = sub.add_parser("learn", help="Run or reset rule-based learning")
    p_learn.add_argument("--reset", action="store_true")
    p_learn.add_argument("--wipe-journal", action="store_true")
    p_learn.set_defaults(func=cmd_learn)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
