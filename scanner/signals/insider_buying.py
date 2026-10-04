"""Signal 2: Cluster insider buying (open-market purchases, SEC Form 4).

EVIDENCE: MODERATE-TO-STRONG.
  - Seyhun (1986), Lakonishok & Lee (2001): insider PURCHASES predict positive
    abnormal returns; insider SALES carry little information (people sell for
    taxes, houses, diversification - people buy for one reason).
  - Cohen, Malloy & Pomorski (2012): "opportunistic" (non-routine) buys are the
    informative ones. Several insiders buying at once ("clusters") is a widely
    used proxy for that, though the cluster rule itself is practitioner lore
    more than a single canonical paper.
  - Effect is strongest in small caps and plays out over weeks to months.

DATA: openinsider.com's free screener, read with pandas.read_html.
  IMPORTANT: openinsider is a THIRD-PARTY AGGREGATOR of SEC Form 4 filings,
  not the primary source. The primary source is SEC EDGAR
  (https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4).
  The aggregator may lag, mis-parse, or change its HTML at any time.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from scanner.base import SignalResult, scaled_strength, unavailable

NAME = "insider_buying"

SCREENER_URL = (
    "http://openinsider.com/screener?s={ticker}&o=&pl=&ph=&ll=&lh=&fd={days}&fdr=&td=0&tdr="
    "&fdlyl=&fdlyh=&daysago=&xp=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0"
    "&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=100&page=1"
)  # xp=1 -> purchases only; fd=N -> filed in the last N days


def _norm(col: str) -> str:
    # openinsider headers use non-breaking spaces ("Insider\xa0Name")
    return str(col).replace("\xa0", " ").strip()


def _money(v: Any) -> float:
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("+", ""))
    except ValueError:
        return 0.0


def evaluate(records: List[Dict[str, Any]], ticker: str, params: Dict[str, Any]) -> SignalResult:
    """Pure function. `records` = screener rows with normalized column names."""
    min_n = int(params.get("min_distinct_insiders", 2))
    full_mult = float(params.get("full_strength_multiple", 2.0))
    days = int(params.get("lookback_days", 14))

    buys = [r for r in records
            if str(r.get("Ticker", "")).upper() == ticker.upper()
            and str(r.get("Trade Type", "")).startswith("P")]  # "P - Purchase"
    # Token buys (a director buying $500 of stock) say little about conviction,
    # so an insider only counts once their purchases add up to min_value.
    min_value = float(params.get("min_value_per_insider_usd", 10000))
    per_insider: Dict[str, float] = {}
    for r in buys:
        who = str(r.get("Insider Name", "")).strip()
        if who:
            per_insider[who] = per_insider.get(who, 0.0) + _money(r.get("Value"))
    insiders = sorted(w for w, v in per_insider.items() if v >= min_value)
    small = sorted(w for w, v in per_insider.items() if v < min_value)
    total_value = sum(per_insider[w] for w in insiders)
    raw = {
        "distinct_insiders": len(insiders),
        "insiders": insiders[:10],
        "titles": sorted({str(r.get("Title", "")) for r in buys})[:10],
        "purchase_count": len(buys),
        "ignored_small_buyers": small[:10],
        "total_value_usd": round(total_value),
    }
    n = len(insiders)
    if n < min_n:
        who = f" ({insiders[0]})" if n == 1 else ""
        extra = f" ({len(small)} more bought under ${min_value:,.0f} each)" if small else ""
        return SignalResult(NAME, False, 0.0,
                            f"{n} insider{'s' if n != 1 else ''}{who} bought ${min_value:,.0f}+ in the last "
                            f"{days} days{extra}; need {min_n}+ distinct buyers.", raw)
    strength = scaled_strength(n, min_n, full_mult)
    return SignalResult(NAME, True, strength,
                        f"{n} different insiders bought ~${total_value:,.0f} of stock with their own money "
                        f"in the last {days} days: {', '.join(insiders[:4])}"
                        f"{'…' if n > 4 else ''}.", raw)


def parse_html(html: str) -> Optional[List[Dict[str, Any]]]:
    """Returns screener rows, [] when the page says no results, None if the layout changed."""
    from io import StringIO

    import pandas as pd

    if "tinytable" not in html:  # the class name lives in the page CSS even with 0 results
        return None
    try:
        tables = pd.read_html(StringIO(html), attrs={"class": "tinytable"}, flavor="lxml")
    except ValueError:  # "No tables found" -> screener matched nothing (a ticker with no buys)
        return []
    if not tables:
        return []
    df = tables[0]
    df.columns = [_norm(c) for c in df.columns]
    return df.to_dict("records")


def run(ticker: str, keyword: str, params: Dict[str, Any]) -> SignalResult:
    import requests

    days = int(params.get("lookback_days", 14))
    url = SCREENER_URL.format(ticker=ticker, days=days)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (personal stock-trend-scanner)"}, timeout=30)
    resp.raise_for_status()
    records = parse_html(resp.text)
    if records is None:
        return unavailable(NAME, "openinsider page layout changed; could not parse.")
    return evaluate(records, ticker, params)
