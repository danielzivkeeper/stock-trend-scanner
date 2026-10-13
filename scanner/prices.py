"""Daily price history shared by the market snapshot and the chart-pattern
signal: one bulk Yahoo download for the S&P 500 per run, plus on-demand
single-ticker downloads for anything else (watchlist / trending names)."""
from __future__ import annotations

import threading
from typing import Any, Dict, List

Bar = Dict[str, Any]  # {"date": "YYYY-MM-DD", "close": float, "volume": float}

_STORE: Dict[str, List[Bar]] = {}
_LOCK = threading.Lock()


def _frame_to_bars(close, volume) -> List[Bar]:
    out = []
    for idx, c in close.dropna().items():
        vol = volume.get(idx) if volume is not None else None
        out.append({"date": idx.date().isoformat(), "close": float(c),
                    "volume": float(vol) if vol is not None and vol == vol else 0.0})
    return out


def bulk_load(tickers: List[str], period: str = "1y") -> Dict[str, List[Bar]]:
    import yfinance as yf

    df = yf.download(tickers, period=period, interval="1d", auto_adjust=True, progress=False, threads=True)
    closes, vols = df["Close"], df.get("Volume")
    loaded = {}
    for t in closes.columns:
        bars = _frame_to_bars(closes[t], vols[t] if vols is not None and t in vols else None)
        if bars:
            loaded[str(t)] = bars
    with _LOCK:
        _STORE.update(loaded)
    return loaded


def get(ticker: str, period: str = "1y") -> List[Bar]:
    with _LOCK:
        if ticker in _STORE:
            return _STORE[ticker]
    try:
        import yfinance as yf

        from scanner.cache import YAHOO_LIMIT

        YAHOO_LIMIT.wait()
        h = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        bars = _frame_to_bars(h["Close"], h["Volume"]) if len(h) else []
    except Exception:  # noqa: BLE001
        bars = []
    with _LOCK:
        _STORE[ticker] = bars
    return bars
