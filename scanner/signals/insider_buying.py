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

DATA (two sources, the first one that's configured wins):
  1. SEC EDGAR - the PRIMARY source. We list each company's recent Form 4
     filings (data.sec.gov submissions API) and read the filing XML directly.
     The SEC requires a contact email in every automated request's
     User-Agent; it comes from the SEC_CONTACT_EMAIL environment variable
     (a GitHub secret). Free, official, and reachable from GitHub's servers.
  2. openinsider.com's screener (fallback when SEC_CONTACT_EMAIL isn't set).
     IMPORTANT: openinsider is a THIRD-PARTY AGGREGATOR of SEC Form 4
     filings, not the primary source, and it doesn't answer requests from
     GitHub's servers (tested Oct 2026) - it only works when run locally.

Purchases made under a pre-scheduled Rule 10b5-1 plan are ignored: they were
decided months earlier, which is exactly the "routine" kind of trade Cohen,
Malloy & Pomorski found uninformative.
"""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
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
    planned = [r for r in buys if r.get("plan_10b5_1")]
    buys = [r for r in buys if not r.get("plan_10b5_1")]
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
        "ignored_10b5_1_plan_purchases": len(planned),
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


# ------------------------------------------------------------ SEC EDGAR

_SEC: Dict[str, Any] = {}  # cache for the ticker -> CIK map, shared across tickers


def _txt(el: Optional[ET.Element], path: str) -> str:
    if el is None:
        return ""
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_form4(xml_text: str) -> List[Dict[str, Any]]:
    """Pure function: one Form 4 XML -> purchase records shaped like screener rows."""
    root = ET.fromstring(xml_text)
    ticker = _txt(root, "issuer/issuerTradingSymbol").upper()
    plan = _txt(root, "aff10b5One") in ("1", "true")
    owners, titles = [], []
    for o in root.findall("reportingOwner"):
        owners.append(_txt(o, "reportingOwnerId/rptOwnerName"))
        rel = o.find("reportingOwnerRelationship")
        title = _txt(rel, "officerTitle")
        if not title:
            title = ("Director" if _txt(rel, "isDirector") in ("1", "true") else
                     "10% owner" if _txt(rel, "isTenPercentOwner") in ("1", "true") else "Other")
        titles.append(title)
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _txt(tx, "transactionCoding/transactionCode") != "P":  # P = open-market purchase
            continue
        try:
            shares = float(_txt(tx, "transactionAmounts/transactionShares/value") or 0)
            price = float(_txt(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            shares = price = 0.0
        for who, title in zip(owners, titles):
            out.append({"Ticker": ticker, "Insider Name": who, "Title": title, "Trade Type": "P - Purchase",
                        "Value": shares * price / max(len(owners), 1),
                        "Trade Date": _txt(tx, "transactionDate/value"), "plan_10b5_1": plan})
    return out


def _sec_get(url: str, email: str):
    import requests

    time.sleep(0.15)  # SEC fair-use limit is 10 requests/second
    r = requests.get(url, headers={"User-Agent": f"StockTrendScanner {email}"}, timeout=30)
    r.raise_for_status()
    return r


def _cik(ticker: str, email: str) -> Optional[int]:
    if "map" not in _SEC:
        data = _sec_get("https://www.sec.gov/files/company_tickers.json", email).json()
        _SEC["map"] = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}
    return _SEC["map"].get(ticker.upper())


def fetch_edgar(ticker: str, days: int, email: str, today: Optional[date] = None) -> Optional[List[Dict[str, Any]]]:
    cik = _cik(ticker, email)
    if cik is None:
        return None
    cutoff = ((today or date.today()) - timedelta(days=days)).isoformat()
    recent = _sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", email).json()["filings"]["recent"]
    records: List[Dict[str, Any]] = []
    rows = zip(recent["form"], recent["filingDate"], recent["accessionNumber"], recent["primaryDocument"])
    form4s = [(acc, doc) for form, filed, acc, doc in rows if form == "4" and filed >= cutoff]
    for acc, doc in form4s[:60]:  # cap requests for very active companies
        xml_name = doc.split("/")[-1]  # primaryDocument points at the styled view; raw XML has the same name
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{xml_name}"
        try:
            records.extend(parse_form4(_sec_get(url, email).text))
        except Exception as e:  # noqa: BLE001 - one odd filing shouldn't sink the signal
            print(f"    [insider] skipped {url}: {type(e).__name__}")
    return records


# ------------------------------------------------------------ entry point

def run(ticker: str, keyword: str, params: Dict[str, Any]) -> SignalResult:
    import requests

    days = int(params.get("lookback_days", 14))
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if email:
        records = fetch_edgar(ticker, days, email)
        if records is None:
            return unavailable(NAME, f"{ticker} not found in the SEC's ticker list.")
        result = evaluate(records, ticker, params)
        result.raw["source"] = "SEC EDGAR Form 4"
        return result

    url = SCREENER_URL.format(ticker=ticker, days=days)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (personal stock-trend-scanner)"}, timeout=30)
    resp.raise_for_status()
    records = parse_html(resp.text)
    if records is None:
        return unavailable(NAME, "openinsider page layout changed; could not parse.")
    result = evaluate(records, ticker, params)
    result.raw["source"] = "openinsider.com (SEC_CONTACT_EMAIL not set)"
    return result
