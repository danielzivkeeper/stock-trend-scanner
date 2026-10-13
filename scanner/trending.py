"""Trending: spot companies whose social-media chatter is spiking - including
ones NOT on your watchlist - so the full five-signal check can look at them.

EVIDENCE: attention spikes are real but SHORT-LIVED. Retail-attention studies
(Da, Engelberg & Gao 2011; WallStreetBets research after 2021) find a bump over
days to ~2 weeks, then a reversal. By the time a brand is viral, professional
funds usually already see it in paid card-spend / app-download data. Treat this
tab as "things worth researching", not "things to buy".

SOURCES (all free, all reachable from GitHub's servers - tested Oct 2026):
  - StockTwits: a stock-only social network where every message is tagged
    with its tickers. We read its public "trending symbols" list and each
    ticker's latest messages to estimate messages/day. No key needed.
  - Bluesky: public post search (no key). We search each tracked ticker and
    brand phrase over the last 24h and count posts that really mention it.
  - Reddit: only if REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set. Reddit's
    2025 "Responsible Builder Policy" requires approval for new API apps, so
    this is off by default.
  NOT included: TikTok (API limited to approved academic researchers) and
  Instagram (hashtag API needs Meta app review, 30 hashtags/week, no counts).
  Scraping either violates their Terms of Service. Viral TikTok/Instagram trends
  still echo on Bluesky/StockTwits and in the Wikipedia/Google social signal.

HOW NAMES ARE FOUND in a post: cashtags ($CELH, SEC-validated), bare tickers
(Reddit investing subs only), and brand phrases from brands.json ("hoka" ->
DECK). Search engines match loosely, so every hit is re-checked with the same
extractor. Private brands (Stanley, Owala...) are counted separately.

SPIKE RULE: today's level vs. that name's own daily baseline (z-score), per
source. Needs ~5 days of history before z-scores mean anything.

    python -m scanner.trending
"""
from __future__ import annotations

import html
import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from scanner.signals.social_spike import zscore_latest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "StockTrendScanner/1.0 (personal, read-only; github.com/danielzivkeeper/stock-trend-scanner)"

CASHTAG = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,5})(?![A-Za-z0-9])")
BARE = re.compile(r"(?<![A-Za-z0-9$])([A-Z]{2,5})(?![A-Za-z0-9])")

# Uppercase words people type that happen to be tickers or look like them.
STOPWORDS = set("""
A I AM AN ARE AS AT BE BY DO GO HE IF IN IS IT ME MY NO OF OK ON OR SO TO UP US WE
ALL AND ANY ARE BIG BUT CAN DAY DID FOR GET GOT HAS HAD HER HIM HIS HOW ITS LET MAY NEW
NOT NOW OLD ONE OUR OUT OWN PUT RUN SAY SEE SHE THE TOO TWO USE WAS WAY WHO WHY WIN YES YOU
ALSO BEST BEEN BOTH CASH COST EVER EDIT FREE FUND GAIN GOOD HAVE HOLD HUGE INTO JUST KEEP
LIKE LONG LOOK LOSS LOVE MADE MAKE MANY MORE MOST MOVE MUCH NEXT ONLY OPEN OVER PLAY REAL
SAFE SAME SELL SOME SURE TAKE THAN THAT THEM THEN THEY THIS VERY WANT WELL WERE WHAT WHEN
WILL WITH WORK YEAR YOUR ZERO
DD YOLO FOMO HODL ATH ATL IMO IMHO TLDR TL DR LOL LMAO WTF OMG FYI EOD EOW EOY YTD YOY QOQ
CEO CFO CTO COO CIO VP IPO SPAC ETF ETFS EPS PE PEG ROI ROE ROIC FCF EBIT EBITDA GAAP SEC
FDA FED FOMC CPI PPI GDP USA USD EUR GBP JPY CAD UK EU AI ML API IT IOS PC TV PR HR IRS
IRA ROTH LLC INC CO LTD NYSE OTC DOW SPX SPY QQQ VIX ITM OTM ATM IV DTE CALL CALLS PUTS
BUY BUYS BULL BEAR MOON PUMP DUMP RIP GG OP EV EVS NFT NFTS BTC ETH TA FA PT
""".split())

STATUS_ORDER = {"rising": 0, "building baseline": 1, "steady": 2, "below minimum": 3}


# ------------------------------------------------------------ extraction (pure)

def load_brands(path: str) -> Tuple[Dict[str, str], List[str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    brands = {str(k).lower().strip(): str(v).upper().strip() for k, v in data.get("brands", {}).items() if v}
    private = [str(p).lower().strip() for p in data.get("private", [])]
    return brands, private


def _phrase_regex(phrases: Iterable[str]) -> Optional["re.Pattern[str]"]:
    phrases = sorted({p for p in phrases if p}, key=len, reverse=True)  # longest first
    if not phrases:
        return None
    body = "|".join(re.escape(p) for p in phrases)
    # whole words only; optional plural/possessive ("hokas", "costco's")
    return re.compile(rf"(?<![A-Za-z0-9])({body})(?:'?s)?(?![A-Za-z0-9])", re.IGNORECASE)


class Extractor:
    """Finds tickers and brands in text. Pure - no network."""

    def __init__(self, brands: Dict[str, str], private: List[str], valid_tickers: Optional[Set[str]]):
        self.brands = brands
        self.valid = valid_tickers  # None = SEC list unavailable -> only tickers we already know
        self.brand_re = _phrase_regex(brands)
        self.private_re = _phrase_regex(private)
        self.known = set(brands.values())

    def _ok(self, t: str) -> bool:
        return t in self.valid if self.valid is not None else t in self.known

    def tickers(self, text: str, allow_bare: bool) -> Set[str]:
        # A cashtag is deliberate, so "$AI" counts even though "AI" alone is a stopword.
        found = {m.upper() for m in CASHTAG.findall(text) if self._ok(m.upper())}
        if allow_bare and not text.isupper():  # an all-caps rant isn't a list of tickers
            found |= {m for m in BARE.findall(text) if m not in STOPWORDS and self._ok(m)}
        if self.brand_re:
            found |= {self.brands[m.lower()] for m in self.brand_re.findall(text)}
        return found

    def private_brands(self, text: str) -> Set[str]:
        return {m.lower() for m in self.private_re.findall(text)} if self.private_re else set()


def _snippet(text: str) -> str:
    s = " ".join(text.split())
    return s[:140] + ("…" if len(s) > 140 else "")


def count_mentions(items: List[Dict[str, Any]], ex: Extractor, finance_subs: Set[str]) -> Dict[str, Any]:
    """Pure. items = [{id, sub, author, text, url}] -> counts per ticker.

    Each item counts at most once per ticker; distinct authors are tracked so
    one person spamming a ticker doesn't look like a crowd.
    """
    counts: Dict[str, int] = {}
    authors: Dict[str, Set[str]] = {}
    subs: Dict[str, Set[str]] = {}
    samples: Dict[str, List[Dict[str, str]]] = {}
    private: Dict[str, int] = {}
    seen: Set[str] = set()
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        text = it.get("text") or ""
        for t in ex.tickers(text, allow_bare=it["sub"].lower() in finance_subs):
            counts[t] = counts.get(t, 0) + 1
            authors.setdefault(t, set()).add(it.get("author") or "?")
            subs.setdefault(t, set()).add(it["sub"])
            if len(samples.setdefault(t, [])) < 2:
                samples[t].append({"text": _snippet(text), "url": it.get("url", ""), "sub": it["sub"]})
        for b in ex.private_brands(text):
            private[b] = private.get(b, 0) + 1
    return {"items": len(seen), "counts": counts,
            "authors": {t: len(a) for t, a in authors.items()},
            "subs": {t: sorted(s) for t, s in subs.items()},
            "samples": samples, "private": private}


def stocktwits_rate(messages: List[Dict[str, Any]], now: datetime) -> Tuple[float, int]:
    """Pure. Messages/day for one ticker from its newest messages (API returns 30).

    If the 30 messages span more than a day, count the ones in the last 24h.
    If they all fit in less than a day, extrapolate (30 in 3h ~ 240/day).
    Returns (messages_per_day, distinct_users_in_last_24h_or_sample).
    """
    times = []
    users: Set[str] = set()
    for m in messages:
        try:
            ts = datetime.strptime(m["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        times.append(ts)
        if now - ts <= timedelta(days=1):
            users.add(str((m.get("user") or {}).get("username", "?")))
    if not times:
        return 0.0, 0
    oldest = min(times)
    if now - oldest >= timedelta(days=1):
        return float(sum(1 for ts in times if now - ts <= timedelta(days=1))), len(users)
    hours = max((now - oldest).total_seconds() / 3600, 0.25)
    return round(len(times) / hours * 24, 1), len(users)


# ------------------------------------------------------------ history + ranking (pure)

def merge_day(history: Dict[str, Any], day: str, run: Dict[str, Any], mode: str = "sum",
              queried: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Pure. Folds one run into history[day].

    mode "sum": sampled sources (Reddit) - two runs a day add up, rate = per 1,000 items.
    mode "max": trailing-24h sources (Bluesky, StockTwits) - each run already covers a
                full day, so keep the larger reading instead of double counting.
    `queried` lists the tickers this source actually looked up today, so a ticker
    that wasn't checked isn't mistaken for "zero mentions" in its baseline.
    """
    h = history.setdefault(day, {"items": 0, "counts": {}, "authors": {}, "queried": []})
    h["items"] += run.get("items", 0)
    for key in ("counts", "authors"):
        for t, n in run[key].items():
            h[key][t] = h[key].get(t, 0) + n if mode == "sum" else max(h[key].get(t, 0), n)
    if queried is not None:
        h["queried"] = sorted(set(h.get("queried") or []) | set(queried))
    return history


def source_stat(history: Dict[str, Any], day: str, ticker: str, params: Dict[str, Any],
                normalize: bool) -> Optional[Dict[str, Any]]:
    """Pure. One ticker's reading from one source today vs. its own baseline."""
    today = history.get(day)
    if not today or ticker not in today["counts"]:
        return None
    baseline_days = int(params.get("baseline_days", 28))
    min_history = int(params.get("min_history_days", 5))

    def checked(h: Dict[str, Any]) -> bool:
        q = h.get("queried")
        return not q or ticker in q  # empty list = sampled source, every ticker was "checked"

    def value(h: Dict[str, Any]) -> float:
        c = float(h["counts"].get(ticker, 0))
        if normalize:
            return c / h["items"] * 1000 if h.get("items") else 0.0
        return c

    days = [d for d in sorted(history) if d < day and checked(history[d])][-baseline_days:]
    series = [value(history[d]) for d in days]
    v = value(today)
    z = zscore_latest(series + [v], len(series)) if len(series) >= min_history else None
    base = statistics.mean(series) if series else None
    count = today["counts"][ticker]
    authors = today["authors"].get(ticker, 0)
    if count < float(params.get("min_mentions", 5)) or authors < int(params.get("min_authors", 3)):
        status = "below minimum"
    elif z is None:
        status = "building baseline"
    elif z >= float(params.get("min_zscore", 2.0)):
        status = "rising"
    else:
        status = "steady"
    return {"value": round(v, 2), "mentions": count, "authors": authors, "status": status,
            "baseline": None if base is None else round(base, 2),
            "zscore": None if z is None else round(z, 2),
            "vs_baseline": round(v / base, 1) if base else None}


def build_rows(histories: Dict[str, Tuple[Dict[str, Any], bool]], day: str, params: Dict[str, Any],
               always: Iterable[str] = (), st_trending: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Pure. One row per ticker combining every source; best status wins."""
    st_trending = st_trending or {}
    tickers: Set[str] = set(always) | set(st_trending)
    for hist, _ in histories.values():
        tickers |= set(hist.get(day, {}).get("counts", {}))
    rows = []
    for t in tickers:
        stats = {src: s for src, (hist, norm) in histories.items()
                 if (s := source_stat(hist, day, t, params, norm)) is not None}
        statuses = [s["status"] for s in stats.values()] or ["below minimum"]
        status = min(statuses, key=lambda s: STATUS_ORDER[s])
        if status == "below minimum" and t not in st_trending and t not in set(always):
            continue
        zs = [s["zscore"] for s in stats.values() if s["zscore"] is not None and s["status"] != "below minimum"]
        rows.append({"ticker": t, "status": status, "sources": stats,
                     "max_zscore": max(zs) if zs else None,
                     "mentions": sum(s["mentions"] for s in stats.values()),
                     "stocktwits_trending_rank": st_trending.get(t)})
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], -(r["max_zscore"] or 0),
                             r["stocktwits_trending_rank"] or 999, -r["mentions"]))
    return rows


# ------------------------------------------------------------ fetchers (network)

def _get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    import requests

    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_stocktwits_trending() -> List[Dict[str, Any]]:
    data = _get_json("https://api.stocktwits.com/api/2/trending/symbols.json")
    out = []
    for i, s in enumerate(data.get("symbols", []), 1):
        sym = str(s.get("symbol", "")).upper()
        if sym and "." not in sym:  # skip crypto (BTC.X) and foreign listings
            out.append({"ticker": sym, "name": s.get("title") or sym, "rank": i})
    return out


def fetch_stocktwits(tickers: List[str], pause: float) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, str]]]]:
    now = datetime.now(timezone.utc)
    counts, authors, samples = {}, {}, {}
    for t in tickers:
        try:
            msgs = _get_json(f"https://api.stocktwits.com/api/2/streams/symbol/{t}.json").get("messages", [])
        except Exception as e:  # noqa: BLE001
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code == 429:
                print("  stocktwits: rate limited - stopping early")
                break
            continue  # unknown symbol etc.
        rate, users = stocktwits_rate(msgs, now)
        counts[t], authors[t] = rate, users
        samples[t] = [{"text": _snippet(html.unescape(m.get("body", ""))), "sub": "stocktwits",
                       "url": f"https://stocktwits.com/message/{m.get('id')}"} for m in msgs[:2]]
        time.sleep(pause)
    return {"items": 0, "counts": counts, "authors": authors}, samples


def fetch_bluesky(queries: Dict[str, str], pause: float) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """queries = {search text: ticker}. Returns (posts from the last 24h, {query: hours covered}).

    Without an account Bluesky serves only the first page (100 posts) per search;
    page 2 is refused. When a search fills that page, the hours it covers let us
    estimate the full-day rate (see saturated_estimates).
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    items, saturated = [], {}
    for q in queries:
        try:
            data = _get_json("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                             {"q": q, "limit": 100, "sort": "latest", "since": since})
        except Exception as e:  # noqa: BLE001
            print(f"  bluesky '{q}': {type(e).__name__}")
            continue
        posts = data.get("posts", [])
        oldest = None
        for post in posts:
            uri = post.get("uri", "")
            handle = (post.get("author") or {}).get("handle", "?")
            created = (post.get("record") or {}).get("createdAt", "")
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                oldest = ts if oldest is None or ts < oldest else oldest
            except ValueError:
                pass
            items.append({"id": uri, "sub": "bluesky", "author": handle, "query": q,
                          "text": (post.get("record") or {}).get("text", ""),
                          "url": f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}"})
        if len(posts) >= 100 and oldest is not None:
            saturated[q] = max((now - oldest).total_seconds() / 3600, 0.25)
        time.sleep(pause)
    return items, saturated


def saturated_estimates(items: List[Dict[str, Any]], saturated: Dict[str, float], queries: Dict[str, str],
                        ex: Extractor) -> Dict[str, float]:
    """Pure. For searches that hit the 100-post cap: verified hits / hours covered x 24."""
    est: Dict[str, float] = {}
    for q, hours in saturated.items():
        t = queries.get(q)
        if not t or hours >= 24:
            continue
        hits = sum(1 for it in items if it.get("query") == q and t in ex.tickers(it["text"], allow_bare=False))
        if hits:
            est[t] = max(est.get(t, 0.0), round(hits / hours * 24, 1))
    return est


def fetch_reddit(subreddits: List[str], posts: int, comments: int, max_age_hours: int) -> List[Dict[str, Any]]:
    import praw

    reddit = praw.Reddit(client_id=os.environ["REDDIT_CLIENT_ID"],
                         client_secret=os.environ["REDDIT_CLIENT_SECRET"], user_agent=UA)
    reddit.read_only = True
    cutoff = time.time() - max_age_hours * 3600
    items: List[Dict[str, Any]] = []
    for name in subreddits:
        try:
            sub = reddit.subreddit(name)
            for p in sub.new(limit=posts):
                if p.created_utc >= cutoff:
                    items.append({"id": "t3_" + p.id, "sub": name, "author": str(p.author),
                                  "text": f"{p.title}\n{p.selftext or ''}",
                                  "url": "https://www.reddit.com" + p.permalink})
            for c in sub.comments(limit=comments):
                if c.created_utc >= cutoff:
                    items.append({"id": "t1_" + c.id, "sub": name, "author": str(c.author), "text": c.body or "",
                                  "url": "https://www.reddit.com" + c.permalink})
        except Exception as e:  # noqa: BLE001 - a private/banned sub shouldn't stop the rest
            print(f"  r/{name}: skipped ({type(e).__name__}: {str(e)[:80]})")
    return items


# ------------------------------------------------------------ main

def main() -> int:
    from scanner.run_scan import load_json, load_watchlist, save_json
    from scanner.scoring import load_config

    cfg = load_config(os.path.join(ROOT, "config.json"))
    params = cfg.get("trending", {})
    out_dir = os.path.join(ROOT, "docs", "data")
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    watch = load_watchlist(os.path.join(ROOT, "watchlist.json"))
    watch_tickers = [w["ticker"] for w in watch]
    brands, private = load_brands(os.path.join(ROOT, "brands.json"))

    company: Dict[str, Any] = {}
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if email:
        try:
            from scanner.signals.insider_buying import sec_company_map
            company = sec_company_map(email)
        except Exception as e:  # noqa: BLE001
            print(f"[trending] SEC ticker list unavailable ({e})")

    # Universe: watchlist + brand tickers + whatever StockTwits says is trending.
    st_trend: List[Dict[str, Any]] = []
    if params.get("use_stocktwits", True):
        try:
            st_trend = fetch_stocktwits_trending()
        except Exception as e:  # noqa: BLE001
            print(f"[trending] StockTwits trending unavailable: {e}")
    st_rank = {s["ticker"]: s["rank"] for s in st_trend}
    universe = sorted(set(watch_tickers) | set(brands.values()) | set(st_rank))
    valid = (set(company) | set(universe)) if company else None
    ex = Extractor(brands, private, valid)
    if valid is None:
        ex.known |= set(universe)

    history = load_json(os.path.join(out_dir, "trending_history.json"), {})
    histories: Dict[str, Tuple[Dict[str, Any], bool]] = {}
    samples: Dict[str, List[Dict[str, str]]] = {}
    private_counts: Dict[str, int] = {}
    used = []

    if params.get("use_stocktwits", True):
        run, st_samples = fetch_stocktwits(universe, float(params.get("stocktwits_pause_seconds", 1.0)))
        if run["counts"]:
            merge_day(history.setdefault("stocktwits", {}), day, run, mode="max", queried=run["counts"])
            histories["stocktwits"] = (history["stocktwits"], False)
            used.append(f"StockTwits ({len(run['counts'])} tickers)")
            for t, s in st_samples.items():
                samples.setdefault(t, []).extend(s)
        print(f"[trending] stocktwits: {len(run['counts'])} tickers measured")

    if params.get("use_bluesky", True):
        queries: Dict[str, str] = {f"${t}": t for t in universe}
        queries.update({b: t for b, t in brands.items()})
        queries.update({w["keyword"]: w["ticker"] for w in watch})
        queries.update({p: "private" for p in private})
        items, saturated = fetch_bluesky(queries, float(params.get("bluesky_pause_seconds", 0.3)))
        run = count_mentions(items, ex, set())
        for t, est in saturated_estimates(items, saturated, queries, ex).items():
            run["counts"][t] = max(run["counts"].get(t, 0), est)  # busy names: full-day estimate
        merge_day(history.setdefault("bluesky", {}), day, run, mode="max", queried=universe)
        histories["bluesky"] = (history["bluesky"], False)
        used.append(f"Bluesky ({run['items']} posts)")
        for t, s in run["samples"].items():
            samples.setdefault(t, []).extend(s)
        for b, n in run["private"].items():
            private_counts[b] = private_counts.get(b, 0) + n
        print(f"[trending] bluesky: {run['items']} posts, {len(run['counts'])} tickers mentioned")

    if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
        subs = params.get("finance_subreddits", []) + params.get("consumer_subreddits", [])
        items = fetch_reddit(subs, int(params.get("posts_per_sub", 100)), int(params.get("comments_per_sub", 500)),
                             int(params.get("max_age_hours", 48)))
        run = count_mentions(items, ex, {s.lower() for s in params.get("finance_subreddits", [])})
        merge_day(history.setdefault("reddit", {}), day, run, mode="sum")
        histories["reddit"] = (history["reddit"], True)
        used.append(f"Reddit ({run['items']} posts/comments)")
        for t, s in run["samples"].items():
            samples.setdefault(t, []).extend(s)
        for b, n in run["private"].items():
            private_counts[b] = private_counts.get(b, 0) + n

    keep_days = int(params.get("history_days", 60))
    for src in list(history):
        history[src] = {d: history[src][d] for d in sorted(history[src])[-keep_days:]}
        if src in histories:
            histories[src] = (history[src], histories[src][1])
    save_json(os.path.join(out_dir, "trending_history.json"), history)

    names = {v: k for k, v in brands.items()}
    st_names = {s["ticker"]: s["name"] for s in st_trend}
    rows = build_rows(histories, day, params, always=watch_tickers, st_trending=st_rank)
    for r in rows:
        r["name"] = ((company.get(r["ticker"]) or {}).get("title") or st_names.get(r["ticker"])
                     or names.get(r["ticker"], r["ticker"]))
        r["on_watchlist"] = r["ticker"] in watch_tickers
        r["samples"] = samples.get(r["ticker"], [])[:3]
    days_of_history = max((len(h) for h, _ in histories.values()), default=0)
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "status": "ok" if histories else "no_sources",
        "sources": used,
        "history_days": days_of_history,
        "note": "",
        "rows": rows[:int(params.get("max_rows", 40))],
        "private": sorted(({"brand": b, "mentions": n} for b, n in private_counts.items()),
                          key=lambda x: -x["mentions"]),
    }
    min_hist = int(params.get("min_history_days", 5))
    if days_of_history < min_hist:
        out["note"] = (f"Day {days_of_history} of {min_hist} building a baseline - until then nothing can be "
                       f"'rising'; names are ranked by StockTwits trending rank and raw mentions.")
    save_json(os.path.join(out_dir, "trending.json"), out)
    rising = [r["ticker"] for r in rows if r["status"] == "rising"]
    print(f"[trending] sources: {', '.join(used) or 'none'}; rising: {rising or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
