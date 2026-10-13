"""Offline tests for chart-pattern detection using synthetic price paths with
known shapes (straight-line segments between textbook turning points)."""
import unittest

from scanner.signals import chart_patterns as cp

P = {"pivot_order": 4, "confirm_days": 5, "min_volume_ratio": 1.2}


def path(start, *legs):
    """legs = (days, target) pairs joined by straight lines -> daily closes."""
    out = [float(start)]
    for days, target in legs:
        a = out[-1]
        out += [a + (target - a) * k / days for k in range(1, days + 1)]
    return out


def vols(n, spike_at=None, mult=2.5):
    v = [1_000_000.0] * n
    if spike_at is not None:
        v[spike_at] = 1_000_000.0 * mult
    return v


def run(closes, spike_from_end=1, mult=2.5):
    n = len(closes)
    return cp.detect(closes, vols(n, n - spike_from_end, mult), P)


class Pivots(unittest.TestCase):
    def test_finds_peaks_and_troughs(self):
        c = path(100, (10, 80), (10, 95), (10, 85), (10, 100))
        peaks, troughs = cp.pivots(c, 4)
        self.assertEqual([c[i] for i in troughs], [80, 85])
        self.assertEqual([c[i] for i in peaks], [95])


class Patterns(unittest.TestCase):
    def test_double_bottom_confirmed(self):
        # decline, low ~80, bounce to 92 (neckline), retest ~80.5, rally, break 92 on the last day
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 91), (1, 94))
        found = run(c)
        self.assertIn("double_bottom", found["confirmed"])
        self.assertEqual(found["confirmed"]["double_bottom"]["level"], 92.0)

    def test_double_bottom_forming_only_before_breakout(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 89.5))
        found = run(c)
        self.assertNotIn("double_bottom", found["confirmed"])
        self.assertIn("double_bottom", found["forming"])
        self.assertAlmostEqual(found["forming"]["double_bottom"]["level"], 92.0)

    def test_inverse_head_and_shoulders(self):
        c = path(100, (20, 85), (12, 92), (12, 78), (12, 92), (12, 86), (10, 91), (1, 95))
        self.assertIn("inverse_head_shoulders", run(c)["confirmed"])

    def test_ascending_triangle(self):
        # flat ceiling at 100, rising floor 90 -> 93 -> 96, then break out
        c = path(85, (20, 100), (10, 90), (10, 100), (10, 93), (10, 100), (10, 96), (9, 99.5), (1, 102.5))
        self.assertIn("ascending_triangle", run(c)["confirmed"])

    def test_cup_and_handle(self):
        # rim 100, rounded bottom ~76, right rim 99, handle dips to 94, breakout
        c = path(80, (20, 100), (15, 85), (10, 76), (10, 76.5), (10, 86), (15, 99), (8, 94), (6, 98.5), (1, 101.5))
        self.assertIn("cup_handle", run(c)["confirmed"])

    def test_bull_flag(self):
        # quiet base, +20% pole in 8 days, gentle 10-day drift lower, breakout
        c = path(50, (40, 50.5), (8, 61), (10, 58.5), (1, 62))
        found = run(c)
        self.assertIn("bull_flag", found["confirmed"])
        self.assertGreaterEqual(found["confirmed"]["bull_flag"]["pole_gain_pct"], 15)

    def test_52_week_high_breakout(self):
        c = path(100, (120, 130), (60, 115), (71, 129.5), (1, 131))  # first close above the old 130 high
        self.assertIn("52w_high", run(c)["confirmed"])


class FalsePositives(unittest.TestCase):
    def test_flat_and_downtrend_find_nothing(self):
        self.assertEqual(run([100.0] * 260)["confirmed"], {})
        self.assertEqual(run(path(150, (259, 90)))["confirmed"], {})

    def test_breakout_without_volume_does_not_confirm(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 91), (1, 94))
        self.assertNotIn("double_bottom", run(c, mult=1.0)["confirmed"])

    def test_old_breakout_is_not_reported(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 91), (1, 94), (20, 96))
        self.assertNotIn("double_bottom", run(c, spike_from_end=21)["confirmed"])

    def test_failed_breakout_is_dropped(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 91), (1, 94), (2, 88))
        self.assertNotIn("double_bottom", run(c, spike_from_end=3)["confirmed"])


class Scoring(unittest.TestCase):
    def bars(self, closes, spike_from_end=1, mult=2.5):
        v = vols(len(closes), len(closes) - spike_from_end, mult)
        return [{"date": f"d{i}", "close": c, "volume": v[i]} for i, c in enumerate(closes)]

    def test_confirmed_pattern_fires_with_explanation(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 91), (1, 94))
        r = cp.evaluate(self.bars(c), P)
        self.assertTrue(r.triggered)
        self.assertEqual(r.strength, 0.75)  # one pattern (0.5) + strong volume >= 2x (0.25)
        self.assertIn("Double bottom breakout above $92.00", r.detail)
        self.assertIn("2.5x avg volume", r.detail)

    def test_forming_pattern_scores_zero_but_is_reported(self):
        c = path(100, (30, 80), (15, 92), (15, 80.5), (14, 89.5))
        r = cp.evaluate(self.bars(c), P)
        self.assertFalse(r.triggered)
        self.assertEqual(r.strength, 0.0)
        self.assertIn("Double bottom forming - confirms above $92.00", r.detail)

    def test_too_little_history_is_unavailable(self):
        self.assertEqual(cp.evaluate(self.bars([100.0] * 30), P).status, "unavailable")


if __name__ == "__main__":
    unittest.main()
