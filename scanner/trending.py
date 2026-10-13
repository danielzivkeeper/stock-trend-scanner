"""Trending: find companies whose Reddit mentions are spiking - including ones
NOT on your watchlist - so the full five-signal check can look at them.

EVIDENCE: attention spikes are real but SHORT-LIVED. Retail-attention studies
(Da, Engelberg & Gao 2011; WallStreetBets research after 2021) find a bump over
days to ~2 weeks, then a reversal. By the time a brand is viral, professional
funds usually already see it in paid card-spend / app-download data. Treat this
tab as "things worth researching", not "things to buy".

WHY ONLY REDDIT: TikTok's API is limited to approved academic researchers, and
Instagram's hashtag API needs Meta app review, caps you at 30 hashtags/week and
returns posts, not counts. Scraping either violates their Terms of Service.
Viral TikTok/Instagram trends still show up indirectly in Reddit, Wikipedia and
Google searches.

HOW NAMES ARE FOUND in each post/comment:
  1. Cashtags ($CELH) - kept only if the SEC lists the ticker.
  2. Bare tickers (CELH) - only in investing subreddits, only if SEC-listed, and
     never common words/acronyms (STOPWORDS). "ALL" and "IT" are real tickers.
  3. Brand phrases from brands.json ("hoka" -> DECK). Private brands (Stanley,
     Owala...) are counted separately and never scanned - there's no stock.

SPIKE RULE: mentions per 1,000 scanned items today vs. that name's own daily
baseline (z-score). Needs ~5 days of history before z-scores mean anything.

    python -m scanner.trending
"""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from scanner.signals.social_spike import zscore_latest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        self.valid = valid_tickers  # None = SEC list unavailable -> only cashtags/brands we already know
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
                snippet = " ".join(text.split())
                samples[t].append({"text": snippet[:140] + ("…" if len(snippet) > 140 else ""),
                                   "url": it.get("url", ""), "sub": it["sub"]})
        for b in ex.private_brands(text):
            private[b] = private.get(b, 0) + 1
    return {"items": len(seen), "counts": counts,
            "authors": {t: len(a) for t, a in authors.items()},
            "subs": {t: sorted(s) for t, s in subs.items()},
            "samples": samples, "private": private}


def merge_day(history: Dict[str, Any], day: str, run: Dict[str, Any]) -> Dict[str, Any]:
    """Pure. Adds one run's counts into history[day] (two runs a day add up)."""
    h = history.setdefault(day, {"items": 0, "counts": {}, "authors": {}})
    h["items"] += run["items"]
    for key in ("counts", "authors"):
        for t, n in run[key].items():
            h[key][t] = h[key].get(t, 0) + n
    return history


def rank(history: Dict[str, Any], day: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pure. Scores every name seen today against its own baseline."""
    min_mentions = int(params.get("min_mentions", 5))
    min_authors = int(params.get("min_authors", 3))
    min_z = float(params.get("min_zscore", 2.0))
    baseline_days = int(params.get("baseline_days", 28))
    min_history = int(params.get("min_history_days", 5))

    days = sorted(d for d in history if d < day)[-baseline_days:]
    today = history.get(day, {"items": 0, "counts": {}, "authors": {}})
    if not today["items"]:
        return []
    rows = []
    for t, n in today["counts"].items():
        authors = today["authors"].get(t, 0)
        if n < min_mentions or authors < min_authors:
            continue
        rate = n / today["items"] * 1000
        series = [history[d]["counts"].get(t, 0) / history[d]["items"] * 1000 for d in days if history[d]["items"]]
        base = statistics.mean(series) if series else 0.0
        z = zscore_latest(series + [rate], len(series)) if len(series) >= min_history else None
        if z is None:
            status = "building baseline"
        elif z >= min_z:
            status = "rising"
        else:
            status = "steady"
        rows.append({"ticker": t, "mentions": n, "authors": authors, "per_1000": round(rate, 2),
                     "baseline_per_1000": round(base, 2), "zscore": None if z is None else round(z, 2),
                     "vs_baseline": round(rate / base, 1) if base > 0 else None, "status": status})
    order = {"rising": 0, "building baseline": 1, "steady": 2}
    rows.sort(key=lambda r: (order[r["status"]], -(r["zscore"] or 0), -r["mentions"]))
    return rows


# ------------------------------------------------------------ Reddit fetch

def fetch_reddit(subreddits: List[str], posts: int, comments: int, max_age_hours: int) -> List[Dict[str, Any]]:
    import praw

    reddit = praw.Reddit(client_id=os.environ["REDDIT_CLIENT_ID"],
                         client_secret=os.environ["REDDIT_CLIENT_SECRET"],
                         user_agent="StockTrendScanner/1.0 (personal, read-only; "
                                    "github.com/danielzivkeeper/stock-trend-scanner)")
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
            print(f"  r/{name}: {len(items)} items so far")
        except Exception as e:  # noqa: BLE001 - a private/banned sub shouldn't stop the rest
            print(f"  r/{name}: skipped ({type(e).__name__}: {str(e)[:80]})")
    return items


def main() -> int:
    from scanner.run_scan import load_json, load_watchlist, save_json
    from scanner.scoring import load_config

    cfg = load_config(os.path.join(ROOT, "config.json"))
    params = cfg.get("trending", {})
    out_dir = os.path.join(ROOT, "docs", "data")
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    watch = {w["ticker"] for w in load_watchlist(os.path.join(ROOT, "watchlist.json"))}

    base = {"generated_at": now.isoformat(timespec="seconds"), "status": "ok", "note": "", "rows": [],
            "private": [], "items_scanned": 0, "subreddits": params.get("finance_subreddits", []) +
            params.get("consumer_subreddits", [])}
    if not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
        base.update(status="needs_credentials",
                    note="Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET secrets to turn this on (see README).")
        save_json(os.path.join(out_dir, "trending.json"), base)
        print("[trending] Reddit credentials not set - skipped.")
        return 0

    brands, private = load_brands(os.path.join(ROOT, "brands.json"))
    valid = None
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if email:
        try:
            from scanner.signals.insider_buying import sec_company_map
            company = sec_company_map(email)
            valid = set(company)
        except Exception as e:  # noqa: BLE001
            print(f"[trending] SEC ticker list unavailable ({e}); only known brands/cashtags count.")
            company = {}
    else:
        company = {}
    ex = Extractor(brands, private, valid)
    finance = {s.lower() for s in params.get("finance_subreddits", [])}

    items = fetch_reddit(base["subreddits"], int(params.get("posts_per_sub", 100)),
                         int(params.get("comments_per_sub", 500)), int(params.get("max_age_hours", 48)))
    run = count_mentions(items, ex, finance)
    history = load_json(os.path.join(out_dir, "trending_history.json"), {})
    merge_day(history, day, run)
    keep = sorted(history)[-int(params.get("history_days", 60)):]
    history = {d: history[d] for d in keep}
    save_json(os.path.join(out_dir, "trending_history.json"), history)

    names = {v: k for k, v in brands.items()}  # ticker -> one brand phrase
    rows = rank(history, day, params)
    for r in rows:
        r["name"] = (company.get(r["ticker"]) or {}).get("title") or names.get(r["ticker"], r["ticker"])
        r["on_watchlist"] = r["ticker"] in watch
        r["subs"] = run["subs"].get(r["ticker"], [])
        r["samples"] = run["samples"].get(r["ticker"], [])
    base.update(rows=rows[:int(params.get("max_rows", 40))], items_scanned=run["items"],
                history_days=len(history),
                private=sorted(({"brand": b, "mentions": n} for b, n in run["private"].items()),
                               key=lambda x: -x["mentions"]))
    if len(history) < int(params.get("min_history_days", 5)):
        base["note"] = (f"Day {len(history)} of building a baseline - spike detection starts after "
                        f"{params.get('min_history_days', 5)} days. Until then, names are ranked by raw mentions.")
    save_json(os.path.join(out_dir, "trending.json"), base)
    rising = [r["ticker"] for r in rows if r["status"] == "rising"]
    print(f"[trending] {run['items']} items, {len(rows)} names above minimums, rising: {rising or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
