"""Composite 0-10 score with a line-by-line explanation. Pure - no network.

    score = sum(weight_i * strength_i for triggered signals) / sum(all weights) * 10

The denominator is ALWAYS the total of all configured weights, even when a
signal couldn't be checked (data source down). That's deliberately
conservative: missing data can only lower a score, never inflate it. If a
source is permanently gone, set its weight to 0 in config.json.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from scanner.base import NOT_IMPLEMENTED, OK, SignalResult


def load_config(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    validate_config(cfg)
    return cfg


def validate_config(cfg: Dict[str, Any]) -> None:
    weights = cfg.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ValueError("config.json needs a non-empty 'weights' object")
    for k, w in weights.items():
        if not isinstance(w, (int, float)) or w < 0:
            raise ValueError(f"weight for {k!r} must be a number >= 0 (got {w!r})")
    if sum(weights.values()) <= 0:
        raise ValueError("at least one weight must be greater than 0")
    t = cfg.get("alert_threshold")
    if not isinstance(t, (int, float)) or not 0 <= t <= 10:
        raise ValueError("'alert_threshold' must be a number from 0 to 10")
    h = cfg.get("hold_days")
    if not isinstance(h, int) or h < 1:
        raise ValueError("'hold_days' must be a whole number >= 1")


def score_ticker(results: Dict[str, SignalResult], weights: Dict[str, float],
                 threshold: float) -> Dict[str, Any]:
    total_weight = float(sum(weights.values()))
    rows: List[Dict[str, Any]] = []
    points = 0.0
    for name, weight in weights.items():
        r = results.get(name) or SignalResult(name=name, detail="Signal did not run.", status="error")
        pts = weight * r.strength if (r.triggered and r.status == OK) else 0.0
        points += pts
        rows.append({
            "name": name,
            "weight": weight,
            "triggered": bool(r.triggered and r.status == OK),
            "strength": round(r.strength, 4) if r.triggered else 0.0,
            "points": round(pts, 4),
            "score_contribution": round(pts / total_weight * 10, 2),
            "status": r.status,
            "detail": r.detail,
            "raw": r.raw,
        })
    score = round(points / total_weight * 10, 2)
    alert = score >= threshold
    return {
        "score": score,
        "alert": alert,
        "points": round(points, 4),
        "total_weight": total_weight,
        "signals": rows,
        "summary": summarize(score, threshold, rows),
        "explanation": explain(score, threshold, total_weight, rows),
    }


def summarize(score: float, threshold: float, rows: List[Dict[str, Any]]) -> str:
    fired = [r["name"] for r in rows if r["triggered"]]
    checked = [r for r in rows if r["status"] == OK]
    head = f"{score:.1f}/10"
    if fired:
        head += f" - {len(fired)} of {len(rows)} signals fired ({', '.join(fired)})"
    else:
        head += f" - no signals fired ({len(checked)} of {len(rows)} could be checked)"
    head += "; ALERT (>= " if score >= threshold else "; below alert threshold ("
    return head + f"{threshold:g})."


def explain(score: float, threshold: float, total_weight: float, rows: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for r in rows:
        if r["triggered"]:
            lines.append(f"FIRED {r['name']}: strength {r['strength']:.2f} x weight {r['weight']:g} = "
                         f"{r['points']:.2f} pts (+{r['score_contribution']:.2f} to score). {r['detail']}")
        elif r["status"] == OK:
            lines.append(f"no    {r['name']}: {r['detail']}")
        elif r["status"] == NOT_IMPLEMENTED:
            lines.append(f"n/a   {r['name']}: {r['detail']}")
        else:
            lines.append(f"???   {r['name']} ({r['status']}, counts as 0): {r['detail']}")
    pts = sum(r["points"] for r in rows)
    lines.append(f"Math: {pts:.2f} pts / {total_weight:g} possible x 10 = {score:.2f}. "
                 f"Alert threshold {threshold:g}.")
    return lines
