"""Customer emails the site sends itself (the CRM does not send these): one sender for memberships, jackpot
alerts, abandoned checkouts and withdrawals. The designs live in lo_emails.py (send_template).

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


def send(to: str, subject: str, text: str, kind: str = "email", html: str | None = None, plain_footer: bool = True) -> str:
    """Send one email: plain text, plus an HTML part when given. Returns "sent" or "outbox"."""
    body = text.rstrip() + (footer() if plain_footer else "")
    if smtp_configured() and to:
        try:
            msg = EmailMessage()
            msg["From"] = os.getenv("MAIL_FROM") or "LottosOnline <support@lottosonline.com>"
            msg["To"] = to
            msg["Subject"] = subject
            if os.getenv("MAIL_REPLY_TO"):
                msg["Reply-To"] = os.getenv("MAIL_REPLY_TO")
            msg.set_content(body)
            if html:
                msg.add_alternative(html, subtype="html")
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
    name = f"{ts}-{kind}-{uuid.uuid4().hex[:6]}"
    (box / f"{name}.txt").write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    if html:
        (box / f"{name}.html").write_text(html, encoding="utf-8")
    return "outbox"


# Joey's standing rule: never email customers in Denmark, on any brand or kind of send. Enforced here, in the one
# function every customer email goes through, rather than trusted to each caller. Whether Danish customers get
# service emails (order confirmation, password reset) is still his decision; until he says so, they get none.
BLOCKED_COUNTRIES = frozenset({"DK"})


def customer_country(customer: dict | None) -> str:
    """The ISO-2 country on a CRM customer record, or "" when it carries none."""
    customer = customer or {}
    address = customer.get("address") if isinstance(customer.get("address"), dict) else {}
    for candidate in (customer.get("country"), address.get("country_iso2"), address.get("country")):
        iso = str(candidate or "").strip().upper()
        if len(iso) == 2 and iso.isalpha():
            return iso
    return ""


def blocked(to: str, country: str | None = None) -> bool:
    """True when this address must not be emailed: the country given, or the one remembered for the address."""
    iso = (country or "").strip().upper()
    if not iso and to:
        iso = str((contact_by_email(to) or {}).get("country") or "").upper()
    return iso in BLOCKED_COUNTRIES


def send_template(to: str, key: str, data: dict, *, text: str | None = None, kind: str | None = None,
                  country: str | None = None) -> str:
    """Send one of the designed emails (lo_emails.py). text: a hand-written plain-text part; without it the plain
    text is made from the HTML (which already carries the footer). country: the customer's, when the caller has the
    record; otherwise the one remembered for the address. Returns "sent", "outbox" or "blocked"."""
    if blocked(to, country):
        return "blocked"
    import lo_emails
    subject, page, auto_text = lo_emails.render(key, data, SITE_URL, os.getenv("LO_ASSET_URL") or SITE_URL)
    if text is None:
        return send(to, subject, auto_text, kind=kind or key, html=page, plain_footer=False)
    return send(to, subject, text, kind=kind or key, html=page)


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
    # added 19 Oct 2026 for the Denmark rule; older databases gain the column in place
    if "country" not in {r[1] for r in c.execute("PRAGMA table_info(contacts)")}:
        c.execute("ALTER TABLE contacts ADD COLUMN country TEXT")
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
        c.execute("INSERT OR REPLACE INTO contacts (customer_id, email, marketing_email, updated_at, country) VALUES (?,?,?,?,?)",
                  (cid, email, int(marketing_allowed(customer)), datetime.now(timezone.utc).isoformat(),
                   customer_country(customer) or None))
        c.commit()


def contact(customer_id: int) -> dict | None:
    from contextlib import closing
    with closing(_contacts_db()) as c:
        r = c.execute("SELECT * FROM contacts WHERE customer_id=?", (int(customer_id),)).fetchone()
    return dict(r) if r else None


def contact_by_email(email: str) -> dict | None:
    from contextlib import closing
    with closing(_contacts_db()) as c:
        r = c.execute("SELECT * FROM contacts WHERE lower(email)=lower(?) ORDER BY updated_at DESC",
                      (str(email or "").strip(),)).fetchone()
    return dict(r) if r else None


def marketing_contacts() -> list[dict]:
    """Customers who allow marketing email, Danish accounts left out."""
    from contextlib import closing
    with closing(_contacts_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM contacts WHERE marketing_email=1 AND email != ''")]
    return [r for r in rows if str(r.get("country") or "").upper() not in BLOCKED_COUNTRIES]
