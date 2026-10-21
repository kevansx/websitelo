"""Joining the marketing list, with a welcome gift pack (Joey, 21 Oct 2026; Plans: "Getting customers to opt in to
marketing").

* Asked on the website only, never in a transactional email: in the UK and EU a request for consent sent by email is
  marketing itself.
* Two places for now: a panel on the order page (after the gift pack opens) and the sign-up form's box.
* Consent is saved to the CRM (notification.is_allow_marketing_email) and recorded here with where, when and which
  wording, so it stands up if challenged.
* The welcome gift: one "welcome_list" gift pack per customer, ever, granted after a paid order. Opting in from the
  order page grants it at once; ticking the box at sign-up grants it with the first paid order. An account that never
  buys gets nothing.
* Not asked, and no gift, in the UAE, Saudi Arabia (our onboarding plan, until counsel advises) or Denmark (never
  emailed), by account country or by where the visitor is.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

import lo_mail

NOT_ASKED = frozenset({"AE", "SA", "DK"})
WORDING = "2026-10-21 v1"
SOURCES = ("order_page", "signup")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db() -> sqlite3.Connection:
    p = lo_mail._data_dir() / "optin.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS optins (customer_id INTEGER PRIMARY KEY, source TEXT NOT NULL,
                 wording TEXT NOT NULL, opted_in_at TEXT NOT NULL, gift_pack_id TEXT, gift_granted_at TEXT)""")
    return c


def get(customer_id: int) -> dict | None:
    with closing(_db()) as c:
        r = c.execute("SELECT * FROM optins WHERE customer_id=?", (int(customer_id),)).fetchone()
    return dict(r) if r else None


def may_ask(customer: dict | None, geo_country: str | None) -> bool:
    """Whether to show the offer: a signed-in customer without marketing consent, not asked before, and neither their
    account nor where they are now is in the UAE, Saudi Arabia or Denmark."""
    if not customer or customer.get("id") is None:
        return False
    if lo_mail.marketing_allowed(customer):
        return False
    countries = {lo_mail.customer_country(customer), str(geo_country or "").strip().upper()}
    if countries & NOT_ASKED:
        return False
    try:
        return get(int(customer["id"])) is None
    except (TypeError, ValueError):
        return False


def record(customer_id: int, source: str, now: datetime | None = None) -> None:
    assert source in SOURCES
    with closing(_db()) as c:
        c.execute("INSERT OR IGNORE INTO optins (customer_id, source, wording, opted_in_at) VALUES (?,?,?,?)",
                  (int(customer_id), source, WORDING, (now or _now()).isoformat()))
        c.commit()


def grant_gift(customer_id: int, country: str | None = None, now: datetime | None = None) -> dict | None:
    """The welcome gift pack, once. Only for someone who opted in, and never for AE, SA or DK."""
    if str(country or "").upper() in NOT_ASKED:
        return None
    row = get(customer_id)
    if not row:
        return None
    import lo_packs
    pack = lo_packs.grant_pack(customer_id=int(customer_id), kind="welcome_list", key=f"optin-{int(customer_id)}")
    if not row.get("gift_granted_at"):
        with closing(_db()) as c:
            c.execute("UPDATE optins SET gift_pack_id=?, gift_granted_at=? WHERE customer_id=?",
                      (pack["pack_id"], (now or _now()).isoformat(), int(customer_id)))
            c.commit()
    return pack


def on_order(customer: dict) -> dict | None:
    """A paid order: someone who opted in at sign-up gets their welcome gift now."""
    try:
        cid = int((customer or {}).get("id"))
    except (TypeError, ValueError):
        return None
    row = get(cid)
    if not row or row.get("gift_granted_at"):
        return None
    return grant_gift(cid, lo_mail.customer_country(customer))


def register(app) -> None:
    import secrets as _secrets

    from flask import abort, flash, g, redirect, request, session

    def _customer() -> dict:
        return session.get("customer") if isinstance(session.get("customer"), dict) else {}

    def save_consent(token: str | None, customer: dict) -> bool:
        """Marketing email on, in the CRM, the way the account preferences page saves it."""
        try:
            app.config["LO_ENGINE"]["get_crm"]().customer_update(token, {"notification": {
                "is_allow_email": True, "is_allow_marketing_email": True,
                "is_allow_sms": True, "is_allow_marketing_sms": False, "is_allow_phone_call": False,
            }})
        except Exception as e:  # noqa: BLE001
            app.logger.warning("join list: consent not saved to the CRM: %s", type(e).__name__)
            return False
        session["customer"] = {**customer, "notification": {**(customer.get("notification") or {}),
                                                            "is_allow_marketing_email": True}}
        lo_mail.remember_contact(session["customer"])
        return True

    app.config["LO_OPTIN_SAVE_CONSENT"] = save_consent

    @app.context_processor
    def _optin_ctx():
        if request.endpoint != "order_detail":
            return {"lo_optin_offer": False, "lo_optin_pack": None}
        return {"lo_optin_offer": may_ask(_customer(), getattr(g, "geo_country", None)),
                "lo_optin_pack": session.pop("lo_optin_pack", None)}

    @app.post("/account/join-list")
    def join_list():
        sent = (request.form.get("csrf_token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        if not (sent and want and _secrets.compare_digest(sent, want)):
            abort(400)
        customer = _customer()
        back = request.form.get("back") or "/account"
        if not back.startswith("/") or back.startswith("//"):
            back = "/account"
        if not customer or not session.get("crm_token"):
            return redirect("/login?next=" + back)
        if not may_ask(customer, getattr(g, "geo_country", None)):
            return redirect(back)
        if not save_consent(session.get("crm_token"), customer):
            flash("We couldn't save that just now. Please try again.", "error")
            return redirect(back)
        record(int(customer["id"]), "order_page")
        pack = grant_gift(int(customer["id"]), lo_mail.customer_country(customer))
        flash("You're on the list. Your welcome gift pack is in your account." if pack else "You're on the list.",
              "success")
        if pack:
            session["lo_optin_pack"] = pack["pack_id"]
        return redirect(back)
