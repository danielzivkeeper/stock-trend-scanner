"""Signal 6: Classic bullish chart patterns - CONFIRMED breakouts only.

EVIDENCE: MIXED - weighted low (1.0), like the social signal.
  - Lo, Mamaysky & Wang (2000, "Foundations of Technical Analysis") detected
    patterns by computer and found they carry SOME incremental information,
    but the effect is modest. Many later studies find little or no profit
    after trading costs. Most "this pattern works 70% of the time" numbers
    come from trading books, not peer-reviewed research.
  - The best-supported piece here is the 52-week-high breakout: stocks at or
    near their yearly high tend to keep outperforming (George & Hwang 2004).
  - A pattern means little until it is CONFIRMED by a breakout. "Forming"
    shapes are reported as information only and never add points.

HOW IT WORKS (all on daily closes, ~1 year):
  1. Find turning points: a peak/trough is the highest/lowest close within
     `pivot_order` days on each side.
  2. Check each pattern's textbook rules against those turning points.
  3. A pattern is CONFIRMED when the close first breaks above its key level
     (neckline / resistance / rim) within the last `confirm_days` days, on
     volume >= `min_volume_ratio` x the 50-day average, and the price is still
     holding above that level (a failed breakout doesn't count).

Patterns: 52-week-high breakout, double bottom, inverse head & shoulders,
ascending triangle, cup & handle, bull flag.

The exact thresholds (3% "equal" lows, 12-35% cup depth, ...) are common
textbook/practitioner values - reasonable, but speculative. All configurable.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple

from scanner.base import SignalResult, unavailable

NAME = "chart_patterns"

LABELS = {
    "52w_high": "52-week high",
    "double_bottom": "Double bottom",
    "inverse_head_shoulders": "Inverse head & shoulders",
    "ascending_triangle": "Ascending triangle",
    "cup_handle": "Cup & handle",
    "bull_flag": "Bull flag",
}


# ------------------------------------------------------------ building blocks (pure)

def pivots(c: List[float], order: int) -> Tuple[List[int], List[int]]:
    """Indices of local peaks and troughs (strict on the left so flat tops count once)."""
    peaks, troughs = [], []
    for i in range(order, len(c) - order):
        left, right = c[i - order:i], c[i + 1:i + order + 1]
        if c[i] > max(left) and c[i] >= max(right):
            peaks.append(i)
        elif c[i] < min(left) and c[i] <= min(right):
            troughs.append(i)
    return peaks, troughs


def first_cross(c: List[float], start: int, level) -> Optional[int]:
    """First index >= start whose close is above level(i); level may be a number or a function."""
    lv = level if callable(level) else (lambda _i: level)
    for i in range(start, len(c)):
        if c[i] > lv(i):
            return i
    return None


def volume_ratio(v: Optional[List[float]], i: int, window: int = 50) -> Optional[float]:
    if not v or i < 10:
        return None
    base = [x for x in v[max(0, i - window):i] if x]
    if not base or not v[i]:
        return None
    return v[i] / statistics.mean(base)


def _confirmed(c: List[float], v: Optional[List[float]], i: Optional[int], level_at, p: Dict[str, Any]) -> Optional[Dict]:
    """Shared confirmation rule: recent breakout, enough volume, still holding."""
    if i is None:
        return None
    n = len(c)
    if i < n - int(p.get("confirm_days", 5)):
        return None  # breakout is too old to act on
    level = level_at(i) if callable(level_at) else level_at
    if c[-1] < level * (1 - float(p.get("failed_breakout_pct", 2.0)) / 100):
        return None  # broke out, then fell back below: failed
    vr = volume_ratio(v, i)
    if vr is not None and vr < float(p.get("min_volume_ratio", 1.2)):
        return None
    return {"breakout_index": i, "level": round(level, 2), "volume_ratio": None if vr is None else round(vr, 2)}


def _forming(c: List[float], level: float, p: Dict[str, Any]) -> Optional[Dict]:
    """Not broken out yet, but within `forming_within_pct` below the trigger level."""
    gap = (level - c[-1]) / level * 100
    if 0 < gap <= float(p.get("forming_within_pct", 5.0)):
        return {"level": round(level, 2), "distance_pct": round(gap, 2)}
    return None


# ------------------------------------------------------------ the patterns (pure)

def find_52w_high(c, v, p):
    n = len(c)
    if n < 200:
        return None, None
    cd = int(p.get("confirm_days", 5))
    for i in range(n - cd, n):
        prior = max(c[max(0, i - 251):i])
        if c[i] > prior:
            return _confirmed(c, v, i, prior, p), None
    return None, _forming(c, max(c[-252:]), dict(p, forming_within_pct=p.get("near_high_pct", 3.0)))


def find_double_bottom(c, v, p, peaks, troughs):
    n = len(c)
    best_forming = None
    for k in range(len(troughs) - 1, 0, -1):
        t2 = troughs[k]
        if t2 < n - 120:
            break
        for t1 in reversed(troughs[:k]):
            gap = t2 - t1
            if gap < 10:
                continue
            if gap > 80:
                break
            lo1, lo2 = c[t1], c[t2]
            if abs(lo1 - lo2) / min(lo1, lo2) > float(p.get("double_bottom_tolerance_pct", 3.0)) / 100:
                continue
            neck = max(c[t1:t2 + 1])
            if neck < min(lo1, lo2) * 1.05:
                continue  # the bounce between the lows is too small to be a pattern
            if max(c[max(0, t1 - 40):t1] or [0]) < lo1 * 1.08:
                continue  # a bottom needs a decline before it
            if min(c[t2:]) < min(lo1, lo2) * 0.97:
                continue  # made a new low afterwards: pattern broken
            hit = _confirmed(c, v, first_cross(c, t2 + 1, neck), neck, p)
            if hit:
                return hit, None
            if first_cross(c, t2 + 1, neck) is None:
                best_forming = best_forming or _forming(c, neck, p)
    return None, best_forming


def find_inverse_head_shoulders(c, v, p, peaks, troughs):
    n = len(c)
    for k in range(len(troughs) - 1, 1, -1):
        a, b, d = troughs[k - 2], troughs[k - 1], troughs[k]
        if d < n - 120 or not (20 <= d - a <= 150):
            continue
        ls, head, rs = c[a], c[b], c[d]
        if not (head < ls * 0.97 and head < rs * 0.97):
            continue  # head must be clearly lower than both shoulders
        if abs(ls - rs) / min(ls, rs) > float(p.get("shoulder_tolerance_pct", 6.0)) / 100:
            continue
        p1 = max(range(a, b + 1), key=lambda i: c[i])
        p2 = max(range(b, d + 1), key=lambda i: c[i])
        slope = (c[p2] - c[p1]) / (p2 - p1) if p2 != p1 else 0.0

        def neck(i, p1=p1, slope=slope):
            return c[p1] + slope * (i - p1)

        if max(c[max(0, a - 40):a] or [0]) < ls * 1.05:
            continue  # needs a prior decline
        if min(c[d:]) < head:
            continue
        cross = first_cross(c, d + 1, neck)
        hit = _confirmed(c, v, cross, neck, p)
        if hit:
            return hit, None
        if cross is None:
            return None, _forming(c, neck(n - 1), p)
    return None, None


def find_ascending_triangle(c, v, p, peaks, troughs):
    n = len(c)
    cd = int(p.get("confirm_days", 5))
    lo_idx = n - 90
    pk = [i for i in peaks if lo_idx <= i < n - 1]
    tr = [i for i in troughs if lo_idx <= i < n - 1]
    if len(pk) < 2 or len(tr) < 2:
        return None, None
    tol = float(p.get("resistance_tolerance_pct", 2.0)) / 100
    top = max(c[i] for i in pk)
    touches = [i for i in pk if c[i] >= top * (1 - tol)]
    if len(touches) < 2 or touches[-1] - touches[0] < 10:
        return None, None
    base = [i for i in tr if touches[0] <= i <= max(touches[-1], n - cd - 1)]
    if len(base) < 2 or any(c[base[j]] <= c[base[j - 1]] * 1.01 for j in range(1, len(base))):
        return None, None  # lows must be rising
    if c[base[0]] > top * 0.95:
        return None, None  # too flat to be a triangle
    cross = first_cross(c, touches[-1] + 1, top * 1.005)
    hit = _confirmed(c, v, cross, top, p)
    if hit:
        return hit, None
    return None, _forming(c, top, p) if cross is None else None


def find_cup_handle(c, v, p, peaks, troughs):
    n = len(c)
    lo_d, hi_d = float(p.get("cup_min_depth_pct", 12)) / 100, float(p.get("cup_max_depth_pct", 35)) / 100
    for j in range(len(peaks) - 1, 0, -1):
        rim_r = peaks[j]
        if rim_r < n - 40:
            break
        for rim_l in reversed(peaks[:j]):
            width = rim_r - rim_l
            if width < 30:
                continue
            if width > 150:
                break
            L, R = c[rim_l], c[rim_r]
            if abs(L - R) / L > 0.05:
                continue
            seg = c[rim_l:rim_r + 1]
            bottom = min(seg)
            depth = 1 - bottom / L
            if not (lo_d <= depth <= hi_d):
                continue
            b_at = rim_l + seg.index(bottom)
            if not (rim_l + 0.2 * width <= b_at <= rim_l + 0.8 * width):
                continue  # V-shapes and lopsided cups don't count
            if max(c[rim_l + 1:rim_r]) > max(L, R) * 1.02:
                continue
            after = c[rim_r + 1:]
            if len(after) < 5:
                continue
            h_low = min(after)
            h_at = rim_r + 1 + after.index(h_low)
            pull = 1 - h_low / R
            if not (0.03 <= pull <= 0.15) or h_low < bottom + 0.5 * (R - bottom):
                continue  # handle: shallow pullback in the upper half of the cup
            if not (3 <= h_at - rim_r <= 30):
                continue
            cross = first_cross(c, h_at + 1, R)
            hit = _confirmed(c, v, cross, R, p)
            if hit:
                return hit, None
            if cross is None:
                return None, _forming(c, R, p)
    return None, None


def find_bull_flag(c, v, p):
    n = len(c)
    cd = int(p.get("confirm_days", 5))
    min_pole = float(p.get("flag_min_pole_pct", 15)) / 100
    for i in range(n - cd, n):
        for flen in range(5, 21):
            j = i - flen  # top of the pole / start of the flag
            if j < 20:
                break
            if c[j] < max(c[j:i]):
                continue  # pole top must be the flag's high point
            s = min(range(j - 15, j - 2), key=lambda k: c[k])
            gain = c[j] / c[s] - 1
            if gain < min_pole:
                continue
            flag = c[j:i]
            if min(flag) < c[j] - 0.5 * (c[j] - c[s]):
                continue  # retraced more than half the pole
            if c[i] <= max(flag) or any(c[k] > max(flag) for k in range(j + 1, i)):
                continue
            hit = _confirmed(c, v, i, max(flag), p)
            if hit:
                hit["pole_gain_pct"] = round(gain * 100, 1)
                return hit, None
    return None, None


def detect(closes: List[float], volumes: Optional[List[float]], params: Dict[str, Any]) -> Dict[str, Any]:
    """Pure. Returns {"confirmed": {pattern: info}, "forming": {pattern: info}}."""
    order = int(params.get("pivot_order", 4))
    peaks, troughs = pivots(closes, order)
    out: Dict[str, Dict] = {"confirmed": {}, "forming": {}}
    checks = [
        ("52w_high", lambda: find_52w_high(closes, volumes, params)),
        ("double_bottom", lambda: find_double_bottom(closes, volumes, params, peaks, troughs)),
        ("inverse_head_shoulders", lambda: find_inverse_head_shoulders(closes, volumes, params, peaks, troughs)),
        ("ascending_triangle", lambda: find_ascending_triangle(closes, volumes, params, peaks, troughs)),
        ("cup_handle", lambda: find_cup_handle(closes, volumes, params, peaks, troughs)),
        ("bull_flag", lambda: find_bull_flag(closes, volumes, params)),
    ]
    enabled = params.get("patterns")
    for name, fn in checks:
        if enabled and name not in enabled:
            continue
        hit, forming = fn()
        if hit:
            out["confirmed"][name] = hit
        elif forming:
            out["forming"][name] = forming
    return out


def evaluate(bars: List[Dict[str, Any]], params: Dict[str, Any]) -> SignalResult:
    """Pure. bars = [{date, close, volume}] ascending (about a year of daily data)."""
    if len(bars) < 60:
        return unavailable(NAME, "Not enough price history for chart patterns.")
    closes = [float(b["close"]) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    found = detect(closes, vols if any(vols) else None, params)
    conf, form = found["confirmed"], found["forming"]
    for info in conf.values():
        info["breakout_date"] = bars[info.pop("breakout_index")]["date"]
    raw = {"confirmed": conf, "forming": form}

    def fdesc(k, x):
        return f"{LABELS[k]} forming - confirms above ${x['level']:.2f} ({x['distance_pct']:.1f}% away)"

    forming_txt = "; ".join(fdesc(k, x) for k, x in form.items())
    if not conf:
        msg = "No confirmed breakout pattern."
        if forming_txt:
            msg += f" Watching (no points): {forming_txt}."
        return SignalResult(NAME, False, 0.0, msg, raw)

    best_vr = max((x["volume_ratio"] or 0) for x in conf.values())
    strength = min(1.0, 0.5 + 0.25 * (len(conf) - 1) + (0.25 if best_vr >= 2 else 0.0))
    parts = [f"{LABELS[k]} breakout above ${x['level']:.2f} on {x['breakout_date']}" +
             (f" ({x['volume_ratio']:.1f}x avg volume)" if x["volume_ratio"] else "")
             for k, x in conf.items()]
    detail = "; ".join(parts) + "."
    if forming_txt:
        detail += f" Also watching: {forming_txt}."
    return SignalResult(NAME, True, round(strength, 4), detail, raw)


def run(ticker: str, keyword: str, params: Dict[str, Any]) -> SignalResult:
    from scanner import prices

    bars = prices.get(ticker)
    if not bars:
        return unavailable(NAME, "No price history available.")
    return evaluate(bars, params)
