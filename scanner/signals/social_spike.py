"""Signal 5: Social attention spike (Wikipedia views, Google Trends, Reddit).

EVIDENCE: REAL BUT SHORT-LIVED - weighted lowest, treat as confirmation only.
  - Da, Engelberg & Gao (2011, "In Search of Attention"): a jump in Google
    search volume predicts HIGHER prices over the next ~2 weeks and a
    REVERSAL within the year. Retail-attention spikes (Reddit/WSB) show the
    same pattern, often reversing within DAYS.
  - So a spike is "people are looking" - not "it will keep going up".

DATA:
  - Wikipedia page views (official Wikimedia API, free, no key). The most
    reliable source here: it works from GitHub's servers. Moat et al. (2013)
    and others use Wikipedia views as an investor-attention proxy. The article
    comes from the watchlist's optional "wikipedia" field (else the keyword).
  - Google Trends via pytrends (unofficial, no key). Google rate-limits
    aggressively, especially from cloud IPs like GitHub's runners, so expect
    occasional HTTP 429 -> the module reports "unavailable" for that source.
  - Reddit via praw (free "script" app from reddit.com/prefs/apps). Reads
    REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET from the environment; silently
    skipped when they're not set.

Rule: z-score of the latest reading vs. a rolling baseline of earlier readings.
Fires when either source has z >= min_zscore.
"""
from __future__ import annotations

import os
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from scanner.base import SignalResult, scaled_strength, unavailable

NAME = "social_spike"


def zscore_latest(series: List[float], baseline_window: int) -> Optional[float]:
    """z-score of the last value vs. the `baseline_window` values before it.

    Returns None when there isn't enough history. A flat baseline (stdev 0)
    returns 0.0 if the latest equals it, otherwise a large finite number.
    """
    if len(series) < 3:
        return None
    latest = float(series[-1])
    base = [float(x) for x in series[-1 - baseline_window:-1]]
    if len(base) < 2:
        return None
    mu = statistics.mean(base)
    sd = statistics.pstdev(base)
    if sd == 0:
        return 0.0 if latest == mu else (10.0 if latest > mu else -10.0)
    return (latest - mu) / sd


def evaluate(z_by_source: Dict[str, Optional[float]], params: Dict[str, Any],
             notes: Dict[str, str]) -> SignalResult:
    """Pure function. `z_by_source` like {"google_trends": 2.4, "reddit": None}."""
    min_z = float(params.get("min_zscore", 2.0))
    full_mult = float(params.get("full_strength_multiple", 2.0))
    usable = {k: v for k, v in z_by_source.items() if v is not None}
    raw = {"zscores": {k: (None if v is None else round(v, 2)) for k, v in z_by_source.items()},
           "notes": notes}
    if not usable:
        why = "; ".join(f"{k}: {v}" for k, v in notes.items()) or "no social data sources available"
        return unavailable(NAME, f"No social data ({why}).", raw)

    parts = [f"{k.replace('_', ' ')} z={v:+.1f}" for k, v in usable.items()]
    best_src, best_z = max(usable.items(), key=lambda kv: kv[1])
    if best_z < min_z:
        return SignalResult(NAME, False, 0.0,
                            f"No unusual attention ({', '.join(parts)}; need z >= {min_z:g}).", raw)
    return SignalResult(NAME, True, scaled_strength(best_z, min_z, full_mult),
                        f"Attention spike: {', '.join(parts)}. Short-lived signal - often reverses within days.",
                        raw)


# ---------------------------------------------------------------- data fetch

def _google_trends_series(keyword: str, timeframe: str) -> List[float]:
    from pytrends.request import TrendReq

    py = TrendReq(hl="en-US", tz=300, timeout=(10, 30))
    py.build_payload([keyword], timeframe=timeframe)
    df = py.interest_over_time()
    if df is None or df.empty or keyword not in df:
        return []
    if "isPartial" in df:
        df = df[~df["isPartial"].astype(bool)]  # drop today's incomplete bucket
    return [float(x) for x in df[keyword].tolist()]


WIKI_UA = "StockTrendScanner/1.0 (https://github.com/danielzivkeeper/stock-trend-scanner)"


def _wikipedia_daily_views(article: str, days: int) -> List[float]:
    import requests
    from urllib.parse import quote

    from scanner.cache import WIKI_LIMIT, cache

    def resolve() -> str:
        # Follow redirects ("E.l.f. Cosmetics" -> "E.l.f.") - views are counted on the real title.
        for attempt in range(5):
            WIKI_LIMIT.wait()
            r = requests.get("https://en.wikipedia.org/w/api.php", headers={"User-Agent": WIKI_UA}, timeout=30,
                             params={"action": "query", "titles": article, "redirects": 1, "format": "json",
                                     "maxlag": 5})
            try:
                q = r.json()
            except ValueError:  # rate-limited / busy: Wikipedia answers with an HTML page
                time.sleep(2 ** attempt)
                continue
            if "error" in q:  # e.g. maxlag - servers busy, try again shortly
                time.sleep(2 ** attempt)
                continue
            page = next(iter(q["query"]["pages"].values()))
            return "" if "missing" in page else page["title"].replace(" ", "_")
        raise RuntimeError("Wikipedia busy (rate limited)")

    title = cache("wiki_titles").get_or_fetch(article, 24 * 30, resolve)
    if not title:
        raise LookupError(f"no Wikipedia article '{article}'")
    end = datetime.now(timezone.utc).date() - timedelta(days=1)  # yesterday = last complete day
    start = end - timedelta(days=days)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           f"{quote(title, safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    for attempt in range(4):
        WIKI_LIMIT.wait()
        r = requests.get(url, headers={"User-Agent": WIKI_UA}, timeout=30)
        if r.status_code != 429:
            break
        time.sleep(2 ** attempt)  # rate limited: back off and retry
    r.raise_for_status()
    return [float(i["views"]) for i in r.json().get("items", [])]


def _reddit_daily_counts(ticker: str, subreddits: List[str], days: int) -> Optional[List[float]]:
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        return None
    import praw

    reddit = praw.Reddit(client_id=cid, client_secret=secret,
                         user_agent="personal-stock-trend-scanner/1.0 (read-only)")
    reddit.read_only = True
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    counts: Counter = Counter()
    query = f'"{ticker}" OR "${ticker}"'
    for post in reddit.subreddit("+".join(subreddits)).search(query, sort="new", time_filter="month", limit=500):
        created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
        if created >= start:
            counts[(now - created).days] += 1
    # oldest -> newest; bucket 0 = the most recent 24h
    return [float(counts.get(d, 0)) for d in range(days - 1, -1, -1)]


def run(ticker: str, keyword: str, params: Dict[str, Any]) -> SignalResult:
    z: Dict[str, Optional[float]] = {}
    notes: Dict[str, str] = {}

    if params.get("use_wikipedia", True):
        article = params.get("wikipedia_article") or keyword
        try:
            views = _wikipedia_daily_views(article, int(params.get("wikipedia_lookback_days", 60)))
            z["wikipedia"] = zscore_latest(views, int(params.get("wikipedia_baseline_window", 28)))
            if z["wikipedia"] is None:
                notes["wikipedia"] = "not enough history"
        except Exception as e:  # noqa: BLE001
            z["wikipedia"] = None
            notes["wikipedia"] = f"{type(e).__name__}: {str(e)[:80]}"

    if params.get("use_google_trends", True):
        try:
            series = _google_trends_series(keyword, params.get("trends_timeframe", "today 3-m"))
            z["google_trends"] = zscore_latest(series, int(params.get("trends_baseline_window", 28)))
            if z["google_trends"] is None:
                notes["google_trends"] = "not enough history"
        except Exception as e:  # noqa: BLE001 - 429s are routine; degrade
            z["google_trends"] = None
            notes["google_trends"] = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(float(params.get("trends_pause_seconds", 5)))  # be polite; reduces 429s

    try:
        counts = _reddit_daily_counts(ticker, params.get("reddit_subreddits", ["wallstreetbets", "stocks"]),
                                      int(params.get("reddit_lookback_days", 30)))
        if counts is None:
            notes["reddit"] = "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set (skipped)"
        else:
            z["reddit"] = zscore_latest(counts, int(params.get("reddit_baseline_window", 21)))
    except Exception as e:  # noqa: BLE001
        z["reddit"] = None
        notes["reddit"] = f"{type(e).__name__}: {str(e)[:80]}"

    return evaluate(z, params, notes)
