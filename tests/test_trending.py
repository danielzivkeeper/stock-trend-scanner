"""Offline tests for Reddit mention extraction and spike ranking."""
import os
import unittest

from datetime import datetime, timezone

from scanner.trending import (Extractor, build_rows, count_mentions, load_brands, merge_day,
                               saturated_estimates, source_stat, stocktwits_rate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALID = {"CELH", "DECK", "ONON", "AI", "ALL", "IT", "PLTR", "GME", "CROX", "ELF"}
BRANDS = {"hoka": "DECK", "celsius energy": "CELH", "on running": "ONON", "e.l.f.": "ELF", "crocs": "CROX"}


def ex(valid=VALID):
    return Extractor(BRANDS, ["stanley tumbler", "owala"], valid)


class Extraction(unittest.TestCase):
    def test_cashtags_need_a_real_ticker(self):
        self.assertEqual(ex().tickers("loading up on $CELH and $FAKE", allow_bare=False), {"CELH"})

    def test_cashtag_beats_stopword(self):
        self.assertEqual(ex().tickers("$AI to the moon", allow_bare=True), {"AI"})

    def test_bare_tickers_only_where_allowed_and_not_stopwords(self):
        text = "PLTR is IT for ALL of us, AI hype"
        self.assertEqual(ex().tickers(text, allow_bare=True), {"PLTR"})
        self.assertEqual(ex().tickers(text, allow_bare=False), set())

    def test_all_caps_rant_is_not_a_ticker_list(self):
        self.assertEqual(ex().tickers("PLTR GME WHY IS THIS HAPPENING", allow_bare=True), set())

    def test_brands_whole_word_case_insensitive_plural(self):
        e = ex()
        self.assertEqual(e.tickers("My HOKAS finally wore out", allow_bare=False), {"DECK"})
        self.assertEqual(e.tickers("got some e.l.f. primer", allow_bare=False), {"ELF"})
        self.assertEqual(e.tickers("Shokan is not a brand", allow_bare=False), set())  # no partial-word hit
        self.assertEqual(e.tickers("it's 30 celsius outside", allow_bare=False), set())  # needs "celsius energy"

    def test_private_brands_tracked_separately(self):
        e = ex()
        self.assertEqual(e.tickers("my owala leaked", allow_bare=False), set())
        self.assertEqual(e.private_brands("my Owala leaked"), {"owala"})

    def test_without_sec_list_only_known_brand_tickers_count(self):
        e = ex(valid=None)
        self.assertEqual(e.tickers("$CROX and $PLTR", allow_bare=False), {"CROX"})

    def test_shipped_brands_file_loads(self):
        brands, private = load_brands(os.path.join(ROOT, "brands.json"))
        self.assertEqual(brands["hoka"], "DECK")
        self.assertIn("owala", private)
        self.assertTrue(all(k == k.lower() for k in brands))


def item(i, text, sub="stocks", author=None):
    return {"id": str(i), "sub": sub, "author": author or f"u{i}", "text": text, "url": f"https://x/{i}"}


class Counting(unittest.TestCase):
    def test_counts_items_and_distinct_authors(self):
        items = [item(1, "$CELH $CELH $CELH"), item(2, "celsius energy rocks", sub="energydrinks"),
                 item(3, "$CELH again", author="u1"), item(3, "duplicate id ignored $CELH")]
        out = count_mentions(items, ex(), {"stocks"})
        self.assertEqual(out["items"], 3)
        self.assertEqual(out["counts"]["CELH"], 3)      # once per item
        self.assertEqual(out["authors"]["CELH"], 2)     # u1 twice
        self.assertEqual(out["subs"]["CELH"], ["energydrinks", "stocks"])
        self.assertLessEqual(len(out["samples"]["CELH"]), 2)

    def test_merge_sum_vs_max(self):
        h = {}
        merge_day(h, "d", {"items": 100, "counts": {"A": 2}, "authors": {"A": 2}})
        merge_day(h, "d", {"items": 50, "counts": {"A": 1, "B": 4}, "authors": {"A": 1, "B": 3}})
        self.assertEqual((h["d"]["items"], h["d"]["counts"]), (150, {"A": 3, "B": 4}))
        m = {}
        merge_day(m, "d", {"counts": {"A": 20}, "authors": {"A": 9}}, mode="max", queried=["A", "B"])
        merge_day(m, "d", {"counts": {"A": 12}, "authors": {"A": 11}}, mode="max", queried=["C"])
        self.assertEqual((m["d"]["counts"]["A"], m["d"]["authors"]["A"]), (20, 11))
        self.assertEqual(m["d"]["queried"], ["A", "B", "C"])


class BlueskySaturation(unittest.TestCase):
    def test_full_page_is_scaled_to_a_day_using_verified_hits_only(self):
        items = [{"query": "hoka", "text": "new hoka drop"} for _ in range(60)] + \
                [{"query": "hoka", "text": "unrelated fuzzy match"} for _ in range(40)]
        est = saturated_estimates(items, {"hoka": 6.0}, {"hoka": "DECK"}, ex())
        self.assertEqual(est, {"DECK": 240.0})  # 60 real hits in 6h

    def test_page_covering_whole_day_is_not_scaled(self):
        self.assertEqual(saturated_estimates([], {"hoka": 30.0}, {"hoka": "DECK"}, ex()), {})


class StockTwitsRate(unittest.TestCase):
    NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    def msgs(self, hours_ago, users=None):
        return [{"created_at": f"2026-10-{12 - (12 + h) // 24 if h >= 12 else 12:02d}T{(12 - h) % 24:02d}:00:00Z",
                 "user": {"username": (users or {}).get(i, f"u{i}")}} for i, h in enumerate(hours_ago)]

    def test_sample_older_than_a_day_counts_last_24h(self):
        rate, users = stocktwits_rate(self.msgs([1, 2, 5, 30, 40]), self.NOW)
        self.assertEqual((rate, users), (3.0, 3))

    def test_busy_ticker_is_extrapolated(self):
        rate, _ = stocktwits_rate(self.msgs([0, 1, 1, 2, 2, 3]), self.NOW)  # 6 messages in 3 hours
        self.assertEqual(rate, 48.0)

    def test_empty(self):
        self.assertEqual(stocktwits_rate([], self.NOW), (0.0, 0))


def hist(series, today, ticker="CELH", authors=10, queried=None):
    h = {f"2026-10-0{i + 1}": {"items": 1000, "counts": {ticker: c}, "authors": {ticker: authors},
                               "queried": queried or []} for i, c in enumerate(series)}
    h["2026-10-12"] = {"items": 1000, "counts": {ticker: today}, "authors": {ticker: authors}, "queried": []}
    return h


class Ranking(unittest.TestCase):
    P = {"min_mentions": 5, "min_authors": 3, "min_zscore": 2.0, "min_history_days": 5}
    BASE = [2, 3, 2, 4, 3, 2, 3]

    def test_spike_is_rising(self):
        s = source_stat(hist(self.BASE, 30), "2026-10-12", "CELH", self.P, normalize=False)
        self.assertEqual(s["status"], "rising")
        self.assertGreater(s["zscore"], 2)
        self.assertEqual(s["vs_baseline"], round(30 / (19 / 7), 1))

    def test_normal_day_is_steady(self):
        self.assertEqual(source_stat(hist([8, 9, 10, 9, 11, 10, 9], 10), "2026-10-12", "CELH", self.P, False)["status"],
                         "steady")

    def test_normalized_source_accounts_for_sample_size(self):
        h = hist(self.BASE, 30)
        h["2026-10-12"]["items"] = 10000  # 10x more items scanned -> 3 per 1000, not a spike
        self.assertEqual(source_stat(h, "2026-10-12", "CELH", self.P, normalize=True)["status"], "steady")

    def test_minimums_filter_noise(self):
        s = source_stat(hist(self.BASE, 30, authors=2), "2026-10-12", "CELH", self.P, False)
        self.assertEqual(s["status"], "below minimum")

    def test_new_history_is_building_baseline(self):
        s = source_stat(hist([], 9), "2026-10-12", "CELH", self.P, False)
        self.assertEqual(s["status"], "building baseline")
        self.assertIsNone(s["zscore"])

    def test_days_ticker_was_not_checked_are_not_zero_baseline(self):
        h = hist([2, 3, 2, 4, 3, 2, 3], 3, queried=["OTHER"])  # CELH never looked up before today
        self.assertEqual(source_stat(h, "2026-10-12", "CELH", self.P, False)["status"], "below minimum")
        h = hist([2, 3, 2, 4, 3, 2, 3], 9, queried=["OTHER"])
        self.assertEqual(source_stat(h, "2026-10-12", "CELH", self.P, False)["status"], "building baseline")

    def test_build_rows_best_source_wins_and_sorts(self):
        spike = hist(self.BASE, 30)
        calm = hist([8, 9, 10, 9, 11, 10, 9], 10, ticker="DECK")
        histories = {"bluesky": (spike, False), "stocktwits": (calm, False)}
        rows = build_rows(histories, "2026-10-12", self.P, always=["PLTR"], st_trending={"DECK": 3})
        self.assertEqual([r["ticker"] for r in rows], ["CELH", "DECK", "PLTR"])
        self.assertEqual(rows[0]["status"], "rising")
        self.assertEqual(rows[1]["stocktwits_trending_rank"], 3)
        self.assertEqual(rows[2]["status"], "below minimum")  # watchlist names always shown


if __name__ == "__main__":
    unittest.main()
