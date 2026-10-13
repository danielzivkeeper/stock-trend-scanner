"""Signal 1: Post-Earnings-Announcement Drift (PEAD).

EVIDENCE: STRONG (the best-documented anomaly in this project).
  - Ball & Brown (1968) and Bernard & Thomas (1989, 1990): after a positive
    earnings surprise, prices keep drifting in the surprise direction for
    roughly 60 trading days, because the market under-reacts.
  - Honest caveat: later work (e.g. Chordia et al. 2009) finds the drift has
    shrunk a lot in large, liquid stocks since the 2000s and survives mostly in
    smaller / less-liquid names. "Robust" means "repeatedly replicated", not
    "still free money".

DATA: yfinance `Ticker.get_earnings_dates()` (unofficial Yahoo Finance scrape;
can break without warning). We only go long, so only POSITIVE surprises fire.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional

from scanner.base import SignalResult, scaled_strength, unavailable

NAME = "earnings_drift"


def _is_num(x: Any) -> bool:
    try:
        return x is not None and not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def surprise_pct(estimate: Any, reported: Any, fallback: Any = None) -> Optional[float]:
    """EPS surprise in percent: (reported - estimate) / |estimate| * 100.

    Falls back to Yahoo's own "Surprise(%)" column when we can't compute it.
    Note: tiny estimates (e.g. $0.01) make this number explode - that's real
    math, and the strength cap of 1.0 keeps it from dominating the score.
    """
    if _is_num(estimate) and _is_num(reported) and float(estimate) != 0:
        return (float(reported) - float(estimate)) / abs(float(estimate)) * 100.0
    if _is_num(reported) and _is_num(fallback):
        return float(fallback)
    return None


def evaluate(rows: List[Dict[str, Any]], params: Dict[str, Any], today: date) -> SignalResult:
    """Pure function (no network). `rows` = [{date, estimate, reported, surprise}]."""
    threshold = float(params.get("min_surprise_pct", 5.0))
    full_mult = float(params.get("full_strength_multiple", 3.0))
    max_age = int(params.get("max_days_since_report", 30))

    # Most recent report that has actually happened (future dates have no reported EPS).
    past = [r for r in rows if r["date"] <= today and _is_num(r.get("reported"))]
    if not past:
        return unavailable(NAME, "No reported earnings found.")
    latest = max(past, key=lambda r: r["date"])
    age = (today - latest["date"]).days
    s = surprise_pct(latest.get("estimate"), latest.get("reported"), latest.get("surprise"))
    raw = {
        "report_date": latest["date"].isoformat(),
        "days_since_report": age,
        "eps_estimate": latest.get("estimate"),
        "eps_reported": latest.get("reported"),
        "surprise_pct": None if s is None else round(s, 2),
    }
    if s is None:
        return unavailable(NAME, "Latest report has no usable EPS estimate.", raw)

    when = f"{latest['date'].isoformat()} ({age}d ago)"
    if age > max_age:
        return SignalResult(NAME, False, 0.0,
                            f"Last report {when} is older than the {max_age}-day drift window "
                            f"(surprise was {s:+.1f}%).", raw)
    if s < threshold:
        return SignalResult(NAME, False, 0.0,
                            f"EPS surprise {s:+.1f}% on {when} is below the +{threshold:g}% threshold.", raw)
    strength = scaled_strength(s, threshold, full_mult)
    return SignalResult(NAME, True, strength,
                        f"EPS beat estimates by {s:+.1f}% on {when} "
                        f"(reported {latest['reported']} vs est. {latest['estimate']}).", raw)


def _fetch_rows(ticker: str) -> List[Dict[str, Any]]:
    import yfinance as yf  # imported lazily so offline tests don't need it

    from scanner.cache import YAHOO_LIMIT

    YAHOO_LIMIT.wait()
    df = yf.Ticker(ticker).get_earnings_dates(limit=12)
    rows = []
    for idx, rec in (df.iterrows() if df is not None else []):
        rows.append({
            "date": idx.date().isoformat(),  # pandas Timestamp (exchange-local time) -> calendar date
            "estimate": None if not _is_num(rec.get("EPS Estimate")) else float(rec.get("EPS Estimate")),
            "reported": None if not _is_num(rec.get("Reported EPS")) else float(rec.get("Reported EPS")),
            "surprise": None if not _is_num(rec.get("Surprise(%)")) else float(rec.get("Surprise(%)")),
        })
    return rows


def run(ticker: str, keyword: str, params: Dict[str, Any], today: Optional[date] = None) -> SignalResult:
    from scanner.cache import cache

    today = today or date.today()
    # Earnings dates change a few times a year; re-download at most about once a day.
    rows = cache("earnings").get_or_fetch(ticker, float(params.get("cache_hours", 20)), lambda: _fetch_rows(ticker))
    if not rows:
        return unavailable(NAME, "Yahoo returned no earnings dates.")
    return evaluate([dict(r, date=date.fromisoformat(r["date"])) for r in rows], params, today)
