"""Shared types and helpers for every signal module.

Every signal returns a SignalResult with the four fields the project spec asks
for (triggered, strength, detail, raw) plus a `status` so the dashboard can tell
"checked and didn't fire" apart from "couldn't check at all".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

# status values
OK = "ok"                    # data fetched, rule evaluated (may or may not have fired)
UNAVAILABLE = "unavailable"  # data source down / missing credentials / no data for ticker
ERROR = "error"              # unexpected exception while running the signal
NOT_IMPLEMENTED = "not_implemented"


@dataclass
class SignalResult:
    name: str
    triggered: bool = False
    strength: float = 0.0          # 0.0 - 1.0, only meaningful when triggered
    detail: str = ""               # plain-English reason, shown to the user
    raw: Dict[str, Any] = field(default_factory=dict)  # small debugging payload
    status: str = OK

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def scaled_strength(value: float, threshold: float, full_multiple: float) -> float:
    """Strength convention used by every signal.

    0.0 below the threshold; otherwise value / (threshold * full_multiple),
    capped at 1.0. With full_multiple=3, hitting the bare threshold gives 0.33
    and reaching 3x the threshold gives full strength 1.0.
    """
    if threshold <= 0 or value < threshold:
        return 0.0
    return round(clamp01(value / (threshold * full_multiple)), 4)


def unavailable(name: str, why: str, raw: Optional[Dict[str, Any]] = None) -> SignalResult:
    return SignalResult(name=name, detail=why, raw=raw or {}, status=UNAVAILABLE)
