"""Registry of signal modules. Each exposes NAME and run(ticker, keyword, params)."""
from scanner.signals import (congressional_trades, earnings_drift, insider_buying,
                             short_squeeze_setup, social_spike)

SIGNALS = {
    m.NAME: m
    for m in (earnings_drift, insider_buying, short_squeeze_setup, congressional_trades, social_spike)
}

# How well-documented each signal is, shown on the dashboard next to each row.
EVIDENCE = {
    "earnings_drift": "strong",
    "insider_buying": "moderate",
    "short_squeeze_setup": "mixed",
    "congressional_trades": "weak",
    "social_spike": "short-lived",
}
