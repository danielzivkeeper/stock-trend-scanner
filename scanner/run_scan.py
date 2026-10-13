"""Entry point: run every signal on every watchlist ticker, score, save, alert.

    python -m scanner.run_scan                 # full run (what GitHub Actions does)
    python -m scanner.run_scan --no-alerts     # don't send texts
    python -m scanner.run_scan --tickers CELH  # just one ticker

Writes into docs/data/ (served by GitHub Pages to the dashboard):
    results.json      latest scan, full breakdown
    history.json      compact score log, used by backtest.py
    alert_state.json  when each ticker last texted you (prevents spam)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List

from scanner import alerts
from scanner.base import ERROR, SignalResult
from scanner.scoring import load_config, score_ticker
from scanner.signals import EVIDENCE, SIGNALS
from scanner.signals.stubs import STUBS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_CAP = 5000


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)


def load_watchlist(path: str) -> List[Dict[str, str]]:
    data = load_json(path, None)
    if not data or not isinstance(data.get("watchlist"), list):
        raise ValueError(f"{path} must contain a 'watchlist' list of {{keyword, ticker}} entries")
    out = []
    for e in data["watchlist"]:
        if e.get("ticker") and e.get("keyword"):
            out.append({"ticker": str(e["ticker"]).upper().strip(), "keyword": str(e["keyword"]).strip(),
                        "wikipedia": str(e.get("wikipedia") or "").strip()})
    return out


def trending_candidates(path: str, already: set, top: int) -> List[Dict[str, str]]:
    """Rising Reddit names that aren't on the watchlist get a full scan too."""
    data = load_json(path, {})
    out = []
    for r in data.get("rows", []):
        if len(out) >= top:
            break
        if r.get("status") == "rising" and r["ticker"] not in already:
            out.append({"ticker": r["ticker"], "keyword": r.get("name") or r["ticker"], "wikipedia": "",
                        "source": "trending"})
    return out


def last_close(ticker: str) -> Any:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        return round(float(hist["Close"].dropna().iloc[-1]), 4) if len(hist) else None
    except Exception:  # noqa: BLE001
        return None


def scan_one(ticker: str, keyword: str, cfg: Dict[str, Any], wikipedia: str = "") -> Dict[str, SignalResult]:
    results: Dict[str, SignalResult] = {}
    for name in cfg["weights"]:
        mod = SIGNALS.get(name)
        if mod is None:
            results[name] = SignalResult(name, detail=f"Unknown signal '{name}' in config.json.", status=ERROR)
            continue
        params = cfg.get("signals", {}).get(name, {})
        if name == "social_spike" and wikipedia:
            params = dict(params, wikipedia_article=wikipedia)
        try:
            results[name] = mod.run(ticker, keyword, params)
        except Exception as e:  # noqa: BLE001 - one broken source must not kill the scan
            traceback.print_exc()
            results[name] = SignalResult(name, detail=f"{type(e).__name__}: {str(e)[:160]}", status=ERROR)
        print(f"  {name:22s} {results[name].status:12s} trig={results[name].triggered!s:5s} "
              f"str={results[name].strength:.2f}  {results[name].detail[:90]}")
    return results


def dashboard_url() -> str:
    if os.environ.get("DASHBOARD_URL"):
        return os.environ["DASHBOARD_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/name", set automatically in Actions
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--watchlist", default=os.path.join(ROOT, "watchlist.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "data"))
    ap.add_argument("--tickers", default="", help="comma-separated subset of the watchlist")
    ap.add_argument("--no-alerts", action="store_true")
    ap.add_argument("--daily-summary", action="store_true",
                    help="also check S&P 500 big drops and text the end-of-day summary")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    watch = load_watchlist(args.watchlist)
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        watch = [w for w in watch if w["ticker"] in wanted]
    if not args.tickers:
        watch += trending_candidates(os.path.join(args.out, "trending.json"), {w["ticker"] for w in watch},
                                     int(cfg.get("trending", {}).get("auto_scan_top", 5)))
    threshold = float(cfg["alert_threshold"])
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    tickers = []
    for w in watch:
        print(f"\n== {w['ticker']} ({w['keyword']})")
        sig = scan_one(w["ticker"], w["keyword"], cfg, w["wikipedia"])
        scored = score_ticker(sig, cfg["weights"], threshold)
        for row in scored["signals"]:
            row["evidence"] = EVIDENCE.get(row["name"], "unknown")
        tickers.append({"ticker": w["ticker"], "keyword": w["keyword"], "last_close": last_close(w["ticker"]),
                        "source": w.get("source", "watchlist"), **scored})
        print(f"  -> {scored['summary']}")
        time.sleep(float(cfg.get("pause_between_tickers_seconds", 1)))

    tickers.sort(key=lambda t: -t["score"])
    results = {
        "generated_at": now.isoformat(timespec="seconds"),
        "alert_threshold": threshold,
        "hold_days": cfg["hold_days"],
        "weights": cfg["weights"],
        "total_weight": sum(cfg["weights"].values()),
        "paper_trading": cfg.get("paper_trading", {}),
        "not_implemented": [{"name": k, "detail": v} for k, v in STUBS.items()],
        "tickers": tickers,
    }
    save_json(os.path.join(args.out, "results.json"), results)

    history = load_json(os.path.join(args.out, "history.json"), [])
    for t in tickers:
        history.append({"t": results["generated_at"], "date": today, "ticker": t["ticker"],
                         "score": t["score"], "alert": t["alert"], "close": t["last_close"],
                         "fired": [s["name"] for s in t["signals"] if s["triggered"]]})
    save_json(os.path.join(args.out, "history.json"), history[-HISTORY_CAP:])

    state_path = os.path.join(args.out, "alert_state.json")
    state = load_json(state_path, {})
    cooldown = int(cfg.get("alert_cooldown_days", 3))
    to_send = [t for t in tickers if t["alert"] and alerts.should_alert(t["ticker"], t["score"], today, state, cooldown)]
    print(f"\n{sum(t['alert'] for t in tickers)} ticker(s) above threshold; {len(to_send)} new alert(s) to send.")
    if to_send and not args.no_alerts:
        if alerts.notify(to_send, dashboard_url()):
            for t in to_send:
                state[t["ticker"]] = {"date": today, "score": t["score"]}
            save_json(state_path, state)
    market_snapshot = update_market(cfg, args.out)
    if args.daily_summary:
        send_daily_summary(cfg, tickers, args.out, threshold, market_snapshot, no_send=args.no_alerts)
    return 0


def update_market(cfg: Dict[str, Any], out_dir: str) -> Dict[str, Any]:
    """S&P 500 movers for the Movers tab (and the summary text). Never fails the scan."""
    from scanner import market

    pct = float(cfg.get("daily_summary", {}).get("drop_threshold_pct", 10))
    try:
        snap = market.daily_market(out_dir, pct, int(cfg.get("movers_top_n", 10)))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        snap = {"status": "error", "market_date": None, "drops": [], "gainers": [], "losers": [],
                "threshold_pct": pct, "error": str(e)[:200]}
    if snap.get("status") == "ok" or not os.path.exists(os.path.join(out_dir, "market.json")):
        save_json(os.path.join(out_dir, "market.json"), snap)  # keep the last good snapshot on failure
    return snap


def send_daily_summary(cfg: Dict[str, Any], tickers: List[Dict[str, Any]], out_dir: str, threshold: float,
                       drops: Dict[str, Any], no_send: bool = False) -> None:
    from scanner import market

    opts = cfg.get("daily_summary", {})
    pct = float(opts.get("drop_threshold_pct", 10))
    rising = [r["ticker"] for r in load_json(os.path.join(out_dir, "trending.json"), {}).get("rows", [])
              if r.get("status") == "rising"]
    texts = market.compose_summary(market.new_york_today(), drops.get("market_date"), drops["drops"], pct,
                                   tickers, threshold, rising, dashboard_url())
    if drops["status"] != "ok":
        texts[0] = texts[0].replace("No S&P500 stock fell", "Couldn't check S&P500 drops; none known")
    print("[summary]\n" + "\n---\n".join(texts))
    if opts.get("enabled", True) and not no_send:
        alerts.send_texts(texts)
        alerts.send_ntfy("\n".join(texts))


if __name__ == "__main__":
    sys.exit(main())
