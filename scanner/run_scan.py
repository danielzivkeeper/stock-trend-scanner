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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scanner import alerts
from scanner.base import ERROR, SignalResult
from scanner.scoring import load_config, score_ticker
from scanner.signals import EVIDENCE, SIGNALS
from scanner.signals.stubs import STUBS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_CAP = 40000


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
                        "source": "trending", "sector": ""})
    return out


def last_close(ticker: str) -> Any:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        return round(float(hist["Close"].dropna().iloc[-1]), 4) if len(hist) else None
    except Exception:  # noqa: BLE001
        return None


def scan_one(ticker: str, keyword: str, cfg: Dict[str, Any], wikipedia: str = "",
             log: Optional[List[str]] = None) -> Dict[str, SignalResult]:
    results: Dict[str, SignalResult] = {}
    log = log if log is not None else []
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
        log.append(f"  {name:22s} {results[name].status:12s} trig={results[name].triggered!s:5s} "
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
    threshold = float(cfg["alert_threshold"])
    watch_threshold = float(cfg.get("watch_threshold", threshold))
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    # 1) One bulk price download for the whole S&P 500: Movers tab + every stock's last close.
    market_snapshot = update_market(cfg, args.out)
    closes = market_snapshot.pop("_last_close", {})

    # 2) What to scan: your watchlist first, then the S&P 500, then rising Trending names.
    universe = build_universe(cfg, args)
    print(f"Scanning {len(universe)} stocks "
          f"({sum(u['source'] == 'watchlist' for u in universe)} watchlist, "
          f"{sum(u['source'] == 'sp500' for u in universe)} S&P 500, "
          f"{sum(u['source'] == 'trending' for u in universe)} trending)")

    def work(w: Dict[str, Any]) -> Dict[str, Any]:
        log: List[str] = [f"\n== {w['ticker']} ({w['keyword']})"]
        sig = scan_one(w["ticker"], w["keyword"], cfg, w.get("wikipedia", ""), log)
        scored = score_ticker(sig, cfg["weights"], threshold)
        log.append(f"  -> {scored['summary']}")
        print("\n".join(log), flush=True)
        tier = "alert" if scored["alert"] else "watch" if scored["score"] >= watch_threshold else None
        keep_raw = w["source"] != "sp500" or tier is not None
        return {"ticker": w["ticker"], "keyword": w["keyword"], "source": w["source"],
                "on_watchlist": w.get("on_watchlist", False), "sector": w.get("sector", ""),
                "last_close": closes.get(w["ticker"]) or last_close(w["ticker"]), "tier": tier,
                "score": scored["score"], "alert": scored["alert"], "summary": scored["summary"],
                "math": scored["explanation"][-1],
                "signals": [dict(r, evidence=EVIDENCE.get(r["name"], "unknown"),
                                 raw=r["raw"] if (keep_raw or r["triggered"]) else {})
                            for r in scored["signals"]]}

    with ThreadPoolExecutor(max_workers=int(cfg.get("scan_workers", 8))) as pool:
        tickers = list(pool.map(work, universe))
    from scanner import cache as disk_cache
    disk_cache.cache("form4").prune(24 * 60)  # filings older than ~60 days are never looked at again
    disk_cache.save_all()

    tickers.sort(key=lambda t: -t["score"])
    results = {
        "generated_at": now.isoformat(timespec="seconds"),
        "alert_threshold": threshold,
        "watch_threshold": watch_threshold,
        "hold_days": cfg["hold_days"],
        "weights": cfg["weights"],
        "total_weight": sum(cfg["weights"].values()),
        "paper_trading": cfg.get("paper_trading", {}),
        "not_implemented": [{"name": k, "detail": v} for k, v in STUBS.items()],
        "scanned": len(tickers),
        "tickers": tickers,
    }
    save_json(os.path.join(args.out, "results.json"), results)

    # Score log for the track record: anything that scored at all, plus every watchlist stock.
    history = load_json(os.path.join(args.out, "history.json"), [])
    keep_min = float(cfg.get("history_min_score", 1.0))
    for t in tickers:
        if t["score"] >= keep_min or t["on_watchlist"]:
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
    if args.daily_summary:
        send_daily_summary(cfg, tickers, args.out, threshold, market_snapshot, no_send=args.no_alerts)
    return 0


def build_universe(cfg: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    from scanner import market

    watch = load_watchlist(args.watchlist)
    out = [dict(w, source="watchlist", on_watchlist=True) for w in watch]
    seen = {w["ticker"] for w in out}
    if cfg.get("scan_sp500", True):
        stocks = market.load_constituents(os.path.join(args.out, "sp500_constituents.json"))
        for t in sorted(stocks):
            if t not in seen:
                v = stocks[t]
                out.append({"ticker": t, "keyword": v["name"], "wikipedia": v.get("wiki", "").replace("_", " "),
                            "sector": v.get("sector", ""), "source": "sp500"})
                seen.add(t)
            else:
                for o in out:
                    if o["ticker"] == t:
                        o["sector"] = stocks[t].get("sector", "")
    out += trending_candidates(os.path.join(args.out, "trending.json"), seen,
                               int(cfg.get("trending", {}).get("auto_scan_top", 5)))
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        out = [o for o in out if o["ticker"] in wanted]
    return out


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
        # keep the last good snapshot on failure; the per-stock closes are only used in memory
        save_json(os.path.join(out_dir, "market.json"), {k: v for k, v in snap.items() if not k.startswith("_")})
    return snap


def send_daily_summary(cfg: Dict[str, Any], tickers: List[Dict[str, Any]], out_dir: str, threshold: float,
                       drops: Dict[str, Any], no_send: bool = False) -> None:
    from scanner import market

    opts = cfg.get("daily_summary", {})
    pct = float(opts.get("drop_threshold_pct", 10))
    rising = [r["ticker"] for r in load_json(os.path.join(out_dir, "trending.json"), {}).get("rows", [])
              if r.get("status") == "rising"]
    texts = market.compose_summary(market.new_york_today(), drops.get("market_date"), drops["drops"], pct,
                                   tickers, threshold, rising, dashboard_url(),
                                   watch_threshold=cfg.get("watch_threshold"))
    if drops["status"] != "ok":
        texts[0] = texts[0].replace("No S&P500 stock fell", "Couldn't check S&P500 drops; none known")
    print("[summary]\n" + "\n---\n".join(texts))
    if opts.get("enabled", True) and not no_send:
        alerts.send_texts(texts)
        alerts.send_ntfy("\n".join(texts))


if __name__ == "__main__":
    sys.exit(main())
