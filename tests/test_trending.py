"""Offline tests for Reddit mention extraction and spike ranking."""
import os
import unittest

from scanner.trending import Extractor, count_mentions, load_brands, merge_day, rank

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

    def test_merge_two_runs_same_day(self):
        h = {}
        merge_day(h, "2026-10-12", {"items": 100, "counts": {"A": 2}, "authors": {"A": 2}})
        merge_day(h, "2026-10-12", {"items": 50, "counts": {"A": 1, "B": 4}, "authors": {"A": 1, "B": 3}})
        self.assertEqual(h["2026-10-12"], {"items": 150, "counts": {"A": 3, "B": 4}, "authors": {"A": 3, "B": 3}})


class Ranking(unittest.TestCase):
    P = {"min_mentions": 5, "min_authors": 3, "min_zscore": 2.0, "min_history_days": 5}

    def history(self, today_counts):
        h = {f"2026-10-0{d}": {"items": 1000, "counts": {"CELH": c, "DECK": 10}, "authors": {}}
             for d, c in zip(range(1, 8), [2, 3, 2, 4, 3, 2, 3])}
        h["2026-10-12"] = {"items": 1000, "counts": today_counts,
                           "authors": {t: 10 for t in today_counts}}
        return h

    def test_spike_is_rising_steady_is_steady(self):
        rows = {r["ticker"]: r for r in rank(self.history({"CELH": 30, "DECK": 10}), "2026-10-12", self.P)}
        self.assertEqual(rows["CELH"]["status"], "rising")
        self.assertGreater(rows["CELH"]["zscore"], 2)
        self.assertEqual(rows["CELH"]["vs_baseline"], round(30 / (19 / 7), 1))
        self.assertEqual(rows["DECK"]["status"], "steady")
        self.assertEqual(list(rows)[0], "CELH")  # rising sorts first

    def test_normalizes_by_items_scanned(self):
        h = self.history({"CELH": 30})
        h["2026-10-12"]["items"] = 10000  # 10x more items -> 3 per 1000, not a spike
        rows = rank(h, "2026-10-12", self.P)
        self.assertEqual(rows[0]["status"], "steady")

    def test_minimums_filter_noise(self):
        h = self.history({"CELH": 30, "PLTR": 4})
        h["2026-10-12"]["authors"]["CELH"] = 2  # one or two people spamming
        self.assertEqual(rank(h, "2026-10-12", self.P), [])

    def test_new_history_is_building_baseline(self):
        h = {"2026-10-12": {"items": 500, "counts": {"CELH": 9}, "authors": {"CELH": 5}}}
        rows = rank(h, "2026-10-12", self.P)
        self.assertEqual(rows[0]["status"], "building baseline")
        self.assertIsNone(rows[0]["zscore"])


if __name__ == "__main__":
    unittest.main()
