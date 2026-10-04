"""Text-message alerts via a carrier email-to-SMS gateway (free), plus an
optional ntfy.sh push notification as a backup.

Every setting comes from environment variables (GitHub Actions secrets). If
any are missing we log and carry on - a missing secret never crashes the scan.

Reliability warning: carriers treat email-to-SMS as a legacy feature. AT&T shut
its gateway down in 2025, and Verizon/T-Mobile may delay or silently drop
messages. That's why the optional NTFY_TOPIC backup exists.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List

SMS_LIMIT = 160  # one SMS segment; gateways truncate or split anything longer


def build_sms(alerts: List[Dict[str, Any]], dashboard_url: str = "") -> str:
    """One compact text covering every alerting ticker, highest score first."""
    if not alerts:
        return ""
    parts = []
    for a in sorted(alerts, key=lambda a: -a["score"]):
        fired = "+".join(_short(s["name"]) for s in a["signals"] if s["triggered"])
        parts.append(f"{a['ticker']} {a['score']:.1f} ({fired})")
    msg = "Scanner: " + "; ".join(parts)
    if dashboard_url and len(msg) + len(dashboard_url) + 1 <= SMS_LIMIT:
        msg += " " + dashboard_url
    if len(msg) > SMS_LIMIT:
        msg = msg[:SMS_LIMIT - 1] + "…"
    return msg


def _short(name: str) -> str:
    return {"earnings_drift": "EPS", "insider_buying": "insiders", "short_squeeze_setup": "short",
            "congressional_trades": "congress", "social_spike": "social"}.get(name, name)


def send_sms(text: str) -> bool:
    sender = os.environ.get("SMTP_EMAIL", "").strip()
    password = os.environ.get("SMTP_APP_PASSWORD", "").replace(" ", "").strip()
    phone = "".join(ch for ch in os.environ.get("ALERT_PHONE", "") if ch.isdigit())
    gateway = os.environ.get("ALERT_CARRIER_GATEWAY", "").strip().lstrip("@")
    missing = [n for n, v in (("SMTP_EMAIL", sender), ("SMTP_APP_PASSWORD", password),
                              ("ALERT_PHONE", phone), ("ALERT_CARRIER_GATEWAY", gateway)) if not v]
    if missing:
        print(f"[alerts] SMS skipped - missing secrets: {', '.join(missing)}")
        return False
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = f"{phone}@{gateway}"
    msg["Subject"] = ""  # subjects show up as clutter on most phones
    msg.set_content(text)
    try:
        with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), 465, timeout=30) as s:
            s.login(sender, password)
            s.send_message(msg)
        print(f"[alerts] SMS sent to ***{phone[-4:]}@{gateway}")
        return True
    except Exception as e:  # noqa: BLE001 - log, never crash the scan
        print(f"[alerts] SMS failed: {type(e).__name__}: {e}")
        return False


def send_ntfy(text: str) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    try:
        import requests

        requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                      headers={"Title": "Stock scanner alert"}, timeout=20).raise_for_status()
        print("[alerts] ntfy push sent")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] ntfy failed: {type(e).__name__}: {e}")
        return False


def notify(alerts: List[Dict[str, Any]], dashboard_url: str = "") -> bool:
    text = build_sms(alerts, dashboard_url)
    if not text:
        return False
    print(f"[alerts] message: {text}")
    sms_ok = send_sms(text)
    push_ok = send_ntfy(text)
    return sms_ok or push_ok


def should_alert(ticker: str, score: float, today_iso: str, state: Dict[str, Any],
                 cooldown_days: int, rearm_delta: float = 1.0) -> bool:
    """Don't re-text the same ticker twice a day for a week. Re-alert after the
    cooldown, or sooner if the score jumped by `rearm_delta` or more."""
    from datetime import date

    prev = state.get(ticker)
    if not prev:
        return True
    days = (date.fromisoformat(today_iso) - date.fromisoformat(prev["date"])).days
    return days >= cooldown_days or score >= prev["score"] + rearm_delta
