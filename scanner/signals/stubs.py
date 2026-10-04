"""Ideas that are NOT implemented, on purpose. They never return fake data.

They're listed so the dashboard can show them as "not implemented" and nobody
mistakes their absence for a "no".
"""
from __future__ import annotations

from typing import Any, Dict

from scanner.base import NOT_IMPLEMENTED, SignalResult

STUBS = {
    # X/Twitter removed free API read access in 2023; reading a CEO's posts now
    # needs a paid tier (Basic is ~$200/month). Scraping X violates its ToS.
    "ceo_social_activity": "Not implemented: reading X/Twitter now requires a paid API tier "
                           "(free read access ended in 2023), and scraping violates X's ToS.",
    # Apple and Google publish no free historical ranking API. Commercial
    # services (Sensor Tower, data.ai) are paid. Apple's RSS top-charts feed
    # gives only a current snapshot, so a "jump" needs our own history - doable
    # later, but app ranks also map poorly onto most tickers.
    "app_store_ranking_jump": "Not implemented: no free app-ranking history API (Sensor Tower / data.ai "
                              "are paid); Apple's RSS feed is a current snapshot only.",
    # LinkedIn/Indeed/Glassdoor job counts have no free API and their ToS
    # forbid scraping. Paid alternatives: Revelio Labs, LinkUp, Thinknum.
    "hiring_surge": "Not implemented: no free job-posting API, and scraping LinkedIn/Indeed/Glassdoor "
                    "violates their Terms of Service.",
}


def run(name: str, ticker: str = "", keyword: str = "", params: Dict[str, Any] = None) -> SignalResult:
    return SignalResult(name=name, triggered=False, strength=0.0, detail=STUBS[name], raw={},
                        status=NOT_IMPLEMENTED)
