"""Offline tests for the S&P 500 big-drop finder and the daily summary text."""
import unittest

from scanner.market import SMS_LIMIT, compose_summary, find_drops, pack_texts


def series(*closes, last="2026-10-12"):
    days = ["2026-10-08", "2026-10-09", last][-len(closes):]
    return list(zip(days, closes))


class Drops(unittest.TestCase):
    def test_finds_drops_at_or_beyond_threshold_worst_first(self):
        closes = {"AAA": series(100, 89.0),     # -11%
                  "BBB": series(50, 45.0),      # -10% exactly -> included
                  "CCC": series(20, 18.2),      # -9%
                  "DDD": series(10, 7.0),       # -30%
                  "UPP": series(10, 12.0)}
        day, drops = find_drops(closes, 10, {"AAA": "Alpha"})
        self.assertEqual(day, "2026-10-12")
        self.assertEqual([d["ticker"] for d in drops], ["DDD", "AAA", "BBB"])
        self.assertEqual(drops[1]["name"], "Alpha")
        self.assertAlmostEqual(drops[1]["pct"], -11.0)

    def test_stale_ticker_cannot_report_old_move_as_today(self):
        closes = {"AAA": series(100, 101.0), "HALT": series(100, 50.0, last="2026-10-09")}
        _, drops = find_drops(closes, 10)
        self.assertEqual(drops, [])

    def test_empty(self):
        self.assertEqual(find_drops({}, 10), (None, []))


class Packing(unittest.TestCase):
    def test_packs_lines_into_sms_sized_texts(self):
        texts = pack_texts(["a" * 100, "b" * 50, "c" * 100])
        self.assertEqual(len(texts), 2)
        self.assertTrue(all(len(t) <= SMS_LIMIT for t in texts))
        self.assertEqual(texts[0], "a" * 100 + "\n" + "b" * 50)

    def test_caps_number_of_texts(self):
        texts = pack_texts(["x" * 150] * 6, max_texts=3)
        self.assertEqual(len(texts), 3)
        self.assertTrue(texts[-1].endswith("(more: app)"))
        self.assertTrue(all(len(t) <= SMS_LIMIT for t in texts))


class Summary(unittest.TestCase):
    TICKERS = [{"ticker": "HIMS", "score": 1.2}, {"ticker": "CELH", "score": 6.0}, {"ticker": "PTON", "score": 0.9},
               {"ticker": "ELF", "score": 0.0}]

    def text(self, **kw):
        args = dict(day="2026-10-12", market_date="2026-10-12", drops=[], threshold_pct=10,
                    tickers=self.TICKERS, alert_threshold=5.0, rising=[], dashboard_url="")
        args.update(kw)
        return "\n".join(compose_summary(**args))

    def test_drops_first_then_alerts_scores_trending(self):
        drops = [{"ticker": "XYZ", "pct": -14.25}, {"ticker": "ABC", "pct": -10.0}]
        t = self.text(drops=drops, rising=["DECK"])
        lines = t.split("\n")
        self.assertEqual(lines[0], "Daily scan 10/12")
        self.assertEqual(lines[1], "S&P500 down 10%+: XYZ -14.2%, ABC -10.0%")
        self.assertIn("ALERTS: CELH 6.0", t)
        self.assertIn("Top scores: CELH 6.0, HIMS 1.2, PTON 0.9", t)
        self.assertIn("Trending up: DECK", t)

    def test_quiet_day(self):
        t = self.text()
        self.assertIn("No S&P500 stock fell 10%+ today.", t)
        self.assertNotIn("ALERTS", self.text(tickers=self.TICKERS[:1]))

    def test_link_only_added_when_it_fits(self):
        short = compose_summary("2026-10-12", "2026-10-12", [], 10, [], 5.0, [], "https://x.io/s/")
        self.assertEqual(len(short), 1)
        self.assertTrue(short[0].endswith("https://x.io/s/"))
        long_url = "https://" + "y" * 140
        self.assertEqual(len(compose_summary("2026-10-12", "2026-10-12", [], 10, [], 5.0, [], long_url)), 1)

    def test_holiday_says_market_closed(self):
        self.assertIn("Market closed today (last prices 2026-10-09)", self.text(market_date="2026-10-09"))

    def test_many_drops_are_trimmed(self):
        drops = [{"ticker": f"T{i}", "pct": -11.0} for i in range(12)]
        self.assertIn("+4 more", self.text(drops=drops))

    def test_every_text_fits_in_one_sms(self):
        drops = [{"ticker": f"LONG{i}", "pct": -12.34} for i in range(8)]
        parts = compose_summary("2026-10-12", "2026-10-12", drops, 10, self.TICKERS, 5.0, ["DECK", "ONON"],
                                "https://danielzivkeeper.github.io/stock-trend-scanner/")
        self.assertTrue(all(len(p) <= SMS_LIMIT for p in parts))
        self.assertLessEqual(len(parts), 3)


if __name__ == "__main__":
    unittest.main()
