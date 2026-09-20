"""
Import fills executed OUTSIDE the app (CSV / JSON / optional Alpaca history).

- Journaled with origin="external" (distinct from app paper fills).
- Included in learning + scoreboard; paper portfolio equity stays separate.
- Dedupes by broker_id or hash(symbol, side, qty, price, time).
- Never places live or paper orders from imports (learning only).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IMPORT_META_PATH = DATA_DIR / "external_import_meta.json"
EXTERNAL_MIRROR_PATH = DATA_DIR / "external_trades.jsonl"

_SIDE_SELL = {"sell", "s", "short", "sold", "sale"}

_COL_ALIASES = {
    "symbol": {"symbol", "ticker", "sym", "instrument", "asset"},
    "side": {"side", "action", "bs", "buy_sell", "direction"},
    "qty": {"qty", "quantity", "shares", "size", "amount", "fill_qty"},
    "price": {"price", "fill_price", "avg_price", "avg_fill_price", "px", "fill_px"},
    "time": {
        "time", "timestamp", "datetime", "date", "filled_at", "filled_at_utc",
        "transaction_time", "executed_at", "ts",
    },
    "fees": {"fees", "commission", "fee", "total_fees", "comm"},
    "strategy": {"strategy", "strategy_id", "strategy_tag", "tag", "algo"},
    "notes": {"notes", "note", "comment", "memo", "description"},
    "broker_id": {
        "broker_id", "order_id", "id", "fill_id", "client_order_id", "activity_id",
    },
    "entry_price": {"entry_price", "entry", "avg_entry"},
    "exit_price": {"exit_price", "exit", "avg_exit"},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_header(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (k or "").strip().lower()).strip("_")


def feature_info() -> Dict[str, Any]:
    return {
        "external_trades_import": True,
        "formats": ["csv", "json"],
        "alpaca_optional": True,
        "alpaca_keys_present": alpaca_credentials_present(),
        "alpaca_import_available": alpaca_credentials_present(),
        "live_from_import": False,
        "live_trading_from_import": False,
        "endpoints": [
            "POST /trades/import",
            "POST /trades/import/alpaca",
            "GET /trades/external",
            "GET /trades/learning-stats",
        ],
        "note": "Import is learning-only; never auto-places live or paper orders.",
    }


def alpaca_credentials_present() -> bool:
    key = (
        os.environ.get("ALPACA_API_KEY", "").strip()
        or os.environ.get("ALPACA_KEY_ID", "").strip()
        or os.environ.get("ALPACA_API_KEY_ID", "").strip()
    )
    secret = (
        os.environ.get("ALPACA_API_SECRET", "").strip()
        or os.environ.get("ALPACA_SECRET_KEY", "").strip()
        or os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    )
    return bool(key and secret)


def trade_dedupe_key(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    time: str,
    broker_id: Optional[str] = None,
) -> str:
    if broker_id:
        return f"broker:{str(broker_id).strip()}"
    raw = (
        f"{symbol.upper()}|{side.lower()}|"
        f"{float(qty):.8g}|{float(price):.8g}|{str(time).strip()}"
    )
    return "hash:" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def load_import_meta() -> Dict[str, Any]:
    if not IMPORT_META_PATH.exists():
        return {"last_import": None, "total_imported": 0}
    try:
        return json.loads(IMPORT_META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"last_import": None, "total_imported": 0}


def _save_import_meta(patch: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    meta = load_import_meta()
    meta.update(patch)
    meta["updated_at"] = _utc_now()
    IMPORT_META_PATH.write_text(json.dumps(meta, indent=2))


def _map_headers(headers: List[str]) -> Dict[str, str]:
    normed = {_norm_header(h): h for h in headers if h}
    out: Dict[str, str] = {}
    for canon, aliases in _COL_ALIASES.items():
        for a in aliases:
            if a in normed:
                out[canon] = normed[a]
                break
    return out


def _parse_side(raw: Any) -> str:
    s = str(raw or "buy").strip().lower()
    return "sell" if s in _SIDE_SELL else "buy"


def _parse_float(raw: Any, default: float = 0.0) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(str(raw).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return default


def normalize_fill(
    row: Dict[str, Any], *, default_strategy: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper().replace(".", "-")
    if not symbol:
        return None
    side = _parse_side(row.get("side") or row.get("action"))
    qty = abs(_parse_float(row.get("qty") or row.get("shares") or row.get("quantity")))
    price = abs(_parse_float(row.get("price") or row.get("fill_price") or row.get("avg_price")))
    entry_price = row.get("entry_price")
    exit_price = row.get("exit_price")
    if entry_price is not None:
        entry_price = abs(_parse_float(entry_price))
    if exit_price is not None:
        exit_price = abs(_parse_float(exit_price))
    if qty <= 0:
        return None
    if price <= 0 and not (entry_price and exit_price):
        return None
    if price <= 0 and entry_price and exit_price:
        price = float(exit_price)
    time_s = str(
        row.get("time")
        or row.get("timestamp")
        or row.get("datetime")
        or row.get("date")
        or _utc_now()
    ).strip()
    fees = abs(_parse_float(row.get("fees") or row.get("commission") or 0))
    strategy = (
        str(
            row.get("strategy")
            or row.get("strategy_id")
            or row.get("strategy_tag")
            or default_strategy
            or ""
        ).strip()
        or None
    )
    notes = str(row.get("notes") or row.get("note") or row.get("comment") or "").strip()[:240]
    broker_id = row.get("broker_id") or row.get("order_id") or row.get("id") or row.get("fill_id")
    broker_id = str(broker_id).strip() if broker_id not in (None, "") else None
    dedupe = trade_dedupe_key(
        symbol=symbol, side=side, qty=qty, price=price, time=time_s, broker_id=broker_id
    )
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "time": time_s,
        "fees": fees,
        "strategy_id": strategy,
        "notes": notes,
        "broker_id": broker_id,
        "dedupe_key": dedupe,
        "origin": "external",
        "source": "external",
    }


def parse_csv_trades(
    text: str, *, default_strategy: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    if not (text or "").strip():
        return [], ["empty CSV"]
    try:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            return [], ["CSV has no header row"]
        mapping = _map_headers(list(reader.fieldnames))
        if "symbol" not in mapping or "qty" not in mapping:
            return [], [
                f"Need symbol + qty columns (got {list(reader.fieldnames)}). "
                "Aliases: ticker, shares, fill_price, …"
            ]
        if "price" not in mapping and not (
            "entry_price" in mapping and "exit_price" in mapping
        ):
            return [], ["Need price (or entry_price+exit_price) column"]
        out: List[Dict[str, Any]] = []
        for i, raw in enumerate(reader, start=2):
            mapped = {canon: raw.get(hdr) for canon, hdr in mapping.items()}
            norm = normalize_fill(mapped, default_strategy=default_strategy)
            if not norm:
                errors.append(f"row {i}: invalid/missing fields")
                continue
            out.append(norm)
        return out, errors
    except Exception as e:
        return [], [f"CSV parse failed: {type(e).__name__}: {e}"]


def parse_json_trades(
    payload: Any, *, default_strategy: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as e:
            return [], [f"JSON parse failed: {e}"]
    if isinstance(payload, dict):
        payload = (
            payload.get("trades")
            or payload.get("fills")
            or payload.get("orders")
            or payload.get("entries")
            or []
        )
    if not isinstance(payload, list):
        return [], ["JSON must be a list of trades or {trades: [...]}"]
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(payload):
        if not isinstance(raw, dict):
            errors.append(f"item {i}: not an object")
            continue
        norm = normalize_fill(raw, default_strategy=default_strategy)
        if not norm:
            errors.append(f"item {i}: invalid/missing symbol, qty, or price")
            continue
        out.append(norm)
    return out, errors


def _existing_dedupe_keys() -> set:
    from .learning import load_journal

    keys: set = set()
    # Mirror file holds raw fill dedupe keys
    if EXTERNAL_MIRROR_PATH.exists():
        try:
            for line in EXTERNAL_MIRROR_PATH.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("dedupe_key"):
                    keys.add(str(row["dedupe_key"]))
                if row.get("broker_id"):
                    keys.add(f"broker:{row['broker_id']}")
        except OSError:
            pass
    for e in load_journal():
        if not isinstance(e, dict):
            continue
        ctx = e.get("context") or {}
        for candidate in (
            e.get("dedupe_key"),
            ctx.get("dedupe_key"),
            f"broker:{e['broker_id']}" if e.get("broker_id") else None,
            f"broker:{ctx['broker_id']}" if ctx.get("broker_id") else None,
        ):
            if candidate:
                keys.add(str(candidate))
                if not str(candidate).startswith("broker:") and e.get("broker_id"):
                    keys.add(f"broker:{e['broker_id']}")
        # Also accept trade_dedupe_key form broker:
        if e.get("broker_id"):
            keys.add(f"broker:{e['broker_id']}")
        if ctx.get("broker_id"):
            keys.add(f"broker:{ctx['broker_id']}")
        if (e.get("origin") or e.get("source")) == "external" and e.get("ticker"):
            try:
                side = str(ctx.get("side") or e.get("side") or "buy")
                keys.add(
                    trade_dedupe_key(
                        symbol=str(e["ticker"]),
                        side=side,
                        qty=float(e.get("shares") or 0),
                        price=float(e.get("exit") or e.get("entry") or 0),
                        time=str(
                            e.get("closed_at")
                            or e.get("opened_at")
                            or e.get("recorded_at")
                            or ""
                        ),
                    )
                )
            except (TypeError, ValueError):
                pass
    return keys


def validate_fills(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    existing = _existing_dedupe_keys()
    accepted: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    invalid: List[Any] = []
    seen: set = set()
    for r in rows:
        norm = r if r.get("dedupe_key") and r.get("symbol") else normalize_fill(r or {})
        if not norm:
            invalid.append(r)
            continue
        dk = norm["dedupe_key"]
        if dk in existing or dk in seen:
            duplicates.append(norm)
            continue
        seen.add(dk)
        accepted.append(norm)
    return {
        "ok": True,
        "dry_run": True,
        "origin": "external",
        "parsed": len(rows),
        "would_import": len(accepted),
        "duplicates": len(duplicates),
        "invalid": len(invalid),
        "sample": accepted[:8],
        "duplicate_sample": duplicates[:3],
        "live_trading": False,
        "note": "Learning-only import — never auto-places live or paper orders.",
    }


def _fill_to_kwargs(fill: Dict[str, Any]) -> Dict[str, Any]:
    symbol = fill["symbol"]
    side = fill.get("side") or "buy"
    qty = int(max(1, round(float(fill["qty"]))))
    price = float(fill["price"])
    fees_amt = float(fill.get("fees") or 0)
    entry_px = fill.get("entry_price")
    exit_px = fill.get("exit_price")
    if entry_px is not None and exit_px is not None:
        entry = float(entry_px)
        exit_ = float(exit_px)
        if "short" in str(fill.get("notes") or "").lower() or side in ("cover", "short"):
            ret = (entry - exit_) / entry if entry else 0.0
        else:
            ret = (exit_ - entry) / entry if entry else 0.0
    else:
        entry = price
        exit_ = price
        ret = 0.0
        m = re.search(
            r"pnl\s*[:=]\s*([+-]?\d+(?:\.\d+)?)", str(fill.get("notes") or ""), re.I
        )
        if m:
            pnl = float(m.group(1))
            notional = price * qty
            ret = pnl / notional if notional else 0.0
            exit_ = entry * (1.0 + ret)

    strategy_id = fill.get("strategy_id")
    context = {
        "origin": "external",
        "side": side,
        "broker_id": fill.get("broker_id"),
        "dedupe_key": fill.get("dedupe_key"),
        "notes": fill.get("notes") or "",
        "strategy_id": strategy_id,
        "imported_at": _utc_now(),
        "learning_only": True,
        "never_auto_live": True,
    }
    signal_params = {"strategy_id": strategy_id} if strategy_id else None
    signed = (entry - exit_) if (
        "short" in str(fill.get("notes") or "").lower() or side in ("cover", "short")
    ) else (exit_ - entry)
    fees = {
        "entry_fees": round(fees_amt / 2.0, 4),
        "exit_fees": round(fees_amt / 2.0, 4),
        "total_fees": round(fees_amt, 4),
        "gross_pnl": round(signed * qty, 4),
        "net_pnl": round(signed * qty - fees_amt, 4),
    }
    return dict(
        ticker=symbol,
        entry=entry,
        exit=exit_,
        shares=qty,
        return_pct=ret,
        exit_reason="external_import",
        opened_at=fill.get("opened_at") or fill.get("time"),
        closed_at=fill.get("closed_at") or fill.get("time"),
        source="external",
        origin="external",
        sector="Unknown",  # skip live yfinance lookup on import
        signal_params=signal_params,
        position_id=f"ext-{(fill.get('dedupe_key') or '')[:32]}",
        fees=fees,
        context=context,
    )


def _append_mirror(fill: Dict[str, Any], journal_id: Optional[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = dict(fill)
    row["journal_id"] = journal_id
    row["mirrored_at"] = _utc_now()
    with EXTERNAL_MIRROR_PATH.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")



def _fifo_pair_fills(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pair buy/sell fills into closed round-trips (FIFO) when entry/exit missing.
    Rows that already have entry_price+exit_price pass through unchanged.
    Unmatched open lots are dropped (not journaled as zero-PnL closes).
    """
    closed_ready: List[Dict[str, Any]] = []
    books: Dict[str, List[Dict[str, Any]]] = {}
    ordered = sorted(fills, key=lambda f: str(f.get("time") or ""))
    for fill in ordered:
        if fill.get("entry_price") is not None and fill.get("exit_price") is not None:
            closed_ready.append(fill)
            continue
        sym = fill["symbol"]
        book = books.setdefault(sym, [])
        remaining = float(fill["qty"])
        side = fill.get("side") or "buy"
        while remaining > 1e-12 and book and book[0].get("side") != side:
            lot = book[0]
            take = min(remaining, float(lot["qty"]))
            entry_px = float(lot["price"])
            exit_px = float(fill["price"])
            if lot["side"] == "buy":
                # long close
                pass
            else:
                # short cover: entry was sell price, exit is buy
                entry_px, exit_px = float(lot["price"]), float(fill["price"])
            fee = float(lot.get("fees") or 0) * (take / float(lot["qty"])) + float(
                fill.get("fees") or 0
            ) * (take / float(fill["qty"]) if fill.get("qty") else 1.0)
            paired = {
                "symbol": sym,
                "side": "sell" if lot["side"] == "buy" else "buy",
                "qty": take,
                "price": exit_px,
                "entry_price": entry_px if lot["side"] == "buy" else exit_px,
                "exit_price": exit_px if lot["side"] == "buy" else entry_px,
                "time": fill.get("time") or lot.get("time"),
                "fees": fee,
                "strategy_id": fill.get("strategy_id") or lot.get("strategy_id"),
                "notes": fill.get("notes") or lot.get("notes") or "fifo_pair",
                "broker_id": fill.get("broker_id") or lot.get("broker_id"),
                "dedupe_key": f"close:{lot.get('dedupe_key')}:{fill.get('dedupe_key')}:{take:.6g}",
                "origin": "external",
                "source": "external",
                "opened_at": lot.get("time"),
                "closed_at": fill.get("time"),
            }
            # Normalize long semantics: entry=open price, exit=close price
            if lot["side"] == "buy":
                paired["entry_price"] = float(lot["price"])
                paired["exit_price"] = float(fill["price"])
            else:
                paired["entry_price"] = float(lot["price"])  # short entry
                paired["exit_price"] = float(fill["price"])  # cover
                # return for shorts: (entry-exit)/entry handled in _fill_to_kwargs via prices
                # Mark side so _fill_to_kwargs computes short return if needed
                paired["side"] = "cover"
                paired["notes"] = (paired.get("notes") or "") + "|short"
            closed_ready.append(paired)
            lot["qty"] = float(lot["qty"]) - take
            remaining -= take
            if lot["qty"] <= 1e-12:
                book.pop(0)
        if remaining > 1e-12:
            book.append({
                **fill,
                "qty": remaining,
                "fees": float(fill.get("fees") or 0) * (
                    remaining / float(fill["qty"]) if fill.get("qty") else 1.0
                ),
            })
    return closed_ready


def import_trades(rows: List[Dict[str, Any]], *, dry_run: bool = False) -> Dict[str, Any]:
    # Dedupe raw fills first, then FIFO-pair into closed samples for learning.
    existing = _existing_dedupe_keys()
    accepted: List[Dict[str, Any]] = []
    duplicates = 0
    seen: set = set()
    for r in rows:
        norm = r if r.get("dedupe_key") and r.get("symbol") else normalize_fill(r or {})
        if not norm:
            continue
        dk = norm["dedupe_key"]
        if dk in existing or dk in seen:
            duplicates += 1
            continue
        seen.add(dk)
        accepted.append(norm)

    closed = _fifo_pair_fills(accepted)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "origin": "external",
            "parsed": len(rows),
            "would_import": len(closed),
            "new_fills": len(accepted),
            "duplicate_fills": duplicates,
            "duplicates": duplicates,
            "closed_round_trips": len(closed),
            "journaled": len(closed),
            "invalid": max(0, len(rows) - len(accepted) - duplicates),
            "sample": closed[:8],
            "live_trading": False,
            "note": "Learning-only import — never auto-places live or paper orders.",
        }

    from .learning import record_closed_trade, load_journal, save_journal

    for raw in accepted:
        _append_mirror(raw, None)

    imported_rows: List[Dict[str, Any]] = []
    for fill in closed:
        kw = _fill_to_kwargs(fill)
        result = record_closed_trade(**kw)
        entry = result.get("entry") if isinstance(result, dict) else result
        # Stamp dedupe onto journal row if needed
        try:
            journal = load_journal()
            jid = (entry or {}).get("id") if isinstance(entry, dict) else None
            for e in journal:
                if jid and e.get("id") == jid:
                    e["dedupe_key"] = fill.get("dedupe_key")
                    e["broker_id"] = fill.get("broker_id")
                    e["origin"] = "external"
                    e["source"] = "external"
                    if fill.get("strategy_id"):
                        e["strategy_id"] = fill["strategy_id"]
                    break
            save_journal(journal)
        except Exception:
            pass
        if isinstance(entry, dict):
            imported_rows.append(entry)
            _append_mirror(fill, entry.get("id"))
        else:
            imported_rows.append(kw)
            _append_mirror(fill, None)
        try:
            from .copilot_memory import note_outcome

            pnl = (kw.get("fees") or {}).get("net_pnl")
            note_outcome(
                fill["symbol"],
                pnl=pnl,
                reason=f"external:{fill.get('side')}:{fill.get('notes') or 'import'}",
                strategy_id=fill.get("strategy_id"),
            )
        except Exception:
            pass

    meta = load_import_meta()
    _save_import_meta(
        {
            "last_import": {
                "at": _utc_now(),
                "imported": len(imported_rows),
                "duplicates": duplicates,
                "parsed": len(rows),
            },
            "total_imported": int(meta.get("total_imported") or 0) + len(imported_rows),
        }
    )
    return {
        "ok": True,
        "dry_run": False,
        "origin": "external",
        "imported": len(imported_rows),
        "journaled": len(imported_rows),
        "new_fills": len(accepted),
        "closed_round_trips": len(closed),
        "duplicates": duplicates,
        "duplicate_fills": duplicates,
        "parsed": len(rows),
        "entries": imported_rows[:25],
        "live_trading": False,
        "at": _utc_now(),
        "note": "External fills stored for learning only — no live/paper orders placed.",
    }


def import_from_content(
    *,
    format: str = "csv",
    content: str = "",
    dry_run: bool = False,
    default_strategy: Optional[str] = None,
) -> Dict[str, Any]:
    fmt = (format or "csv").strip().lower()
    if fmt == "json":
        rows, errors = parse_json_trades(content, default_strategy=default_strategy)
    else:
        rows, errors = parse_csv_trades(content, default_strategy=default_strategy)
    if not rows and errors:
        return {"ok": False, "error": "; ".join(errors), "errors": errors, "imported": 0}
    result = import_trades(rows, dry_run=dry_run)
    if errors:
        result["parse_warnings"] = errors
    return result


def fetch_alpaca_fills(*, limit: int = 50) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not alpaca_credentials_present():
        return [], ["Alpaca keys not set"]
    key = (
        os.environ.get("ALPACA_API_KEY", "").strip()
        or os.environ.get("ALPACA_KEY_ID", "").strip()
        or os.environ.get("ALPACA_API_KEY_ID", "").strip()
    )
    secret = (
        os.environ.get("ALPACA_API_SECRET", "").strip()
        or os.environ.get("ALPACA_SECRET_KEY", "").strip()
        or os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    )
    base = (
        os.environ.get("ALPACA_BASE_URL", "").strip()
        or os.environ.get("ALPACA_API_BASE", "").strip()
        or "https://paper-api.alpaca.markets"
    ).rstrip("/")
    qs = urllib.parse.urlencode(
        {"direction": "desc", "page_size": min(100, max(1, int(limit)))}
    )
    url = f"{base}/v2/account/activities/FILL?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return [], [f"Alpaca HTTP {e.code}: {e.reason}"]
    except Exception as e:
        return [], [f"Alpaca fetch failed: {type(e).__name__}: {e}"]
    if not isinstance(data, list):
        return [], ["Unexpected Alpaca response shape"]
    out: List[Dict[str, Any]] = []
    for a in data[:limit]:
        if not isinstance(a, dict):
            continue
        norm = normalize_fill(
            {
                "symbol": a.get("symbol"),
                "qty": a.get("qty"),
                "price": a.get("price") or a.get("avg_fill_price"),
                "side": a.get("side") or a.get("order_side"),
                "time": a.get("transaction_time") or a.get("timestamp") or a.get("filled_at"),
                "broker_id": a.get("id") or a.get("order_id"),
                "fees": a.get("commission") or 0,
                "notes": "alpaca_fill",
                "strategy": a.get("strategy_id"),
            }
        )
        if norm:
            out.append(norm)
    return out, []


def import_from_alpaca(*, dry_run: bool = False, limit: int = 50) -> Dict[str, Any]:
    rows, errors = fetch_alpaca_fills(limit=limit)
    if not rows:
        return {
            "ok": False,
            "error": "; ".join(errors) if errors else "no fills",
            "errors": errors,
            "imported": 0,
            "live_trading": False,
            "note": "Read-only Alpaca history — import does not place orders.",
        }
    result = import_trades(rows, dry_run=dry_run)
    result["alpaca_fetched"] = len(rows)
    if errors:
        result["parse_warnings"] = errors
    result["note"] = (
        "Alpaca history imported for learning only — never auto-places live orders."
    )
    result["live_trading"] = False
    return result


def load_external_trades(limit: int = 50) -> List[Dict[str, Any]]:
    from .learning import load_journal

    lim = max(1, min(500, int(limit)))
    rows = [
        e
        for e in load_journal()
        if isinstance(e, dict)
        and (e.get("origin") == "external" or e.get("source") == "external")
    ]
    return list(reversed(rows[-lim:]))


def learning_stats_by_origin() -> Dict[str, Any]:
    from .learning import load_journal

    entries = [e for e in load_journal() if isinstance(e, dict)]

    def _bucket(ents: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(ents)
        wins = sum(1 for e in ents if float(e.get("return_pct") or 0) > 0)
        by_strat: Dict[str, Dict[str, Any]] = {}
        for e in ents:
            sid = str(
                e.get("strategy_id")
                or (e.get("context") or {}).get("strategy_id")
                or (e.get("signal_params") or {}).get("strategy_id")
                or "unknown"
            )
            b = by_strat.setdefault(sid, {"count": 0, "wins": 0})
            b["count"] += 1
            if float(e.get("return_pct") or 0) > 0:
                b["wins"] += 1
        for sid, b in by_strat.items():
            b["win_rate"] = round(b["wins"] / b["count"], 4) if b["count"] else 0.0
        return {
            "count": n,
            "wins": wins,
            "losses": n - wins,
            "win_rate": round(wins / n, 4) if n else 0.0,
            "unlearned": sum(1 for e in ents if not e.get("learned")),
            "by_strategy": by_strat,
        }

    paper = [e for e in entries if (e.get("origin") or "paper") != "external"]
    external = [
        e for e in entries if e.get("origin") == "external" or e.get("source") == "external"
    ]
    meta = load_import_meta()
    last = meta.get("last_import")
    ext_bucket = _bucket(external)
    ext_bucket["last_import"] = last
    fills_n = 0
    if EXTERNAL_MIRROR_PATH.exists():
        try:
            fills_n = sum(
                1 for line in EXTERNAL_MIRROR_PATH.read_text().splitlines() if line.strip()
            )
        except OSError:
            fills_n = 0
    ext_bucket["fills_stored"] = fills_n
    return {
        "paper": _bucket(paper),
        "external": ext_bucket,
        "combined": _bucket(entries),
        "last_import": last,
        "updated_at": _utc_now(),
        "note": (
            "Combined learning samples include external imports. "
            "Paper portfolio equity remains app-paper only. "
            "Imports never auto-trade live."
        ),
    }


def external_performance_blurb(
    limit: int = 10, strategy_id: Optional[str] = None
) -> str:
    stats = learning_stats_by_origin()
    ext = stats.get("external") or {}
    by = ext.get("by_strategy") or {}
    if strategy_id and strategy_id in by:
        b = by[strategy_id]
        n, wr = b.get("count") or 0, b.get("win_rate")
        if n:
            return f"your last {n} external {strategy_id} trades WR={float(wr)*100:.0f}%"
    # Prefer last N from journal for "last 10" phrasing
    rows = load_external_trades(limit=limit)
    if strategy_id:
        sid = strategy_id.lower()
        rows = [
            e
            for e in rows
            if sid
            in str(
                e.get("strategy_id")
                or (e.get("context") or {}).get("strategy_id")
                or ""
            ).lower()
        ]
    n = len(rows)
    if not n:
        n = int(ext.get("count") or 0)
        wr = ext.get("win_rate")
        if not n:
            return "no external trades imported yet"
        return f"your external trades n={n} WR={float(wr or 0)*100:.0f}%"
    wins = sum(1 for e in rows if float(e.get("return_pct") or 0) > 0)
    wr = wins / n
    tag = f" {strategy_id}" if strategy_id else ""
    return f"your last {n} external{tag} trades WR={wr*100:.0f}%"

# Compatibility aliases
parse_csv = parse_csv_trades
parse_json = parse_json_trades
EXTERNAL_PATH = EXTERNAL_MIRROR_PATH
save_import_meta = _save_import_meta
