"""Forward-test the scanner's OWN logged scores (docs/data/history.json).

Why not a classic 10-year backtest? Because we can't rebuild most of these
signals historically for free (old short interest, old Reddit/Trends
baselines, old openinsider screens), and a backtest built on today's data for
past dates leaks the future. So instead: every scan is logged, and once
`hold_days` trading days have passed we check what actually happened.

Rules (deliberately conservative):
  - "entry" = close of the first trading day AFTER the scan date (so we never
    assume we could trade at a price we'd already seen when the scan ran);
  - "exit"  = close `hold_days` trading days after entry (default 10, see config);
  - one open test per ticker at a time - repeat alerts during a hold window
    are ignored so one hot ticker can't be counted ten times;
  - compared against SPY over the exact same dates.

Sample sizes will be tiny for months. Treat early numbers as anecdotes.

    python -m scanner.backtest                 # uses config alert_threshold
    python -m scanner.backtest --min-score 4   # "what if my threshold were 4?"
"""
from __future__ import annotations

import argparse
import bisect
import os
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

PriceSeries = List[Tuple[str, float]]  # [(YYYY-MM-DD, close)] sorted ascending


def pick_signals(history: List[Dict[str, Any]], min_score: float) -> List[Dict[str, Any]]:
    """One row per (ticker, date): the max score that day, kept if >= min_score."""
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for h in history:
        key = (h["ticker"], h["date"])
        if key not in best or h["score"] > best[key]["score"]:
            best[key] = h
    return sorted((h for h in best.values() if h["score"] >= min_score), key=lambda h: (h["date"], h["ticker"]))


def _close_on(series: PriceSeries, day: str) -> Optional[float]:
    i = bisect.bisect_left(series, (day, float("-inf")))
    return series[i][1] if i < len(series) and series[i][0] == day else None


def forward_test(history: List[Dict[str, Any]], prices: Dict[str, PriceSeries],
                 benchmark: PriceSeries, hold_days: int, min_score: float) -> Dict[str, Any]:
    """Pure function. Returns {trades: [...], summary: {...}}."""
    trades = []
    busy_until: Dict[str, str] = {}  # ticker -> exit date of its current test
    for sig in pick_signals(history, min_score):
        series = prices.get(sig["ticker"]) or []
        dates = [d for d, _ in series]
        if sig["ticker"] in busy_until and sig["date"] <= busy_until[sig["ticker"]]:
            continue
        i = bisect.bisect_right(dates, sig["date"])  # first trading day strictly after the scan
        row = {"ticker": sig["ticker"], "signal_date": sig["date"], "score": sig["score"],
               "fired": sig.get("fired", [])}
        if i >= len(series):
            trades.append({**row, "status": "pending", "note": "entry day not reached yet"})
            busy_until[sig["ticker"]] = "9999-12-31"
            continue
        entry_d, entry_px = series[i]
        j = i + hold_days
        if j >= len(series):
            trades.append({**row, "status": "pending", "entry_date": entry_d, "entry": entry_px,
                           "note": f"{len(series) - 1 - i} of {hold_days} trading days elapsed"})
            busy_until[sig["ticker"]] = "9999-12-31"
            continue
        exit_d, exit_px = series[j]
        ret = exit_px / entry_px - 1
        b0, b1 = _close_on(benchmark, entry_d), _close_on(benchmark, exit_d)
        bret = (b1 / b0 - 1) if (b0 and b1) else None
        trades.append({**row, "status": "done", "entry_date": entry_d, "entry": entry_px,
                       "exit_date": exit_d, "exit": exit_px, "return": round(ret, 4),
                       "spy_return": None if bret is None else round(bret, 4),
                       "excess": None if bret is None else round(ret - bret, 4)})
        busy_until[sig["ticker"]] = exit_d
    return {"trades": trades, "summary": summarize(trades, hold_days, min_score)}


def summarize(trades: List[Dict[str, Any]], hold_days: int, min_score: float) -> Dict[str, Any]:
    done = [t for t in trades if t["status"] == "done"]
    rets = [t["return"] for t in done]
    excess = [t["excess"] for t in done if t.get("excess") is not None]
    return {
        "hold_days": hold_days,
        "min_score": min_score,
        "completed": len(done),
        "pending": len(trades) - len(done),
        "avg_return": round(statistics.mean(rets), 4) if rets else None,
        "median_return": round(statistics.median(rets), 4) if rets else None,
        "win_rate": round(sum(r > 0 for r in rets) / len(rets), 4) if rets else None,
        "avg_excess_vs_spy": round(statistics.mean(excess), 4) if excess else None,
        "beat_spy_rate": round(sum(e > 0 for e in excess) / len(excess), 4) if excess else None,
    }


def fetch_prices(tickers: List[str], start: str) -> Dict[str, PriceSeries]:
    import yfinance as yf

    out: Dict[str, PriceSeries] = {}
    for t in tickers:
        try:
            df = yf.Ticker(t).history(start=start, auto_adjust=True)
            out[t] = [(idx.date().isoformat(), float(c)) for idx, c in df["Close"].dropna().items()]
        except Exception as e:  # noqa: BLE001
            print(f"[backtest] price fetch failed for {t}: {e}")
            out[t] = []
    return out


def main(argv: List[str] = None) -> int:
    from scanner.run_scan import ROOT, load_json, save_json
    from scanner.scoring import load_config

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--data", default=os.path.join(ROOT, "docs", "data"))
    args = ap.parse_args(argv)

    cfg = load_config(os.path.join(ROOT, "config.json"))
    min_score = cfg["alert_threshold"] if args.min_score is None else args.min_score
    history = load_json(os.path.join(args.data, "history.json"), [])
    sigs = pick_signals(history, min_score)
    if sigs:
        start = sigs[0]["date"]
        tickers = sorted({s["ticker"] for s in sigs})
        prices = fetch_prices(tickers + ["SPY"], start)
        result = forward_test(history, prices, prices.pop("SPY", []), cfg["hold_days"], min_score)
    else:
        result = {"trades": [], "summary": summarize([], cfg["hold_days"], min_score)}
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(result["summary"])
    if args.min_score is None:  # only the official threshold feeds the dashboard
        save_json(os.path.join(args.data, "backtest.json"), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
