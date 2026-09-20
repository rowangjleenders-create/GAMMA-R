"""
Light durable co-pilot memory (preferences, tickers, strategy interest, outcomes).

Persists under data/copilot_memory.json. Never stores API keys / secrets.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MEMORY_PATH = DATA_DIR / "copilot_memory.json"

_SECRET_RE = re.compile(
    r"(api[_-]?key|apikey|secret|password|token|private[_-]?key|bearer\s+\S+|sk-[A-Za-z0-9]+)",
    re.I,
)

# Soft preference extractors from chat text
_PREF_PATTERNS = (
    (r"\bprefer(?:s|ring)?\s+(tech|technology|software|semiconductor)s?\b", "prefer_sectors", "tech"),
    (r"\bprefer(?:s|ring)?\s+(finance|financial|bank)s?\b", "prefer_sectors", "finance"),
    (r"\bprefer(?:s|ring)?\s+(energy|oil)\b", "prefer_sectors", "energy"),
    (r"\bprefer(?:s|ring)?\s+(healthcare|health)\b", "prefer_sectors", "healthcare"),
    (r"\bno\s+(biotech|bio)\b", "avoid_sectors", "biotech"),
    (r"\bavoid(?:s|ing)?\s+(biotech|bio)\b", "avoid_sectors", "biotech"),
    (r"\bno\s+(meme|penny)\s*stocks?\b", "avoid_themes", "meme"),
    (r"\b(low|conservative)\s+risk\b", "risk_comfort", "low"),
    (r"\b(medium|moderate)\s+risk\b", "risk_comfort", "medium"),
    (r"\b(high|aggressive)\s+risk\b", "risk_comfort", "high"),
    (r"\brisk\s+(averse|aversion)\b", "risk_comfort", "low"),
    (r"\binterested\s+in\s+(momentum|mean[_ ]?reversion|breakout|relative[_ ]?strength|pairs|earnings[_ ]?drift|fx[_ ]?mean|vol[_ ]?target)\b", "strategy_interest", None),
    (r"\blike\s+(momentum|mean[_ ]?reversion|breakout|relative[_ ]?strength|pairs)\b", "strategy_interest", None),
    (r"\bfocus\s+on\s+(momentum|mean[_ ]?reversion|breakout|relative[_ ]?strength|pairs)\b", "strategy_interest", None),
    (r"\btoggle\s+(?:on\s+)?(momentum|mean[_ ]?reversion|breakout|relative[_ ]?strength|pairs|earnings[_ ]?drift|fx[_ ]?mean[_ ]?reversion|vol[_ ]?target)\b", "strategy_interest", None),
)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "preferences": {
            "prefer_sectors": [],
            "avoid_sectors": [],
            "avoid_themes": [],
            "risk_comfort": None,
            "notes": [],
        },
        "strategy_interest": [],  # strategy_ids user mentioned positively
        "last_tickers": [],  # recent tickers discussed
        "facts": [],  # free-form short facts [{text, at}]
        "outcomes": [],  # short paper-close notes [{ticker, pnl, reason, at}]
    }


def memory_enabled() -> bool:
    try:
        from .config import get_runtime_config

        return bool(getattr(get_runtime_config(), "copilot_memory_enabled", True))
    except Exception:
        return True


def load_memory() -> Dict[str, Any]:
    base = _default()
    if not MEMORY_PATH.exists():
        return base
    try:
        raw = json.loads(MEMORY_PATH.read_text())
        if not isinstance(raw, dict):
            return base
        for k, v in base.items():
            if k not in raw:
                raw[k] = v
        prefs = raw.get("preferences") or {}
        for pk, pv in base["preferences"].items():
            prefs.setdefault(pk, pv)
        raw["preferences"] = prefs
        return raw
    except (json.JSONDecodeError, OSError):
        return base


def save_memory(mem: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    mem = dict(mem)
    mem["updated_at"] = _utc()
    # Hard redact before write
    blob = json.dumps(mem, default=str)
    if _SECRET_RE.search(blob):
        mem = _scrub_obj(mem)
    MEMORY_PATH.write_text(json.dumps(mem, indent=2, default=str))


def _scrub_text(s: str) -> str:
    return _SECRET_RE.sub("***", s or "")


def _scrub_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in ("secret", "api_key", "apikey", "password", "token", "private")):
                out[k] = "***"
            else:
                out[k] = _scrub_obj(v)
        return out
    if isinstance(obj, list):
        return [_scrub_obj(x) for x in obj]
    if isinstance(obj, str):
        return _scrub_text(obj)
    return obj


def compact_memory(mem: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Small JSON-safe summary for prompts / tools."""
    m = mem or load_memory()
    prefs = m.get("preferences") or {}
    return {
        "prefer_sectors": list(prefs.get("prefer_sectors") or [])[:8],
        "avoid_sectors": list(prefs.get("avoid_sectors") or [])[:8],
        "avoid_themes": list(prefs.get("avoid_themes") or [])[:6],
        "risk_comfort": prefs.get("risk_comfort"),
        "notes": list(prefs.get("notes") or [])[-5:],
        "strategy_interest": list(m.get("strategy_interest") or [])[:10],
        "last_tickers": list(m.get("last_tickers") or [])[:10],
        "facts": [f.get("text") if isinstance(f, dict) else str(f) for f in (m.get("facts") or [])[-8:]],
        "recent_outcomes": (m.get("outcomes") or [])[-5:],
        "updated_at": m.get("updated_at"),
    }


def remember_fact(text: str, *, kind: str = "fact") -> Dict[str, Any]:
    """Store a short free-form fact (redacted). Returns compact memory."""
    if not memory_enabled():
        return compact_memory()
    text = _scrub_text((text or "").strip())
    if not text or len(text) > 400:
        text = text[:400]
    if not text:
        return compact_memory()
    mem = load_memory()
    facts = list(mem.get("facts") or [])
    facts.append({"text": text, "kind": kind, "at": _utc()})
    mem["facts"] = facts[-40:]
    save_memory(mem)
    return compact_memory(mem)


def note_outcome(
    ticker: str,
    *,
    pnl: Optional[float] = None,
    reason: str = "",
    strategy_id: Optional[str] = None,
) -> None:
    """Hook from paper closes — short outcome note."""
    if not memory_enabled():
        return
    try:
        mem = load_memory()
        outcomes = list(mem.get("outcomes") or [])
        outcomes.append(
            {
                "ticker": str(ticker or "").upper()[:12],
                "pnl": round(float(pnl), 2) if isinstance(pnl, (int, float)) else None,
                "reason": _scrub_text(str(reason or ""))[:80],
                "strategy_id": strategy_id,
                "at": _utc(),
            }
        )
        mem["outcomes"] = outcomes[-30:]
        # Keep ticker in last_tickers
        t = str(ticker or "").upper()
        if t:
            lt = [x for x in (mem.get("last_tickers") or []) if x != t]
            lt.insert(0, t)
            mem["last_tickers"] = lt[:15]
        save_memory(mem)
    except Exception:
        pass


def touch_ticker(ticker: str) -> None:
    if not memory_enabled() or not ticker:
        return
    try:
        mem = load_memory()
        t = str(ticker).upper().replace(".", "-")[:12]
        lt = [x for x in (mem.get("last_tickers") or []) if x != t]
        lt.insert(0, t)
        mem["last_tickers"] = lt[:15]
        save_memory(mem)
    except Exception:
        pass


def _norm_sid(raw: str) -> str:
    s = re.sub(r"[\s-]+", "_", (raw or "").lower().strip())
    aliases = {
        "mean_reversion": "mean_reversion",
        "meanreversion": "mean_reversion",
        "relative_strength": "relative_strength",
        "rs": "relative_strength",
        "earnings_drift": "earnings_drift",
        "pead": "earnings_drift",
        "fx_mean": "fx_mean_reversion",
        "fx_mean_reversion": "fx_mean_reversion",
        "vol_target": "vol_target",
        "voltarget": "vol_target",
    }
    return aliases.get(s, s)


def ingest_chat_preferences(message: str) -> List[str]:
    """
    Parse light prefs from a user message. Returns list of human-readable updates applied.
    """
    if not memory_enabled():
        return []
    q = (message or "").strip().lower()
    if not q:
        return []
    mem = load_memory()
    prefs = dict(mem.get("preferences") or {})
    updates: List[str] = []

    for pat, key, fixed in _PREF_PATTERNS:
        m = re.search(pat, q)
        if not m:
            continue
        if key == "risk_comfort":
            prefs["risk_comfort"] = fixed
            updates.append(f"risk_comfort={fixed}")
        elif key == "strategy_interest":
            sid = _norm_sid(m.group(1))
            si = list(mem.get("strategy_interest") or [])
            if sid and sid not in si:
                si.insert(0, sid)
                mem["strategy_interest"] = si[:12]
                updates.append(f"strategy_interest+={sid}")
        else:
            val = fixed if fixed is not None else (m.group(1) if m.lastindex else None)
            if not val:
                continue
            bucket = list(prefs.get(key) or [])
            if val not in bucket:
                bucket.append(val)
                prefs[key] = bucket[:12]
                updates.append(f"{key}+={val}")

    # Explicit "remember that …" / "please remember …" / "note: …"
    # Avoid matching questions like "what do you remember …"
    rem = re.search(
        r"(?:(?:please\s+)?remember\s+that|remember:\s*|note that|note:)\s+(.+)$",
        q,
    )
    if rem and not q.strip().startswith(("what ", "how ", "do you ", "can you ")):
        fact = _scrub_text(rem.group(1).strip()[:240])
        if fact:
            notes = list(prefs.get("notes") or [])
            if fact not in notes:
                notes.append(fact)
                prefs["notes"] = notes[-12:]
                facts = list(mem.get("facts") or [])
                facts.append({"text": fact, "kind": "pref", "at": _utc()})
                mem["facts"] = facts[-40:]
                updates.append(f"note={fact[:60]}")

    if updates:
        mem["preferences"] = prefs
        save_memory(mem)
    return updates


def memory_prompt_block(mem: Optional[Dict[str, Any]] = None) -> str:
    c = compact_memory(mem)
    parts = []
    if c.get("prefer_sectors"):
        parts.append(f"prefer sectors: {', '.join(c['prefer_sectors'])}")
    if c.get("avoid_sectors"):
        parts.append(f"avoid sectors: {', '.join(c['avoid_sectors'])}")
    if c.get("avoid_themes"):
        parts.append(f"avoid themes: {', '.join(c['avoid_themes'])}")
    if c.get("risk_comfort"):
        parts.append(f"risk comfort: {c['risk_comfort']}")
    if c.get("strategy_interest"):
        parts.append(f"strategy interest: {', '.join(c['strategy_interest'])}")
    if c.get("last_tickers"):
        parts.append(f"recent tickers: {', '.join(c['last_tickers'])}")
    if c.get("facts"):
        parts.append("facts: " + "; ".join(str(x) for x in c["facts"][-4:]))
    if c.get("recent_outcomes"):
        bits = []
        for o in c["recent_outcomes"][-3:]:
            if isinstance(o, dict):
                bits.append(f"{o.get('ticker')} pnl={o.get('pnl')} ({o.get('reason')})")
        if bits:
            parts.append("recent paper outcomes: " + "; ".join(bits))
    if not parts:
        return "(no stored preferences yet)"
    return " | ".join(parts)
