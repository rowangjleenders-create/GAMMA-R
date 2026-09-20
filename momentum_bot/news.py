"""
News sentiment analysis (free/low-cost sources, no look-ahead in backtests).

Sources:
  - RSS feeds from major financial outlets (default, no API key)
  - Optional Finnhub / NewsAPI via FINNHUB_API_KEY or NEWSAPI_KEY env vars

Sentiment:
  - Default: VADER (vaderSentiment) — lightweight, CPU-only
  - Optional FinBERT: documented hook if `transformers` + torch installed

Aggregation: per-ticker and per-sector over 24h and 7d windows; spike detection.
Entry: strong positive can boost priority; sudden negative → warning / exit flag.
Backtests must pass as_of timestamp so ONLY news published before that time is used.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

# Optional deps
try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None  # type: ignore

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError:  # pragma: no cover
    SentimentIntensityAnalyzer = None  # type: ignore

from .config import StrategyConfig, get_runtime_config
from .timezone_util import annotate_timestamp

# Major financial RSS feeds (free)
DEFAULT_RSS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Top News
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",  # CNBC Finance
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.nasdaq.com/feed/rssoutbound?category=Stocks",
]

# Free FX / macro feeds (no API key) — used for EOD digest + currency context
FX_MACRO_RSS = [
    "https://www.fxstreet.com/rss/news",  # FXStreet FX news
    "https://www.forexlive.com/feed",  # ForexLive
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",  # CNBC Economy (macro)
]

SECTOR_KEYWORDS = {
    "Technology": ["tech", "software", "chip", "semiconductor", "ai ", "cloud", "apple", "microsoft", "nvidia"],
    "Financials": ["bank", "fed ", "interest rate", "treasury", "fintech", "insurance"],
    "Energy": ["oil", "crude", "gas", "opec", "energy"],
    "Healthcare": ["pharma", "biotech", "fda", "drug", "health"],
    "Consumer": ["retail", "consumer", "amazon", "walmart", "spending"],
    "Industrials": ["industrial", "manufactur", "aerospace", "defense"],
}


@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    published: str  # ISO
    source: str
    tickers: List[str] = field(default_factory=list)
    sector: Optional[str] = None
    sentiment: float = 0.0  # -1..1 compound
    label: str = "neutral"  # positive|negative|neutral
    confidence: float = 0.0
    model: str = "vader"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TickerNewsAgg:
    ticker: str
    score_24h: float
    score_7d: float
    count_24h: int
    count_7d: int
    spike: bool
    shift: float  # 24h vs prior 6d avg
    headlines: List[Dict[str, Any]] = field(default_factory=list)
    warning: bool = False  # sudden negative
    boost: bool = False  # strong positive

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_ANALYZER = None
_CACHE: Dict[str, Any] = {"items": [], "fetched_at": None}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    s = str(val)
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s[:26], fmt[: len(s) + 2] if False else fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _get_analyzer():
    global _ANALYZER
    if _ANALYZER is None and SentimentIntensityAnalyzer is not None:
        _ANALYZER = SentimentIntensityAnalyzer()
    return _ANALYZER


def score_text(text: str, prefer_finbert: bool = False) -> Tuple[float, str, float, str]:
    """
    Return (compound -1..1, label, confidence 0..1, model_name).
    FinBERT hook: if prefer_finbert and transformers available, use it; else VADER.
    """
    text = (text or "").strip()
    if not text:
        return 0.0, "neutral", 0.0, "none"

    if prefer_finbert:
        try:
            # Optional heavy dependency — documented, not required
            from transformers import pipeline  # type: ignore

            global _FINBERT
            if "_FINBERT" not in globals() or globals().get("_FINBERT") is None:
                globals()["_FINBERT"] = pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    truncation=True,
                )
            pipe = globals()["_FINBERT"]
            out = pipe(text[:512])[0]
            label_raw = str(out.get("label", "neutral")).lower()
            score = float(out.get("score", 0.5))
            if "pos" in label_raw:
                compound = score
                label = "positive"
            elif "neg" in label_raw:
                compound = -score
                label = "negative"
            else:
                compound = 0.0
                label = "neutral"
            return compound, label, score, "finbert"
        except Exception:
            pass  # fall through to VADER

    analyzer = _get_analyzer()
    if analyzer is None:
        # Tiny lexicon fallback
        pos = len(re.findall(r"\b(surge|rally|beat|record|growth|upgrade)\b", text, re.I))
        neg = len(re.findall(r"\b(crash|plunge|miss|fraud|downgrade|layoff)\b", text, re.I))
        compound = (pos - neg) / max(1, pos + neg)
        label = "positive" if compound > 0.05 else "negative" if compound < -0.05 else "neutral"
        return compound, label, min(1.0, abs(compound)), "lexicon"

    scores = analyzer.polarity_scores(text)
    compound = float(scores.get("compound", 0.0))
    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"
    confidence = min(1.0, abs(compound))
    return compound, label, confidence, "vader"


def _guess_sector(text: str) -> Optional[str]:
    low = text.lower()
    for sector, kws in SECTOR_KEYWORDS.items():
        if any(k in low for k in kws):
            return sector
    return None


def _extract_tickers(text: str, universe: Optional[Sequence[str]] = None) -> List[str]:
    """Find $TICKER or uppercase tokens that match universe."""
    found = set(re.findall(r"\$([A-Z]{1,5})\b", text.upper()))
    # Also bare tickers if in universe
    if universe:
        u = {t.upper().replace(".", "-") for t in universe}
        words = set(re.findall(r"\b([A-Z]{2,5})\b", text.upper()))
        # Filter common English words
        stop = {"THE", "AND", "FOR", "USD", "CEO", "ETF", "IPO", "GDP", "CPI", "USA", "NEW", "ALL"}
        found |= {w for w in words if w in u and w not in stop}
    return sorted(found)


def fetch_rss(urls: Optional[List[str]] = None, limit_per_feed: int = 40) -> List[NewsItem]:
    if feedparser is None:
        print("Warning: feedparser not installed; RSS disabled")
        return []
    items: List[NewsItem] = []
    for url in urls or DEFAULT_RSS:
        try:
            # Timeout-hardened fetch (feedparser URL fetch can hang forever)
            try:
                resp = requests.get(
                    url,
                    timeout=12,
                    headers={"User-Agent": "GAMMA-R/0.1 (educational; RSS reader)"},
                )
                if resp.status_code != 200 or not resp.content:
                    print(f"Warning: RSS HTTP {resp.status_code} for {url}")
                    continue
                parsed = feedparser.parse(resp.content)
            except requests.RequestException as net_exc:
                print(f"Warning: RSS network failed for {url}: {net_exc}")
                continue
            source = parsed.feed.get("title", url) if getattr(parsed, "feed", None) else url
            for e in list(parsed.entries)[:limit_per_feed]:
                title = getattr(e, "title", "") or ""
                summary = getattr(e, "summary", "") or getattr(e, "description", "") or ""
                link = getattr(e, "link", "") or ""
                published = None
                for attr in ("published", "updated", "created"):
                    published = _parse_date(getattr(e, attr, None))
                    if published:
                        break
                if published is None and getattr(e, "published_parsed", None):
                    try:
                        import time
                        published = datetime.fromtimestamp(time.mktime(e.published_parsed), tz=timezone.utc)
                    except Exception:
                        published = _utc_now()
                if published is None:
                    published = _utc_now()
                text = f"{title}. {summary}"
                compound, label, conf, model = score_text(text)
                items.append(
                    NewsItem(
                        title=title[:300],
                        summary=re.sub(r"<[^>]+>", "", summary)[:500],
                        url=link,
                        published=published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        source=str(source)[:80],
                        tickers=_extract_tickers(text),
                        sector=_guess_sector(text),
                        sentiment=round(compound, 4),
                        label=label,
                        confidence=round(conf, 4),
                        model=model,
                    )
                )
        except Exception as exc:
            print(f"Warning: RSS fetch failed for {url}: {exc}")
    return items


def fetch_finnhub(tickers: Sequence[str], api_key: Optional[str] = None) -> List[NewsItem]:
    key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not key:
        return []
    items: List[NewsItem] = []
    to = _utc_now().date()
    fr = (to - timedelta(days=7)).isoformat()
    to_s = to.isoformat()
    for t in list(tickers)[:30]:
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": t.replace("-", "."), "from": fr, "to": to_s, "token": key},
                timeout=20,
            )
            if r.status_code != 200:
                continue
            for e in r.json()[:20]:
                title = e.get("headline") or ""
                summary = e.get("summary") or ""
                ts = e.get("datetime")
                published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else _utc_now()
                text = f"{title}. {summary}"
                compound, label, conf, model = score_text(text)
                items.append(
                    NewsItem(
                        title=title[:300],
                        summary=summary[:500],
                        url=e.get("url") or "",
                        published=published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        source=e.get("source") or "finnhub",
                        tickers=[t.upper().replace(".", "-")],
                        sector=_guess_sector(text),
                        sentiment=round(compound, 4),
                        label=label,
                        confidence=round(conf, 4),
                        model=model,
                    )
                )
        except Exception as exc:
            print(f"Warning: Finnhub news failed for {t}: {exc}")
    return items


def fetch_newsapi(query: str = "stocks OR markets", api_key: Optional[str] = None) -> List[NewsItem]:
    key = api_key or os.environ.get("NEWSAPI_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 50,
                "apiKey": key,
            },
            timeout=20,
        )
        r.raise_for_status()
        items = []
        for e in r.json().get("articles", []):
            title = e.get("title") or ""
            summary = e.get("description") or ""
            published = _parse_date(e.get("publishedAt")) or _utc_now()
            text = f"{title}. {summary}"
            compound, label, conf, model = score_text(text)
            items.append(
                NewsItem(
                    title=title[:300],
                    summary=(summary or "")[:500],
                    url=e.get("url") or "",
                    published=published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    source=(e.get("source") or {}).get("name") or "newsapi",
                    tickers=_extract_tickers(text),
                    sector=_guess_sector(text),
                    sentiment=round(compound, 4),
                    label=label,
                    confidence=round(conf, 4),
                    model=model,
                )
            )
        return items
    except Exception as exc:
        print(f"Warning: NewsAPI failed: {exc}")
        return []


def collect_news(
    tickers: Optional[Sequence[str]] = None,
    as_of: Optional[datetime] = None,
    use_cache: bool = True,
) -> List[NewsItem]:
    """
    Fetch + score news. If as_of is set, drop anything published after as_of
    (enforces no look-ahead for backtests / historical train).
    """
    as_of = as_of or _utc_now()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    # Live cache ~10 min (only when as_of is "now")
    nowish = abs((_utc_now() - as_of).total_seconds()) < 120
    if use_cache and nowish and _CACHE.get("items") and _CACHE.get("fetched_at"):
        age = (_utc_now() - _CACHE["fetched_at"]).total_seconds()
        if age < 600:
            items = list(_CACHE["items"])
        else:
            items = None  # type: ignore
    else:
        items = None  # type: ignore

    if items is None:
        items = fetch_rss()
        if tickers:
            items.extend(fetch_finnhub(tickers))
        items.extend(fetch_newsapi())
        # Dedupe by title
        seen = set()
        deduped = []
        for it in items:
            k = it.title.strip().lower()
            if k in seen:
                continue
            seen.add(k)
            deduped.append(it)
        items = deduped
        if nowish:
            _CACHE["items"] = items
            _CACHE["fetched_at"] = _utc_now()

    # Tag tickers from universe if provided
    if tickers:
        for it in items:
            if not it.tickers:
                it.tickers = _extract_tickers(f"{it.title} {it.summary}", tickers)

    # No look-ahead filter
    filtered = []
    for it in items:
        pub = _parse_date(it.published) or as_of
        if pub <= as_of:
            filtered.append(it)
    return filtered


def aggregate_ticker_news(
    items: List[NewsItem],
    ticker: str,
    as_of: Optional[datetime] = None,
    cfg: Optional[StrategyConfig] = None,
) -> TickerNewsAgg:
    cfg = cfg or get_runtime_config()
    as_of = as_of or _utc_now()
    t = ticker.upper().replace(".", "-")
    relevant = [i for i in items if t in [x.upper().replace(".", "-") for x in i.tickers] or t in i.title.upper()]

    def window(hours: int) -> List[NewsItem]:
        cutoff = as_of - timedelta(hours=hours)
        out = []
        for i in relevant:
            pub = _parse_date(i.published)
            if pub and cutoff <= pub <= as_of:
                out.append(i)
        return out

    w24 = window(24)
    w7d = window(24 * 7)
    prior = [i for i in w7d if _parse_date(i.published) and _parse_date(i.published) < as_of - timedelta(hours=24)]

    def avg(xs: List[NewsItem]) -> float:
        if not xs:
            return 0.0
        return sum(i.sentiment for i in xs) / len(xs)

    s24 = avg(w24)
    s7 = avg(w7d)
    prior_avg = avg(prior) if prior else 0.0
    shift = s24 - prior_avg
    spike_thr = float(getattr(cfg, "news_spike_threshold", 0.35) or 0.35)
    spike = abs(shift) >= spike_thr and len(w24) >= 2
    neg_thr = float(getattr(cfg, "news_negative_threshold", -0.4) or -0.4)
    pos_thr = float(getattr(cfg, "news_positive_threshold", 0.4) or 0.4)
    warning = s24 <= neg_thr or (spike and shift < 0)
    boost = s24 >= pos_thr and not warning

    headlines = [i.to_dict() for i in sorted(w24 or w7d, key=lambda x: x.published, reverse=True)[:8]]
    return TickerNewsAgg(
        ticker=t,
        score_24h=round(s24, 4),
        score_7d=round(s7, 4),
        count_24h=len(w24),
        count_7d=len(w7d),
        spike=spike,
        shift=round(shift, 4),
        headlines=headlines,
        warning=warning,
        boost=boost,
    )


def sector_sentiment_impact(
    items: List[NewsItem],
    as_of: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Dashboard: sectors with most sentiment movement (24h vs prior)."""
    as_of = as_of or _utc_now()
    by_sector: Dict[str, List[NewsItem]] = {}
    for i in items:
        sec = i.sector or "Other"
        by_sector.setdefault(sec, []).append(i)

    impact = []
    for sec, xs in by_sector.items():
        w24, prior = [], []
        for i in xs:
            pub = _parse_date(i.published)
            if not pub:
                continue
            if as_of - timedelta(hours=24) <= pub <= as_of:
                w24.append(i)
            elif as_of - timedelta(days=7) <= pub < as_of - timedelta(hours=24):
                prior.append(i)
        if not w24 and not prior:
            continue
        a24 = sum(i.sentiment for i in w24) / len(w24) if w24 else 0.0
        ap = sum(i.sentiment for i in prior) / len(prior) if prior else 0.0
        impact.append({
            "sector": sec,
            "score_24h": round(a24, 4),
            "score_prior": round(ap, 4),
            "movement": round(a24 - ap, 4),
            "count_24h": len(w24),
        })
    impact.sort(key=lambda x: abs(x["movement"]), reverse=True)
    return impact


def news_priority_boost(agg: TickerNewsAgg, cfg: Optional[StrategyConfig] = None) -> float:
    """
    Multiplier / additive boost for momentum ranking.
    Weight news vs technical via cfg.news_weight (0=technical-only, 0.3=70/30 tech/news, 0.5=50/50).
    """
    cfg = cfg or get_runtime_config()
    w = float(getattr(cfg, "news_weight", 0.3) or 0.0)
    if w <= 0:
        return 0.0
    if agg.warning:
        return -abs(w) * abs(min(agg.score_24h, 0)) * 2
    if agg.boost:
        return w * max(agg.score_24h, 0)
    return w * agg.score_24h * 0.5


def blend_score(momentum_pct: float, news_adj: float, cfg: Optional[StrategyConfig] = None) -> float:
    """Combine technical momentum with news adjustment per news_weight setting."""
    cfg = cfg or get_runtime_config()
    mode = str(getattr(cfg, "news_blend_mode", "70_30") or "70_30")
    if mode in ("technical_only", "tech_only", "0"):
        return momentum_pct
    if mode in ("50_50", "50/50"):
        tw, nw = 0.5, 0.5
    else:  # 70/30 technical/news default
        tw, nw = 0.7, 0.3
    # news_adj is roughly -0.3..0.3 scale; scale to momentum-like
    return tw * momentum_pct + nw * news_adj


def enrich_news_display(items: List[NewsItem], user_tz: Optional[str] = None) -> List[Dict[str, Any]]:
    """Attach user-local display times; UTC remains canonical in `published`."""
    from .config import get_runtime_config
    user_tz = user_tz or getattr(get_runtime_config(), "user_timezone", "America/Chicago")
    out = []
    for it in items:
        d = it.to_dict()
        pub = _parse_date(it.published)
        if pub:
            d["time"] = annotate_timestamp(pub, user_tz)
        out.append(d)
    return out


def _items_in_window(
    items: List[NewsItem],
    hours: float = 24.0,
    as_of: Optional[datetime] = None,
) -> List[NewsItem]:
    as_of = as_of or _utc_now()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    cutoff = as_of - timedelta(hours=hours)
    out: List[NewsItem] = []
    for i in items:
        pub = _parse_date(i.published)
        if pub and cutoff <= pub <= as_of:
            out.append(i)
    return out


def collect_news_with_fx(
    tickers: Optional[Sequence[str]] = None,
    as_of: Optional[datetime] = None,
    use_cache: bool = True,
) -> List[NewsItem]:
    """Equity RSS + FX/macro RSS, scored and deduped (offline-tolerant)."""
    as_of = as_of or _utc_now()
    # Reuse collect_news for equity + optional APIs, then merge FX feeds
    base = collect_news(tickers=tickers, as_of=as_of, use_cache=use_cache)
    fx_items = fetch_rss(FX_MACRO_RSS, limit_per_feed=30)
    seen = {i.title.strip().lower() for i in base}
    merged = list(base)
    as_cmp = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    for it in fx_items:
        # Prefer Currencies sector for FX/macro feed items
        it.sector = "Currencies"
        pub = _parse_date(it.published) or as_cmp
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub > as_cmp:
            continue
        k = it.title.strip().lower()
        if k in seen:
            continue
        seen.add(k)
        merged.append(it)
    return merged


def build_eod_digest(
    as_of: Optional[datetime] = None,
    headline_limit: int = 8,
    hours: float = 36.0,
) -> Dict[str, Any]:
    """
    End-of-day news digest for Dashboard + GET /news/eod.

    Aggregates ~last 24h equity + FX/macro headlines into:
      top_headlines, sector_impacts, ticker_mentions, tilt summary, generated_at.
    """
    as_of = as_of or _utc_now()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    try:
        items = collect_news_with_fx(as_of=as_of)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: EOD news collect failed: {exc}")
        items = []

    window = _items_in_window(items, hours=hours, as_of=as_of)
    # Weekend / thin-feed fallback: stretch to 48h so FX Friday copy still surfaces
    if len(window) < 8 and hours < 48:
        hours = 48.0
        window = _items_in_window(items, hours=hours, as_of=as_of)
    # Prefer scored absolute sentiment for "top" headlines
    ranked = sorted(
        window,
        key=lambda i: (abs(float(i.sentiment or 0)), float(i.confidence or 0)),
        reverse=True,
    )
    # Also keep recency diversity: take top by |sentiment|, then fill with newest
    top: List[NewsItem] = []
    seen_titles: set = set()
    for i in ranked:
        k = i.title.strip().lower()
        if not k or k in seen_titles:
            continue
        seen_titles.add(k)
        top.append(i)
        if len(top) >= headline_limit:
            break
    if len(top) < headline_limit:
        for i in sorted(window, key=lambda x: x.published, reverse=True):
            k = i.title.strip().lower()
            if k in seen_titles:
                continue
            seen_titles.add(k)
            top.append(i)
            if len(top) >= headline_limit:
                break

    # Overall tilt
    if window:
        avg = sum(float(i.sentiment or 0) for i in window) / len(window)
    else:
        avg = 0.0
    pos_n = sum(1 for i in window if (i.label or "") == "positive")
    neg_n = sum(1 for i in window if (i.label or "") == "negative")
    neu_n = len(window) - pos_n - neg_n
    if avg >= 0.08 or (pos_n > neg_n and avg > 0):
        tilt = "bullish"
    elif avg <= -0.08 or (neg_n > pos_n and avg < 0):
        tilt = "bearish"
    else:
        tilt = "neutral"

    impacts = sector_sentiment_impact(window, as_of=as_of)

    # Ticker mention rollup (top by |score| among those with tickers)
    ticker_scores: Dict[str, List[float]] = {}
    for i in window:
        for t in i.tickers or []:
            ticker_scores.setdefault(t.upper(), []).append(float(i.sentiment or 0))
    ticker_impacts = []
    for t, scores in ticker_scores.items():
        if not scores:
            continue
        mean = sum(scores) / len(scores)
        ticker_impacts.append({
            "ticker": t,
            "score": round(mean, 4),
            "count": len(scores),
        })
    ticker_impacts.sort(key=lambda x: abs(x["score"]), reverse=True)

    headlines = []
    for i in top[:headline_limit]:
        headlines.append({
            "title": i.title,
            "summary": (i.summary or "")[:240],
            "url": i.url,
            "published": i.published,
            "source": i.source,
            "sentiment": i.sentiment,
            "label": i.label,
            "tickers": i.tickers,
            "sector": i.sector,
        })

    return {
        "generated_at": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_hours": hours,
        "headline_count": len(window),
        "top_headlines": headlines,
        "sector_impacts": impacts[:8],
        "ticker_impacts": ticker_impacts[:10],
        "tilt": tilt,
        "tilt_score": round(avg, 4),
        "label_counts": {"positive": pos_n, "negative": neg_n, "neutral": neu_n},
        "summary": (
            f"{tilt.title()} tilt over ~{int(hours)}h "
            f"({len(window)} headlines; +{pos_n}/−{neg_n}/={neu_n})."
        ),
        "note": "Free RSS + VADER; offline-tolerant. Optional FINNHUB_API_KEY / NEWSAPI_KEY enrich equity side.",
    }
