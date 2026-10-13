"""Offline tests for the composite score. Synthetic data only, no network.

Run:  python -m unittest discover -s tests -v
"""
import json
import os
import unittest

from scanner.base import ERROR, NOT_IMPLEMENTED, UNAVAILABLE, SignalResult
from scanner.scoring import score_ticker, validate_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = {"earnings_drift": 3.0, "insider_buying": 2.5, "short_squeeze_setup": 2.0,
     "congressional_trades": 1.5, "social_spike": 1.0}


def res(name, triggered=False, strength=0.0, status="ok", detail="d"):
    return SignalResult(name=name, triggered=triggered, strength=strength, detail=detail, status=status)


class ScoreMath(unittest.TestCase):
    def test_nothing_fired_is_zero(self):
        out = score_ticker({n: res(n) for n in W}, W, 5.0)
        self.assertEqual(out["score"], 0.0)
        self.assertFalse(out["alert"])

    def test_everything_full_strength_is_ten(self):
        out = score_ticker({n: res(n, True, 1.0) for n in W}, W, 5.0)
        self.assertEqual(out["score"], 10.0)
        self.assertTrue(out["alert"])

    def test_weighted_sum_formula(self):
        # (3.0*1.0 + 2.5*0.5 + 1.0*0.4) / 10 * 10 = 4.65
        r = {n: res(n) for n in W}
        r["earnings_drift"] = res("earnings_drift", True, 1.0)
        r["insider_buying"] = res("insider_buying", True, 0.5)
        r["social_spike"] = res("social_spike", True, 0.4)
        out = score_ticker(r, W, 5.0)
        self.assertAlmostEqual(out["score"], 4.65)
        self.assertAlmostEqual(out["points"], 4.65)
        self.assertFalse(out["alert"])

    def test_threshold_is_inclusive(self):
        # earnings 3.0 + insider 2.0*... -> exactly 5.0: 3.0*1 + 2.5*0.8 = 5.0
        r = {n: res(n) for n in W}
        r["earnings_drift"] = res("earnings_drift", True, 1.0)
        r["insider_buying"] = res("insider_buying", True, 0.8)
        out = score_ticker(r, W, 5.0)
        self.assertAlmostEqual(out["score"], 5.0)
        self.assertTrue(out["alert"])

    def test_single_signal_cannot_alert_alone_with_default_weights(self):
        # Design property worth knowing: max single-signal score is 3.0 (earnings).
        for n in W:
            r = {m: res(m) for m in W}
            r[n] = res(n, True, 1.0)
            self.assertLess(score_ticker(r, W, 5.0)["score"], 5.0, n)

    def test_unavailable_and_error_count_as_zero_and_keep_denominator(self):
        r = {n: res(n, status=UNAVAILABLE) for n in W}
        r["earnings_drift"] = res("earnings_drift", True, 1.0)
        r["insider_buying"] = res("insider_buying", True, 1.0, status=ERROR)  # bogus: error can't fire
        out = score_ticker(r, W, 5.0)
        self.assertAlmostEqual(out["score"], 3.0)
        self.assertEqual(out["total_weight"], 10.0)

    def test_missing_result_is_treated_as_error_not_crash(self):
        out = score_ticker({}, W, 5.0)
        self.assertEqual(out["score"], 0.0)
        self.assertTrue(all(s["status"] == "error" for s in out["signals"]))

    def test_zero_weight_signal_contributes_nothing(self):
        w = dict(W, congressional_trades=0.0)
        r = {n: res(n, True, 1.0) for n in w}
        out = score_ticker(r, w, 5.0)
        self.assertEqual(out["total_weight"], 8.5)
        self.assertEqual(out["score"], 10.0)

    def test_custom_weights(self):
        w = {"earnings_drift": 1.0, "social_spike": 1.0}
        r = {"earnings_drift": res("earnings_drift", True, 0.5), "social_spike": res("social_spike")}
        self.assertAlmostEqual(score_ticker(r, w, 5.0)["score"], 2.5)

    def test_contributions_add_up_to_score(self):
        r = {n: res(n, True, s) for n, s in zip(W, [0.9, 0.3, 0.7, 0.0, 1.0])}
        out = score_ticker(r, W, 5.0)
        self.assertAlmostEqual(sum(s["score_contribution"] for s in out["signals"]), out["score"], places=1)


class Explanation(unittest.TestCase):
    def test_explanation_names_every_signal_and_shows_math(self):
        r = {n: res(n, detail=f"why-{n}") for n in W}
        r["earnings_drift"] = res("earnings_drift", True, 0.5, detail="EPS beat by +10%")
        r["congressional_trades"] = res("congressional_trades", status=UNAVAILABLE, detail="mirror down")
        r["social_spike"] = res("social_spike", status=NOT_IMPLEMENTED, detail="nope")
        out = score_ticker(r, W, 5.0)
        text = "\n".join(out["explanation"])
        for n in W:
            self.assertIn(n, text)
        self.assertIn("FIRED earnings_drift", text)
        self.assertIn("EPS beat by +10%", text)
        self.assertIn("mirror down", text)
        self.assertIn("1.50 pts / 10 possible x 10 = 1.50", text)
        self.assertIn("earnings_drift", out["summary"])
        self.assertIn("below alert threshold", out["summary"])


class ConfigValidation(unittest.TestCase):
    def test_shipped_config_is_valid_and_matches_spec(self):
        with open(os.path.join(ROOT, "config.json")) as f:
            cfg = json.load(f)
        validate_config(cfg)
        self.assertEqual(cfg["weights"], dict(W, congressional_trades=0))  # source offline
        self.assertEqual(cfg["alert_threshold"], 5.0)
        self.assertEqual(cfg["hold_days"], 10)

    def test_rejects_bad_values(self):
        good = {"weights": {"a": 1}, "alert_threshold": 5, "hold_days": 10}
        validate_config(good)
        for bad in ({"weights": {}},
                    {"weights": {"a": -1}},
                    {"weights": {"a": 0}},
                    {"weights": {"a": "3"}},
                    {"alert_threshold": 11},
                    {"hold_days": 0},
                    {"hold_days": 2.5}):
            with self.assertRaises(ValueError, msg=str(bad)):
                validate_config(dict(good, **bad))


if __name__ == "__main__":
    unittest.main()
