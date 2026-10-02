"""Customer emails the site sends itself (the CRM does not send these): one sender for memberships, jackpot
alerts and abandoned checkouts.

Sending: SMTP when SMTP_HOST is set (SendGrid: host smtp.sendgrid.net, port 587, user "apikey", password = the
API key), otherwise the message is written to data/outbox so nothing is lost and nothing is sent by accident.
The same pattern and wording as the Live Lottos site (comms.py), in EUR and with LottosOnline's own name.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

SITE_URL = (os.getenv("LO_SITE_URL") or "https://www.lottosonline.com").rstrip("/")
_lock = threading.Lock()


def _data_dir() -> Path:
    import lo_packs
    return lo_packs.db_path().parent


def outbox() -> Path:
    return _data_dir() / "outbox"


def footer() -> str:
    return ("\n\n--\nLottosOnline.com. 18+ only. Set limits and play responsibly: " + SITE_URL + "/account\n"
            "Email preferences: " + SITE_URL + "/account")


def smtp_configured() -> bool:
    return bool((os.getenv("SMTP_HOST") or "").strip())


def send(to: str, subject: str, text: str, kind: str = "email") -> str:
    """Send one plain-text email. Returns "sent" or "outbox"."""
    body = text.rstrip() + footer()
    if smtp_configured() and to:
        try:
            msg = EmailMessage()
            msg["From"] = os.getenv("MAIL_FROM") or "LottosOnline <support@lottosonline.com>"
            msg["To"] = to
            msg["Subject"] = subject
            if os.getenv("MAIL_REPLY_TO"):
                msg["Reply-To"] = os.getenv("MAIL_REPLY_TO")
            msg.set_content(body)
            host, port = os.getenv("SMTP_HOST").strip(), int(os.getenv("SMTP_PORT") or 587)
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                if os.getenv("SMTP_USER"):
                    s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS") or "")
                s.send_message(msg)
            return "sent"
        except Exception as e:  # never lose the message: fall through to the outbox with the reason
            body += f"\n\n[SMTP failed: {e}]"
    box = outbox()
    box.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (box / f"{ts}-{kind}-{uuid.uuid4().hex[:6]}.txt").write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    return "outbox"


# ------------------------------------------------------------------ "send once" ledger
def _ledger_path() -> Path:
    return _data_dir() / "mail_sent.json"


def once(key: str, now: datetime | None = None) -> bool:
    """True the first time a key is seen (the email may be sent), False after. Keys are kept 90 days."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        p = _ledger_path()
        try:
            sent = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            sent = {}
        if key in sent:
            return False
        sent[key] = now.isoformat()
        cutoff = (now - timedelta(days=90)).isoformat()
        sent = {k: v for k, v in sent.items() if v >= cutoff}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sent, indent=1), encoding="utf-8")
        return True


# ------------------------------------------------------------------ helpers
def eur(cents: Any) -> str:
    try:
        n = int(cents or 0)
    except (TypeError, ValueError):
        n = 0
    return f"€{n / 100:.2f}"


def parse_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def when(d: datetime) -> str:
    """'Tuesday 6 October at 18:30 (UTC)': LottosOnline customers are worldwide, so the zone is stated."""
    d = d.astimezone(timezone.utc)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')} at {d.strftime('%H:%M')} (UTC)"


# ------------------------------------------------------------------ who may be emailed
# The scheduled jobs run without a customer session, so the site remembers each logged-in customer's address and
# their marketing-email choice (the CRM customer's notification.is_allow_marketing_email). Jackpot alerts and
# abandoned-checkout reminders are marketing: they go only to customers who allow marketing email.
def _contacts_db():
    import sqlite3
    p = _data_dir() / "contacts.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS contacts (customer_id INTEGER PRIMARY KEY, email TEXT, marketing_email INTEGER NOT NULL,
                 updated_at TEXT NOT NULL)""")
    return c


def marketing_allowed(customer: dict) -> bool:
    n = (customer or {}).get("notification")
    if isinstance(n, dict) and "is_allow_marketing_email" in n:
        return bool(n.get("is_allow_marketing_email"))
    for k in ("is_allow_marketing_email", "marketing_email", "email_marketing"):
        if k in (customer or {}):
            return bool(customer[k])
    return False       # unknown means no


def remember_contact(customer: dict) -> None:
    from contextlib import closing
    try:
        cid = int((customer or {}).get("id"))
    except (TypeError, ValueError):
        return
    email = str((customer or {}).get("email") or "").strip()
    with closing(_contacts_db()) as c:
        c.execute("INSERT OR REPLACE INTO contacts VALUES (?,?,?,?)",
                  (cid, email, int(marketing_allowed(customer)), datetime.now(timezone.utc).isoformat()))
        c.commit()


def contact(customer_id: int) -> dict | None:
    from contextlib import closing
    with closing(_contacts_db()) as c:
        r = c.execute("SELECT * FROM contacts WHERE customer_id=?", (int(customer_id),)).fetchone()
    return dict(r) if r else None


def marketing_contacts() -> list[dict]:
    from contextlib import closing
    with closing(_contacts_db()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM contacts WHERE marketing_email=1 AND email != ''")]
