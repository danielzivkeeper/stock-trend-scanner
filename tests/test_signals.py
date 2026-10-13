"""Offline tests for each signal's rule logic (the pure `evaluate` functions)
and the alert/backtest helpers. Synthetic data only, no network."""
import unittest
from datetime import date

from scanner import alerts
from scanner.backtest import forward_test, pick_signals
from scanner.base import NOT_IMPLEMENTED, UNAVAILABLE, scaled_strength
from scanner.signals import congressional_trades as ct
from scanner.signals import earnings_drift as ed
from scanner.signals import insider_buying as ib
from scanner.signals import short_squeeze_setup as ss
from scanner.signals import social_spike as sp
from scanner.signals import stubs

TODAY = date(2026, 10, 1)


class Strength(unittest.TestCase):
    def test_scaling_convention(self):
        self.assertEqual(scaled_strength(4.9, 5, 3), 0.0)
        self.assertAlmostEqual(scaled_strength(5, 5, 3), 1 / 3, places=3)
        self.assertAlmostEqual(scaled_strength(10, 5, 3), 2 / 3, places=3)
        self.assertEqual(scaled_strength(15, 5, 3), 1.0)
        self.assertEqual(scaled_strength(500, 5, 3), 1.0)


class EarningsDrift(unittest.TestCase):
    P = {"min_surprise_pct": 5.0, "full_strength_multiple": 3.0, "max_days_since_report": 30}

    def test_fires_on_10pct_beat(self):
        r = ed.evaluate([{"date": date(2026, 9, 20), "estimate": 1.00, "reported": 1.10, "surprise": None}],
                        self.P, TODAY)
        self.assertTrue(r.triggered)
        self.assertAlmostEqual(r.raw["surprise_pct"], 10.0)
        self.assertAlmostEqual(r.strength, 10 / 15, places=3)

    def test_ignores_future_unreported_date(self):
        rows = [{"date": date(2026, 9, 20), "estimate": 1.0, "reported": 1.2, "surprise": None},
                {"date": date(2026, 11, 5), "estimate": 1.3, "reported": float("nan"), "surprise": None}]
        r = ed.evaluate(rows, self.P, TODAY)
        self.assertEqual(r.raw["report_date"], "2026-09-20")
        self.assertTrue(r.triggered)

    def test_small_beat_and_miss_do_not_fire(self):
        for rep in (1.04, 0.80):
            r = ed.evaluate([{"date": date(2026, 9, 20), "estimate": 1.0, "reported": rep, "surprise": None}],
                            self.P, TODAY)
            self.assertFalse(r.triggered)

    def test_negative_estimate_uses_abs_denominator(self):
        # loss narrowed from -0.20 expected to -0.10 = +50% surprise
        r = ed.evaluate([{"date": date(2026, 9, 20), "estimate": -0.20, "reported": -0.10, "surprise": None}],
                        self.P, TODAY)
        self.assertAlmostEqual(r.raw["surprise_pct"], 50.0)
        self.assertEqual(r.strength, 1.0)

    def test_stale_report_does_not_fire(self):
        r = ed.evaluate([{"date": date(2026, 7, 1), "estimate": 1.0, "reported": 2.0, "surprise": None}],
                        self.P, TODAY)
        self.assertFalse(r.triggered)
        self.assertIn("older than", r.detail)

    def test_no_data_is_unavailable(self):
        self.assertEqual(ed.evaluate([], self.P, TODAY).status, UNAVAILABLE)

    def test_falls_back_to_yahoo_surprise_when_estimate_missing(self):
        r = ed.evaluate([{"date": date(2026, 9, 20), "estimate": None, "reported": 1.0, "surprise": 12.0}],
                        self.P, TODAY)
        self.assertTrue(r.triggered)


class InsiderBuying(unittest.TestCase):
    P = {"min_distinct_insiders": 2, "full_strength_multiple": 2.0, "lookback_days": 14,
         "min_value_per_insider_usd": 10000}

    def row(self, who, value="+$50,000", ticker="ABC", kind="P - Purchase"):
        return {"Ticker": ticker, "Insider Name": who, "Trade Type": kind, "Value": value, "Title": "Dir"}

    def test_two_distinct_buyers_fire(self):
        r = ib.evaluate([self.row("A"), self.row("B")], "ABC", self.P)
        self.assertTrue(r.triggered)
        self.assertEqual(r.strength, 0.5)
        self.assertEqual(r.raw["total_value_usd"], 100000)

    def test_same_insider_twice_counts_once(self):
        self.assertFalse(ib.evaluate([self.row("A"), self.row("A")], "ABC", self.P).triggered)

    def test_token_buys_are_ignored(self):
        r = ib.evaluate([self.row("A"), self.row("B", "+$900")], "ABC", self.P)
        self.assertFalse(r.triggered)
        self.assertEqual(r.raw["ignored_small_buyers"], ["B"])

    def test_small_buys_add_up_per_insider(self):
        rows = [self.row("A"), self.row("B", "+$6,000"), self.row("B", "+$6,000")]
        self.assertTrue(ib.evaluate(rows, "ABC", self.P).triggered)

    def test_sales_and_other_tickers_ignored(self):
        rows = [self.row("A"), self.row("B", kind="S - Sale"), self.row("C", ticker="XYZ")]
        self.assertFalse(ib.evaluate(rows, "ABC", self.P).triggered)

    def test_four_buyers_is_full_strength(self):
        r = ib.evaluate([self.row(x) for x in "ABCD"], "ABC", self.P)
        self.assertEqual(r.strength, 1.0)


FORM4 = """<?xml version="1.0"?><ownershipDocument>
<issuer><issuerTradingSymbol>abc</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle>
</reportingOwnerRelationship></reportingOwner>
<aff10b5One>{plan}</aff10b5One>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-09-28</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares>
<transactionPricePerShare><value>25.5</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>99</value></transactionShares>
<transactionPricePerShare><value>30</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""


class SecForm4(unittest.TestCase):
    def test_parses_open_market_purchase_only(self):
        rows = ib.parse_form4(FORM4.format(plan=0))
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["Ticker"], r["Insider Name"], r["Title"]), ("ABC", "Doe Jane", "CEO"))
        self.assertAlmostEqual(r["Value"], 25500.0)
        self.assertFalse(r["plan_10b5_1"])

    def test_10b5_1_plan_purchases_do_not_count(self):
        rows = ib.parse_form4(FORM4.format(plan=1)) + [
            {"Ticker": "ABC", "Insider Name": "B", "Trade Type": "P - Purchase", "Value": 50000}]
        r = ib.evaluate(rows, "ABC", {"min_distinct_insiders": 2})
        self.assertFalse(r.triggered)
        self.assertEqual(r.raw["ignored_10b5_1_plan_purchases"], 1)

    def test_two_sec_buyers_fire(self):
        rows = ib.parse_form4(FORM4.format(plan=0)) + ib.parse_form4(
            FORM4.format(plan=0).replace("Doe Jane", "Roe Rick"))
        self.assertTrue(ib.evaluate(rows, "ABC", {"min_distinct_insiders": 2}).triggered)


class ShortSqueeze(unittest.TestCase):
    P = {"min_short_pct_float": 15.0, "min_days_to_cover": 5.0, "full_strength_multiple": 3.0}

    def test_short_pct_alone_fires(self):
        r = ss.evaluate({"shortPercentOfFloat": 0.30, "shortRatio": 2.0}, self.P)
        self.assertTrue(r.triggered)
        self.assertAlmostEqual(r.strength, 30 / 45, places=3)

    def test_days_to_cover_alone_fires(self):
        r = ss.evaluate({"shortPercentOfFloat": 0.05, "shortRatio": 7.5}, self.P)
        self.assertTrue(r.triggered)
        self.assertAlmostEqual(r.strength, 7.5 / 15, places=3)

    def test_takes_the_stronger_component(self):
        r = ss.evaluate({"shortPercentOfFloat": 0.45, "shortRatio": 5.0}, self.P)
        self.assertEqual(r.strength, 1.0)

    def test_below_both_does_not_fire(self):
        self.assertFalse(ss.evaluate({"shortPercentOfFloat": 0.12, "shortRatio": 3.6}, self.P).triggered)

    def test_missing_is_unavailable(self):
        self.assertEqual(ss.evaluate({}, self.P).status, UNAVAILABLE)


class Congress(unittest.TestCase):
    P = {"lookback_days": 45, "min_distinct_members": 2, "full_strength_multiple": 2.0}

    def test_house_and_senate_formats_merge_and_fire(self):
        house = [{"representative": "Rep. A", "ticker": "abc", "type": "purchase",
                  "transaction_date": "2026-08-20", "disclosure_date": "09/15/2026"}]
        senate = [{"senator": "Sen. B", "ticker": "ABC", "type": "Purchase",
                   "transaction_date": "09/01/2026"}]
        trades = ct.normalize(house, senate)
        r = ct.evaluate(trades, "ABC", self.P, TODAY)
        self.assertTrue(r.triggered)
        self.assertEqual(r.raw["members"], ["Rep. A", "Sen. B"])

    def test_old_sales_and_duplicates_ignored(self):
        house = [{"representative": "Rep. A", "ticker": "ABC", "type": "purchase", "disclosure_date": "09/15/2026"},
                 {"representative": "Rep. A", "ticker": "ABC", "type": "purchase", "disclosure_date": "09/20/2026"},
                 {"representative": "Rep. C", "ticker": "ABC", "type": "sale_full", "disclosure_date": "09/20/2026"},
                 {"representative": "Rep. D", "ticker": "ABC", "type": "purchase", "disclosure_date": "06/01/2026"}]
        r = ct.evaluate(ct.normalize(house, []), "ABC", self.P, TODAY)
        self.assertFalse(r.triggered)
        self.assertEqual(r.raw["distinct_members"], 1)


class Social(unittest.TestCase):
    P = {"min_zscore": 2.0, "full_strength_multiple": 2.0}

    def test_zscore(self):
        base = [10, 12, 8, 10, 10, 12, 8, 10]  # mean 10, pstdev sqrt(2)
        z = sp.zscore_latest(base + [20], baseline_window=8)
        self.assertAlmostEqual(z, 10 / 2 ** 0.5, places=4)

    def test_zscore_needs_history_and_handles_flat(self):
        self.assertIsNone(sp.zscore_latest([1, 2], 8))
        self.assertEqual(sp.zscore_latest([5, 5, 5, 5], 3), 0.0)
        self.assertEqual(sp.zscore_latest([5, 5, 5, 9], 3), 10.0)

    def test_evaluate_uses_best_source(self):
        r = sp.evaluate({"google_trends": 1.0, "reddit": 3.0}, self.P, {})
        self.assertTrue(r.triggered)
        self.assertAlmostEqual(r.strength, 0.75)

    def test_no_sources_is_unavailable(self):
        r = sp.evaluate({"google_trends": None}, self.P, {"google_trends": "429", "reddit": "not set"})
        self.assertEqual(r.status, UNAVAILABLE)


class Stubs(unittest.TestCase):
    def test_stubs_never_fake_data(self):
        for name in stubs.STUBS:
            r = stubs.run(name)
            self.assertEqual(r.status, NOT_IMPLEMENTED)
            self.assertFalse(r.triggered)
            self.assertEqual(r.strength, 0.0)


class Alerts(unittest.TestCase):
    def alert(self, t, score):
        return {"ticker": t, "score": score,
                "signals": [{"name": "earnings_drift", "triggered": True},
                            {"name": "insider_buying", "triggered": True},
                            {"name": "social_spike", "triggered": False}]}

    def test_sms_text_is_short_and_sorted(self):
        msg = alerts.build_sms([self.alert("AAA", 5.5), self.alert("BBB", 7.25)], "https://x.github.io/s/")
        self.assertTrue(msg.startswith("Scanner: BBB 7.2"))
        self.assertIn("EPS+insiders", msg)
        self.assertLessEqual(len(msg), alerts.SMS_LIMIT)

    def test_sms_truncates(self):
        msg = alerts.build_sms([self.alert(f"T{i}", 6.0) for i in range(20)])
        self.assertEqual(len(msg), alerts.SMS_LIMIT)

    def test_missing_secrets_do_not_crash(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("SMTP_EMAIL", "SMTP_APP_PASSWORD", "ALERT_PHONE",
                                                       "ALERT_CARRIER_GATEWAY", "NTFY_TOPIC")}
        try:
            self.assertFalse(alerts.notify([self.alert("AAA", 6.0)]))
        finally:
            os.environ.update({k: v for k, v in saved.items() if v is not None})

    def test_cooldown(self):
        state = {"AAA": {"date": "2026-10-01", "score": 6.0}}
        self.assertTrue(alerts.should_alert("BBB", 6.0, "2026-10-01", state, 3))
        self.assertFalse(alerts.should_alert("AAA", 6.2, "2026-10-02", state, 3))
        self.assertTrue(alerts.should_alert("AAA", 7.0, "2026-10-02", state, 3))  # jumped >= 1 point
        self.assertTrue(alerts.should_alert("AAA", 6.0, "2026-10-04", state, 3))


class Backtest(unittest.TestCase):
    def series(self, start_px, step, days):
        out, d, px = [], date(2026, 9, 1), start_px
        import datetime as dt
        while len(out) < days:
            if d.weekday() < 5:
                out.append((d.isoformat(), px))
                px += step
            d += dt.timedelta(days=1)
        return out

    def test_forward_return_entry_next_day_exit_after_hold(self):
        prices = {"AAA": self.series(100.0, 1.0, 30)}
        spy = self.series(500.0, 0.0, 30)
        hist = [{"date": "2026-09-01", "ticker": "AAA", "score": 6.0, "alert": True}]
        out = forward_test(hist, prices, spy, hold_days=10, min_score=5.0)
        t = out["trades"][0]
        self.assertEqual(t["entry_date"], "2026-09-02")  # next trading day, not same day
        self.assertEqual(t["entry"], 101.0)
        self.assertEqual(t["exit"], 111.0)
        self.assertAlmostEqual(t["return"], 10 / 101, places=4)
        self.assertEqual(t["spy_return"], 0.0)
        self.assertEqual(out["summary"]["win_rate"], 1.0)

    def test_repeat_alerts_inside_hold_window_count_once_and_pending(self):
        prices = {"AAA": self.series(100.0, -1.0, 11)}  # entry day + 9 more: not done yet
        hist = [{"date": "2026-09-01", "ticker": "AAA", "score": 6.0},
                {"date": "2026-09-02", "ticker": "AAA", "score": 6.5},
                {"date": "2026-09-03", "ticker": "AAA", "score": 4.0}]  # below min_score
        out = forward_test(hist, prices, [], hold_days=10, min_score=5.0)
        self.assertEqual(len(out["trades"]), 1)
        self.assertEqual(out["trades"][0]["status"], "pending")
        self.assertIsNone(out["summary"]["avg_return"])

    def test_pick_signals_keeps_max_per_day(self):
        hist = [{"date": "2026-09-01", "ticker": "AAA", "score": 4.0},
                {"date": "2026-09-01", "ticker": "AAA", "score": 6.0}]
        self.assertEqual([h["score"] for h in pick_signals(hist, 5.0)], [6.0])


if __name__ == "__main__":
    unittest.main()
