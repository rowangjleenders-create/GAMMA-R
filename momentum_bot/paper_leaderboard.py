"""
Public PAPER leaderboard — honesty over hype.

Ranks strategies from the paper journal / scoreboard. Never invents live returns.
Watermark: PAPER — not live audited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


WATERMARK = "PAPER — not live audited"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_paper_leaderboard(cfg: Any = None, *, limit: int = 20) -> Dict[str, Any]:
    """
    Strategy ranks + equity sparkline summary + sample sizes + period.
    Safe for public/share display (no secrets, no live claims).
    """
    from .config import get_runtime_config
    from .scoreboard import build_paper_report, build_scoreboard

    cfg = cfg or get_runtime_config()
    report = build_paper_report(cfg)
    board = report.get("scoreboard") or build_scoreboard(cfg)
    summary = report.get("summary") or {}
    spark = list(report.get("equity_sparkline") or [])[-40:]

    ranks: List[Dict[str, Any]] = []
    for st in board.get("strategies") or []:
        prim = st.get("primary") or (st.get("metrics") or {}).get("all") or {}
        trades = prim.get("trades") or st.get("sample_size") or 0
        ranks.append({
            "strategy_id": st.get("strategy_id") or st.get("id"),
            "name": st.get("name") or st.get("strategy_id"),
            "status": st.get("status"),
            "sample_size": trades,
            "win_rate": prim.get("win_rate"),
            "expectancy": prim.get("expectancy"),
            "profit_factor": prim.get("profit_factor"),
            "max_drawdown": prim.get("max_dd") or prim.get("max_drawdown"),
            "total_pnl": prim.get("total_pnl") or st.get("total_pnl"),
        })

    # Prefer larger samples, then expectancy
    def _sort_key(r: Dict[str, Any]):
        n = float(r.get("sample_size") or 0)
        exp = r.get("expectancy")
        exp_f = float(exp) if exp is not None else -1e9
        return (n >= 5, n, exp_f)

    ranks.sort(key=_sort_key, reverse=True)
    ranks = ranks[: max(1, min(50, int(limit or 20)))]

    # Period from equity curve / journal
    curve = report.get("equity_curve") or []
    period_start = curve[0].get("t") if curve else None
    period_end = curve[-1].get("t") if curve else None

    return {
        "ok": True,
        "product": "GAMMA-R",
        "watermark": WATERMARK,
        "label": WATERMARK,
        "audited": False,
        "live": False,
        "generated_at": _utc_now(),
        "period": {
            "start": period_start,
            "end": period_end,
            "note": "Derived from local PAPER journal closes — not a live audited track record.",
        },
        "portfolio": {
            "return_pct": summary.get("return_pct"),
            "max_drawdown_pct": summary.get("max_drawdown_pct"),
            "win_rate": summary.get("win_rate"),
            "closed_trades": summary.get("closed_trades"),
            "starting_equity": summary.get("starting_equity"),
            "ending_equity": summary.get("ending_equity"),
            "equity_sparkline": spark,
            "equity_curve_points": summary.get("equity_curve_points") or len(curve),
        },
        "ranks": ranks,
        "sample_note": (
            "Rankings use PAPER closed trades only. Small sample sizes are shown honestly. "
            "Never treat this as live audited performance."
        ),
        "disclaimer": summary.get("disclaimer") or (
            "PAPER performance — not live audited. Simulated fills with configured fees/slippage."
        ),
    }


def leaderboard_html(payload: Optional[Dict[str, Any]] = None) -> str:
    """Minimal static HTML share card for screenshots."""
    data = payload or build_paper_leaderboard()
    wm = data.get("watermark") or WATERMARK
    port = data.get("portfolio") or {}
    ranks = data.get("ranks") or []
    spark = port.get("equity_sparkline") or []
    ret = port.get("return_pct")
    ret_s = f"{ret * 100:.2f}%" if isinstance(ret, (int, float)) else "—"
    wr = port.get("win_rate")
    wr_s = f"{wr * 100:.1f}%" if isinstance(wr, (int, float)) else "—"
    dd = port.get("max_drawdown_pct")
    dd_s = f"{dd * 100:.2f}%" if isinstance(dd, (int, float)) else "—"
    spark_pts = ""
    if len(spark) >= 2:
        lo, hi = min(spark), max(spark)
        span = (hi - lo) or 1.0
        w, h = 280, 48
        coords = []
        for i, v in enumerate(spark):
            x = i * (w / (len(spark) - 1))
            y = h - ((float(v) - lo) / span) * (h - 4) - 2
            coords.append(f"{x:.1f},{y:.1f}")
        spark_pts = f'<polyline fill="none" stroke="#3b82f6" stroke-width="2" points="{" ".join(coords)}" />'

    rows = []
    for i, r in enumerate(ranks[:12], 1):
        exp = r.get("expectancy")
        exp_s = f"{exp:.4f}" if isinstance(exp, (int, float)) else "—"
        wr_r = r.get("win_rate")
        wr_rs = f"{wr_r * 100:.0f}%" if isinstance(wr_r, (int, float)) else "—"
        rows.append(
            f"<tr><td>{i}</td><td>{r.get('name') or r.get('strategy_id')}</td>"
            f"<td>{r.get('status') or '—'}</td><td>{r.get('sample_size') or 0}</td>"
            f"<td>{wr_rs}</td><td>{exp_s}</td></tr>"
        )
    rows_html = "\n".join(rows) or "<tr><td colspan='6'>No scored PAPER strategies yet</td></tr>"
    period = data.get("period") or {}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>GAMMA-R PAPER Leaderboard</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; background:#0b1220; color:#e5e7eb; margin:0; padding:24px; }}
  .card {{ max-width:640px; margin:0 auto; background:#111827; border:1px solid #1f2937; border-radius:12px; padding:20px; }}
  .wm {{ display:inline-block; background:#7c2d12; color:#fed7aa; font-weight:700; font-size:12px; letter-spacing:.04em;
         padding:4px 10px; border-radius:999px; text-transform:uppercase; }}
  h1 {{ font-size:20px; margin:12px 0 4px; }}
  .muted {{ color:#9ca3af; font-size:13px; }}
  .metrics {{ display:flex; gap:16px; flex-wrap:wrap; margin:16px 0; }}
  .m {{ background:#0b1220; border-radius:8px; padding:10px 12px; min-width:90px; }}
  .m b {{ display:block; font-size:18px; color:#93c5fd; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:12px; }}
  th, td {{ text-align:left; padding:8px 6px; border-bottom:1px solid #1f2937; }}
  th {{ color:#9ca3af; font-weight:600; }}
  svg {{ width:100%; height:48px; margin-top:8px; }}
</style>
</head>
<body>
  <div class="card">
    <span class="wm">{wm}</span>
    <h1>GAMMA-R strategy ranks</h1>
    <p class="muted">Period: {period.get('start') or '—'} → {period.get('end') or '—'} · Generated {data.get('generated_at')}</p>
    <div class="metrics">
      <div class="m"><span class="muted">Return</span><b>{ret_s}</b></div>
      <div class="m"><span class="muted">Win rate</span><b>{wr_s}</b></div>
      <div class="m"><span class="muted">Max DD</span><b>{dd_s}</b></div>
      <div class="m"><span class="muted">Closed</span><b>{port.get('closed_trades') or 0}</b></div>
    </div>
    <svg viewBox="0 0 280 48" preserveAspectRatio="none">{spark_pts}</svg>
    <table>
      <thead><tr><th>#</th><th>Strategy</th><th>Status</th><th>n</th><th>Win%</th><th>Expectancy</th></tr></thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <p class="muted" style="margin-top:16px">{data.get('disclaimer')}</p>
  </div>
</body>
</html>
"""
