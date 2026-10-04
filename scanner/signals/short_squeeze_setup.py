"""Signal 3: Short-squeeze SETUP (high short interest + high days-to-cover).

EVIDENCE: MIXED - read this before trusting it.
  - On AVERAGE, heavily shorted stocks UNDER-perform afterward (Asquith,
    Pathak & Ritter 2005; Boehmer, Huszar & Jordan 2010). Short sellers are,
    as a group, fairly well informed. So high short interest is historically a
    mildly BEARISH signal on its own.
  - Squeezes (GME 2021, VW 2008) are real but rare, and need a catalyst.
    This module only measures the "fuel", never the spark. That's why it makes
    most sense as confluence with earnings_drift / insider_buying, not alone.

DATA: yfinance get_info() -> shortPercentOfFloat (a fraction, 0.15 = 15%) and
shortRatio (days to cover). These come from FINRA short-interest reports that
are only published TWICE A MONTH, so this is a slow, stale snapshot - it will
not catch an intraday squeeze.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from scanner.base import SignalResult, scaled_strength, unavailable

NAME = "short_squeeze_setup"


def evaluate(info: Dict[str, Any], params: Dict[str, Any]) -> SignalResult:
    """Pure function. `info` = the subset of yfinance get_info() we use."""
    min_pct = float(params.get("min_short_pct_float", 15.0))
    min_dtc = float(params.get("min_days_to_cover", 5.0))
    full_mult = float(params.get("full_strength_multiple", 3.0))

    spf = info.get("shortPercentOfFloat")
    dtc = info.get("shortRatio")
    pct = None if spf is None else float(spf) * 100.0  # Yahoo gives a fraction
    dtc = None if dtc is None else float(dtc)
    as_of = info.get("dateShortInterest")
    as_of_str = (datetime.fromtimestamp(as_of, tz=timezone.utc).date().isoformat()
                 if isinstance(as_of, (int, float)) else None)
    raw = {"short_pct_float": None if pct is None else round(pct, 2),
           "days_to_cover": dtc, "short_interest_as_of": as_of_str}
    if pct is None and dtc is None:
        return unavailable(NAME, "No short-interest data from Yahoo for this ticker.", raw)

    pct_hit = pct is not None and pct >= min_pct
    dtc_hit = dtc is not None and dtc >= min_dtc
    pct_txt = "n/a" if pct is None else f"{pct:.1f}%"
    dtc_txt = "n/a" if dtc is None else f"{dtc:.1f}"
    stamp = f" (FINRA data as of {as_of_str})" if as_of_str else ""
    if not (pct_hit or dtc_hit):
        return SignalResult(NAME, False, 0.0,
                            f"Short interest {pct_txt} of float, {dtc_txt} days to cover{stamp}; "
                            f"needs >= {min_pct:g}% or >= {min_dtc:g} days.", raw)
    strength = max(scaled_strength(pct or 0.0, min_pct, full_mult),
                   scaled_strength(dtc or 0.0, min_dtc, full_mult))
    return SignalResult(NAME, True, strength,
                        f"{pct_txt} of float sold short, {dtc_txt} days to cover{stamp}. "
                        f"Squeeze fuel only - historically high short interest is bearish on average.", raw)


def run(ticker: str, keyword: str, params: Dict[str, Any]) -> SignalResult:
    import yfinance as yf

    info = yf.Ticker(ticker).get_info() or {}
    return evaluate(info, params)
