"""Daily market check: S&P 500 stocks that fell a lot in one day, plus the
daily summary text.

WHAT A BIG ONE-DAY DROP MEANS (evidence is mixed - this is a "look closer"
list, not a buy list):
  - Short-term reversal: on average, big losers bounce a little over the next
    week or so (Lehmann 1990; Jegadeesh 1990), partly because forced selling
    overshoots.
  - BUT drops caused by real news (earnings misses, guidance cuts, fraud,
    lawsuits) tend to KEEP drifting down (Chan 2003; the flip side of the
    earnings-drift signal). Always check WHY it fell before treating it as a
    bargain.

DATA: constituents from Wikipedia's "List of S&P 500 companies" table (cached
weekly); prices from Yahoo via yfinance in one bulk download (~40 seconds).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = "StockTrendScanner/1.0 (https://github.com/danielzivkeeper/stock-trend-scanner)"
SMS_LIMIT = 160


# ------------------------------------------------------------ pure helpers

def find_drops(closes: Dict[str, List[Tuple[str, float]]], threshold_pct: float,
               names: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Pure. closes = {ticker: [(YYYY-MM-DD, close), ...] ascending}.

    Returns (latest trading date, drops sorted worst first). Only tickers whose
    last bar is on that latest date count, so a stale/halted stock can't show
    an old move as "today".
    """
    names = names or {}
    latest = max((s[-1][0] for s in closes.values() if len(s) >= 2), default=None)
    if latest is None:
        return None, []
    drops = []
    for t, s in closes.items():
        if len(s) < 2 or s[-1][0] != latest or not s[-2][1]:
            continue
        pct = round((s[-1][1] / s[-2][1] - 1) * 100, 6)  # rounding: 45/50 is -9.9999999...% in floating point
        if pct <= -abs(threshold_pct):
            drops.append({"ticker": t, "name": names.get(t, t), "pct": round(pct, 2), "close": round(s[-1][1], 2),
                          "prev_close": round(s[-2][1], 2)})
    drops.sort(key=lambda d: d["pct"])
    return latest, drops


def pack_texts(lines: List[str], limit: int = SMS_LIMIT, max_texts: int = 3) -> List[str]:
    """Pure. Greedily packs lines into as few <=limit-char texts as possible."""
    texts: List[str] = []
    cur = ""
    for line in lines:
        line = line if len(line) <= limit else line[:limit - 1] + "…"
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) <= limit:
            cur = candidate
        else:
            texts.append(cur)
            cur = line
    if cur:
        texts.append(cur)
    if len(texts) > max_texts:
        texts = texts[:max_texts]
        texts[-1] = texts[-1][:limit - 12] + "\n(more: app)"
    return texts


def compose_summary(day: str, market_date: Optional[str], drops: List[Dict[str, Any]], threshold_pct: float,
                    tickers: List[Dict[str, Any]], alert_threshold: float, rising: List[str],
                    dashboard_url: str = "") -> List[str]:
    """Pure. Builds the daily summary as a list of SMS-sized texts."""
    d = datetime.strptime(day, "%Y-%m-%d")
    lines = [f"Daily scan {d.month}/{d.day}"]
    if market_date and market_date != day:
        lines.append(f"Market closed today (last prices {market_date}).")
    elif drops:
        shown = ", ".join(f"{x['ticker']} {x['pct']:.1f}%" for x in drops[:8])
        more = f" +{len(drops) - 8} more" if len(drops) > 8 else ""
        lines.append(f"S&P500 down {threshold_pct:g}%+: {shown}{more}")
    else:
        lines.append(f"No S&P500 stock fell {threshold_pct:g}%+ today.")
    alerts = [t for t in tickers if t["score"] >= alert_threshold]
    if alerts:
        lines.append("ALERTS: " + ", ".join(f"{t['ticker']} {t['score']:.1f}" for t in alerts))
    top = sorted(tickers, key=lambda t: -t["score"])[:3]
    if top:
        lines.append("Top scores: " + ", ".join(f"{t['ticker']} {t['score']:.1f}" for t in top))
    lines.append("Trending up: " + (", ".join(rising[:5]) if rising else "none"))
    texts = pack_texts(lines)
    # Add the link only where it fits - never spend a whole extra text on it.
    if dashboard_url and len(texts[-1]) + 1 + len(dashboard_url) <= SMS_LIMIT:
        texts[-1] += "\n" + dashboard_url
    return texts


# ------------------------------------------------------------ network

def load_sp500(cache_path: str, max_age_days: int = 7) -> Dict[str, str]:
    """{ticker: company name}. Refreshes the cached copy from Wikipedia weekly."""
    from scanner.run_scan import load_json, save_json

    cached = load_json(cache_path, {})
    fresh = cached.get("fetched") and (date.today() - date.fromisoformat(cached["fetched"])).days < max_age_days
    if fresh and cached.get("constituents"):
        return cached["constituents"]
    try:
        from io import StringIO

        import pandas as pd
        import requests

        html = requests.get(SP500_URL, headers={"User-Agent": UA}, timeout=30).text
        table = pd.read_html(StringIO(html), attrs={"id": "constituents"}, flavor="lxml")[0]
        cons = {str(r["Symbol"]).replace(".", "-"): str(r["Security"]) for _, r in table.iterrows()}
        if len(cons) < 450:  # sanity check: page layout changed
            raise ValueError(f"only {len(cons)} rows parsed")
        save_json(cache_path, {"fetched": date.today().isoformat(), "constituents": cons})
        return cons
    except Exception as e:  # noqa: BLE001 - fall back to the last good list
        print(f"[market] S&P 500 list refresh failed ({e}); using cached copy")
        return cached.get("constituents", {})


def fetch_closes(tickers: List[str]) -> Dict[str, List[Tuple[str, float]]]:
    import yfinance as yf

    df = yf.download(tickers, period="5d", interval="1d", auto_adjust=True, progress=False, threads=True)
    closes = df["Close"]
    out = {}
    for t in closes.columns:
        s = closes[t].dropna()
        out[str(t)] = [(idx.date().isoformat(), float(v)) for idx, v in s.items()]
    return out


def daily_drops(data_dir: str, threshold_pct: float) -> Dict[str, Any]:
    cons = load_sp500(os.path.join(data_dir, "sp500_constituents.json"))
    if not cons:
        return {"status": "unavailable", "market_date": None, "drops": [], "threshold_pct": threshold_pct}
    market_date, drops = find_drops(fetch_closes(sorted(cons)), threshold_pct, cons)
    print(f"[market] {len(cons)} S&P 500 stocks, prices as of {market_date}: "
          f"{len(drops)} fell {threshold_pct:g}%+ ({', '.join(d['ticker'] for d in drops) or 'none'})")
    return {"status": "ok", "market_date": market_date, "drops": drops, "threshold_pct": threshold_pct,
            "checked": len(cons), "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def new_york_today() -> str:
    """Calendar date in New York (DST-aware), so an evening run labels the right trading day."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:  # noqa: BLE001 - no tz database: approximate with UTC-5
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()
