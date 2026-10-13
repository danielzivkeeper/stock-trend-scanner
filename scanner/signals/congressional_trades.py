"""Signal 4: Members of Congress disclosing purchases (STOCK Act filings).

EVIDENCE: MIXED / WEAK - more "fun" than "proven".
  - Ziobrowski et al. (2004, 2011) found Senators and Representatives beat the
    market in the 1990s.
  - Later studies (Eggers & Hainmueller 2013; Belmont et al. 2022) found little
    or no outperformance in more recent periods, especially after the 2012
    STOCK Act. Disclosures can lag the trade by up to 45 days, so much of any
    edge may be gone by the time we see it.

DATA: free community JSON mirrors (House/Senate Stock Watcher), URLs set in
config.json. STATUS AS OF OCT 2026: both S3 buckets answer "403 AccessDenied" -
the projects appear to be offline. The module degrades to "unavailable" (it
never fakes data). If you find a working mirror with the same JSON shape, just
paste its URL into config.json.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from scanner.base import SignalResult, scaled_strength, unavailable

NAME = "congressional_trades"

# Downloaded once per scan run and shared across tickers (the files are large).
_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()


def parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:19], fmt).date()
        except ValueError:
            continue
    return None


def normalize(house: List[Dict[str, Any]], senate: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge both chambers into {member, chamber, ticker, type, tx_date, disclosed}."""
    out = []
    for r in house:
        out.append({"member": r.get("representative"), "chamber": "House",
                    "ticker": str(r.get("ticker") or "").upper().strip(),
                    "type": str(r.get("type") or "").lower(),
                    "tx_date": parse_date(r.get("transaction_date")),
                    "disclosed": parse_date(r.get("disclosure_date"))})
    for r in senate:
        out.append({"member": r.get("senator") or f'{r.get("first_name") or ""} {r.get("last_name") or ""}'.strip(),
                    "chamber": "Senate",
                    "ticker": str(r.get("ticker") or "").upper().strip(),
                    "type": str(r.get("type") or "").lower(),
                    "tx_date": parse_date(r.get("transaction_date")),
                    "disclosed": parse_date(r.get("disclosure_date"))})
    return out


def evaluate(trades: List[Dict[str, Any]], ticker: str, params: Dict[str, Any], today: date) -> SignalResult:
    """Pure function over normalize()d records.

    "Last N days" is measured on the DISCLOSURE date when present (that's when
    the public could first act on it), else the transaction date.
    """
    lookback = int(params.get("lookback_days", 45))
    min_n = int(params.get("min_distinct_members", 2))
    full_mult = float(params.get("full_strength_multiple", 2.0))
    cutoff = today - timedelta(days=lookback)

    hits = []
    for t in trades:
        when = t.get("disclosed") or t.get("tx_date")
        if t["ticker"] == ticker.upper() and "purchase" in t["type"] and when and cutoff <= when <= today:
            hits.append(t)
    members = sorted({str(t["member"]).strip() for t in hits if t.get("member")})
    raw = {"distinct_members": len(members), "members": members[:10], "purchases": len(hits)}
    n = len(members)
    if n < min_n:
        return SignalResult(NAME, False, 0.0,
                            f"{n} member{'s' if n != 1 else ''} of Congress disclosed a purchase in the last "
                            f"{lookback} days; need {min_n}+.", raw)
    return SignalResult(NAME, True, scaled_strength(n, min_n, full_mult),
                        f"{n} members of Congress disclosed buying in the last {lookback} days: "
                        f"{', '.join(members[:4])}{'…' if n > 4 else ''}.", raw)


def _load(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    with _LOCK:
        return _load_locked(params)


def _load_locked(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    import requests

    if "trades" in _CACHE:
        return _CACHE["trades"]
    if "error" in _CACHE:
        raise RuntimeError(_CACHE["error"])
    chunks = {}
    errors = []
    for chamber, url in (("house", params.get("house_url")), ("senate", params.get("senate_url"))):
        if not url:
            continue
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            chunks[chamber] = r.json()
        except Exception as e:  # noqa: BLE001 - any failure means "source unavailable"
            code = getattr(getattr(e, "response", None), "status_code", None)
            errors.append(f"{chamber}: HTTP {code}" if code else f"{chamber}: {type(e).__name__}")
    if not chunks:
        _CACHE["error"] = "; ".join(errors) or "no source URLs configured"
        raise RuntimeError(_CACHE["error"])
    _CACHE["trades"] = normalize(chunks.get("house", []), chunks.get("senate", []))
    _CACHE["partial_errors"] = errors
    return _CACHE["trades"]


def run(ticker: str, keyword: str, params: Dict[str, Any], today: Optional[date] = None) -> SignalResult:
    try:
        trades = _load(params)
    except RuntimeError as e:
        return unavailable(NAME, f"Congress-trade mirrors unreachable ({e}). Source appears to be offline.")
    result = evaluate(trades, ticker, params, today or date.today())
    if _CACHE.get("partial_errors"):
        result.raw["partial_errors"] = _CACHE["partial_errors"]
    return result
