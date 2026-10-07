"""Withdraw winnings (build brief 2, part 6). The CRM has no customer payout call, so the site raises a request.

* /account/withdraw shows the winnings balance; the customer enters an amount (up to their winnings) and how they
  want to be paid. The request is emailed to support (LO_SUPPORT_EMAIL, default support@lottosonline.com: the
  mailbox the help desk turns into a ticket) with the customer id, amount and payout details, and kept in
  data/withdrawals.sqlite. It does NOT move money.
* Support pays the customer, then an agent with wallet-adjust permission debits the Winnings bucket on the
  customer's wallet page in the CRM, with a reason.
* The customer sees "Request received - we'll pay it within N working days" (LO_WITHDRAWAL_DAYS).
* Switched off until the business decides how support pays and the promised turnaround: LO_WITHDRAWALS_ON=1 and
  LO_WITHDRAWAL_DAYS set. Off, the page shows the balance and how to contact support.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import lo_mail

MIN_CENTS = 1000
METHODS = {"bank": "Bank transfer", "other": "Another way (tell us below)"}


def enabled() -> bool:
    return os.environ.get("LO_WITHDRAWALS_ON", "0").strip() == "1" and bool(turnaround_days())


def turnaround_days() -> int | None:
    try:
        n = int(os.environ.get("LO_WITHDRAWAL_DAYS", "").strip())
        return n if n > 0 else None
    except ValueError:
        return None


def support_email() -> str:
    return (os.environ.get("LO_SUPPORT_EMAIL") or "support@lottosonline.com").strip()


def _db() -> sqlite3.Connection:
    p = lo_mail._data_dir() / "withdrawals.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
                 email TEXT, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, method TEXT NOT NULL, details TEXT,
                 created_at TEXT NOT NULL)""")
    return c


def winnings_cents(wallet: dict | None) -> int:
    w = wallet or {}
    for k in ("winnings_cents", "winnings_balance_cents", "withdrawable_cents"):
        if w.get(k) is not None:
            try:
                return max(0, int(w[k]))
            except (TypeError, ValueError):
                pass
    return 0


def register(app) -> None:
    import secrets as _secrets

    from flask import abort, flash, redirect, render_template, request, session, url_for

    def _csrf_ok() -> bool:
        sent = (request.form.get("csrf_token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and _secrets.compare_digest(sent, want))

    def _wallet(tok: str) -> dict:
        try:
            return (app.config["LO_ENGINE"]["get_crm"]().wallet(tok) or {}).get("wallet") or {}
        except Exception:
            return {}

    @app.route("/account/withdraw", methods=["GET", "POST"])
    def account_withdraw():
        tok = session.get("crm_token")
        cust = session.get("customer") if isinstance(session.get("customer"), dict) else None
        if not tok or not cust:
            return redirect(url_for("login", next="/account/withdraw"))
        wallet = _wallet(tok)
        available = winnings_cents(wallet)
        currency = str(wallet.get("currency") or "EUR")
        sent = None
        if request.method == "POST":
            if not _csrf_ok():
                abort(400)
            if not enabled():
                abort(404)
            try:
                amount = int(round(float((request.form.get("amount") or "").replace(",", ".")) * 100))
            except ValueError:
                amount = 0
            method = request.form.get("method") or ""
            details = (request.form.get("details") or "").strip()[:2000]
            error = None
            if amount < MIN_CENTS:
                error = f"The smallest withdrawal is {lo_mail.eur(MIN_CENTS)}."
            elif amount > available:
                error = f"You can withdraw up to {lo_mail.eur(available)}, your winnings balance."
            elif method not in METHODS or not details:
                error = "Please tell us how you'd like to be paid."
            if error:
                flash(error, "warning")
                return redirect(url_for("account_withdraw"))
            with closing(_db()) as c:
                cur = c.execute("INSERT INTO requests (customer_id, email, amount_cents, currency, method, details, created_at) VALUES (?,?,?,?,?,?,?)",
                                (int(cust["id"]), cust.get("email"), amount, currency, method, details, datetime.now(timezone.utc).isoformat()))
                c.commit()
                req_id = cur.lastrowid
            lo_mail.send_template(support_email(), "withdrawal_request_staff",
                         {"reference": f"W{req_id}", "customer_id": cust["id"], "customer_email": cust.get("email"),
                          "customer_name": f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip(),
                          "amount": lo_mail.eur(amount), "balance": lo_mail.eur(available), "method": METHODS[method],
                          "details": details},
                         text=f"A customer has asked to withdraw winnings. Nothing has been paid or debited yet.\n\n"
                         f"Request: W{req_id}\nCustomer id: {cust['id']}\nEmail: {cust.get('email')}\n"
                         f"Name: {cust.get('first_name', '')} {cust.get('last_name', '')}\n"
                         f"Amount: {lo_mail.eur(amount)} ({currency})\nWinnings balance at request: {lo_mail.eur(available)}\n"
                         f"Pay by: {METHODS[method]}\nDetails:\n{details}\n\n"
                         "When paid: debit the Winnings bucket on the customer's wallet page in the CRM, with a reason "
                         f"quoting W{req_id}.", kind="withdrawal-request")
            if cust.get("email"):
                lo_mail.send_template(cust["email"], "withdrawal_received",
                             {"first_name": cust.get("first_name"), "amount": lo_mail.eur(amount), "reference": f"W{req_id}",
                              "method": METHODS[method], "days": turnaround_days()},
                             text=f"Request received: {lo_mail.eur(amount)} from your winnings (reference W{req_id}).\n\n"
                             f"We'll pay it within {turnaround_days()} working days. We'll contact you if we need anything else.",
                             kind="withdrawal-received")
            sent = {"id": req_id, "amount": amount}
        return render_template("lo/withdraw.html", available=available, currency=currency, on=enabled(),
                               days=turnaround_days(), methods=METHODS, sent=sent, min_cents=MIN_CENTS,
                               support=support_email(), noindex="noindex, nofollow")
