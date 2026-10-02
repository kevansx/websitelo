"""Weekly syndicate memberships (build brief 2, part 5). The CRM runs them; the site sells, lists and manages them.

* Three products (CRM reply, 2 Oct 2026): LO-USPOW-W, LO-USMEG-W, LO-EUEUR-W. A share is 10 lines in every draw
  of the week, one of 40 shares, billed weekly at subscription_standard_price_cents (never price_in_base_cents).
* Join: POST /api/v1/checkout with a saved card the CRM can charge each week, as Live Lottos does:
  {"saved_card_id", "use_wins": false, "items": [{"kind": "syndicate", "ticket_mode": "subscription",
  "product_code", "shares": 1}]}. No saved card yet: a deposit with "Save this card" first, then back here.
* Account: /account/memberships lists them with the next charge date and amount; pause (1-12 weeks, default 4,
  active only), resume, cancel (one tap, no phone call); past_due shows an "update your card" action.
* Emails (lo_mail): joined and cancelled when they happen; renewal reminder 24 hours before each charge, receipt,
  and charge failed (at once, then after 2 and 5 days) from `flask membership-emails`, run hourly.
* Offered where people already are: the cart, the order confirmation, jackpot alerts and the account page.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import lo_lotteries
import lo_mail
import lo_store

# game code -> lottery page slug (the share page lives at /syndicates/<slug>)
SHARE_GAMES = {"powerball": "us-powerball", "megamillions": "mega-millions", "euromillions-at": "euromillions"}
LINES_PER_SHARE, SHARES = 10, 40
PAUSE_DEFAULT, PAUSE_MAX = 4, 12


def share_product(games: list[dict], game_code: str) -> dict | None:
    for g in games or []:
        if str(g.get("game_code") or "").lower() == game_code:
            return lo_store.split_products(lo_store.game_products(g))["subscription"]
    return None


def weekly_cents(p: dict | None) -> int | None:
    if not p:
        return None
    v = p.get("subscription_standard_price_cents")
    return int(v) if v not in (None, "") else None


def offers_for(games: list[dict], game_codes) -> list[dict]:
    """The share offer for each of these lotteries that has one: {name, slug, cents, url}."""
    out, seen = [], set()
    for gc in game_codes or []:
        gc = str(gc or "").lower()
        if gc in seen or gc not in SHARE_GAMES:
            continue
        seen.add(gc)
        cents = weekly_cents(share_product(games, gc))
        lot = lo_lotteries.by_game_code(gc)
        if cents and lot:
            out.append({"name": lot.name, "slug": SHARE_GAMES[gc], "cents": cents, "url": f"/syndicates/{SHARE_GAMES[gc]}"})
    return out


# ------------------------------------------------------------------ emails (wording after Live Lottos comms.py)
def mail_joined(to: str, name: str, cents: int, next_at: datetime | None) -> str:
    nxt = f" Your next payment of {lo_mail.eur(cents)} is due on {lo_mail.when(next_at)}." if next_at else ""
    return lo_mail.send(to, f"You're in: {name} syndicate, {lo_mail.eur(cents)} a week",
                        f"Your {name} syndicate membership is confirmed.\n\n"
                        f"Your share is {LINES_PER_SHARE} lines in every {name} draw each week, one of {SHARES} shares. "
                        f"Each share receives 1/{SHARES}th of any prize the syndicate's lines win.\n\n"
                        f"It costs {lo_mail.eur(cents)} a week, taken from your saved card, and renews every week until you cancel.{nxt}\n\n"
                        "To pause for a few weeks or cancel, go to " + lo_mail.SITE_URL + "/account/memberships. "
                        "Cancelling is one tap, free and instant.", kind="member-joined")


def mail_renewal_due(to: str, name: str, cents: int, at: datetime, sub_id: Any) -> str:
    return lo_mail.send(to, f"Your {name} syndicate renews tomorrow: {lo_mail.eur(cents)}",
                        f"Your {name} syndicate membership renews on {lo_mail.when(at)}.\n\n"
                        f"We will take {lo_mail.eur(cents)} from your saved card.\n\n"
                        "Nothing to do if you are happy to carry on: you stay in every draw.\n\n"
                        "To cancel, use this link before then (log in, then one tap): "
                        + lo_mail.SITE_URL + f"/account/memberships?cancel={sub_id}\n"
                        "To pause for a few weeks instead: " + lo_mail.SITE_URL + "/account/memberships",
                        kind="member-renewal-due")


def mail_charged(to: str, name: str, cents: int, next_at: datetime | None) -> str:
    nxt = f"\n\nYour next payment is due on {lo_mail.when(next_at)}." if next_at else ""
    return lo_mail.send(to, f"Payment received: {lo_mail.eur(cents)} for your {name} syndicate",
                        f"We have taken {lo_mail.eur(cents)} for your {name} syndicate membership. You are in this week's "
                        "draws, and your lines will appear in your account before each draw." + nxt,
                        kind="member-charged")


def mail_charge_failed(to: str, name: str, cents: int, reason: str | None) -> str:
    why = f" The bank's message was: {reason}." if reason else ""
    return lo_mail.send(to, f"We could not take your {name} syndicate payment",
                        f"Your weekly payment of {lo_mail.eur(cents)} for your {name} syndicate did not go through.{why}\n\n"
                        "You are not in the draws for this week until a payment succeeds. To carry on, add or update your "
                        "card here: " + lo_mail.SITE_URL + "/wallet/add-funds\n\n"
                        "If you meant to stop, you do not need to do anything: no further payment will be taken without a working card. "
                        "You can also cancel here: " + lo_mail.SITE_URL + "/account/memberships",
                        kind="member-charge-failed")


def mail_cancelled(to: str, name: str) -> str:
    return lo_mail.send(to, f"Your {name} syndicate membership is cancelled",
                        f"Your {name} syndicate membership is cancelled. Nothing more will be taken.\n\n"
                        "Any draws you have already paid for still count, and any winnings go to your account as usual.",
                        kind="member-cancelled")


OK_STATUSES = {"succeeded", "success", "captured", "paid", "completed", "approved"}
FAIL_STATUSES = {"failed", "declined", "error", "rejected"}


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("subscriptions"), list):
        return payload["subscriptions"]
    return payload if isinstance(payload, list) else []


BASE_TO_GAME = {"LO-USPOW": "powerball", "LO-USMEG": "megamillions", "LO-EUEUR": "euromillions-at"}


def _name(s: dict) -> str:
    gc = str((s or {}).get("game_code") or "") or BASE_TO_GAME.get(lo_store.base_code(str((s or {}).get("product_code") or "")), "")
    lot = lo_lotteries.by_game_code(gc)
    return lot.name if lot else str((s or {}).get("product_name") or "syndicate")


def run_emails(client: Any, now: datetime | None = None) -> dict:
    """One pass of the membership emails; safe to run as often as you like (each email is sent once)."""
    now = now or datetime.now(timezone.utc)
    out = {"renewal_due": 0, "charged": 0, "charge_failed": 0, "errors": []}
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        due = _rows(client.subscriptions_due(next_charge_after=iso(now), next_charge_before=iso(now + timedelta(hours=26))))
    except Exception as e:
        due = []
        out["errors"].append(f"due list: {e}")
    for s in due:
        at = lo_mail.parse_utc(s.get("next_charge_at"))
        if str(s.get("status")) != "active" or not s.get("email") or not at or not (now < at <= now + timedelta(hours=26)):
            continue
        if lo_mail.once(f"member-renewal:{s.get('id')}:{at.date().isoformat()}", now):
            mail_renewal_due(s["email"], _name(s), int(s.get("next_amount_cents") or 0), at, s.get("id"))
            out["renewal_due"] += 1
    try:
        recent = _rows(client.subscriptions_due(next_charge_after=iso(now - timedelta(days=8)),
                                                next_charge_before=iso(now + timedelta(days=9))))
    except Exception as e:
        recent = []
        out["errors"].append(f"recent list: {e}")
    for s in recent:
        charge_id, at = s.get("last_charge_id"), lo_mail.parse_utc(s.get("last_charge_at"))
        if not (charge_id and at and s.get("email")):
            continue
        status = str(s.get("last_charge_status") or "").lower()
        if status in OK_STATUSES and now - at <= timedelta(hours=48) and int(s.get("period_number") or 1) > 1:
            if lo_mail.once(f"member-charged:{charge_id}", now):
                mail_charged(s["email"], _name(s), int(s.get("last_charge_amount_cents") or s.get("next_amount_cents") or 0),
                             lo_mail.parse_utc(s.get("next_charge_at")))
                out["charged"] += 1
        elif status in FAIL_STATUSES and str(s.get("status")) in ("past_due", "active"):
            # immediately, then after 2 and 5 days while it is still unpaid
            for day in (0, 2, 5):
                if now - at >= timedelta(days=day) and lo_mail.once(f"member-failed:{charge_id}:{day}", now):
                    mail_charge_failed(s["email"], _name(s), int(s.get("next_amount_cents") or 0), s.get("last_charge_error"))
                    out["charge_failed"] += 1
                    break
    return out


# ------------------------------------------------------------------ web
def register(app) -> None:
    import secrets as _secrets

    from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

    from crm_api import CRMError

    def _cid_token():
        tok = session.get("crm_token")
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        return (c or {}).get("id"), tok, (c or {}).get("email")

    def _csrf_ok() -> bool:
        sent = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and _secrets.compare_digest(sent, want))

    def _games() -> list[dict]:
        try:
            return app.config["LO_ENGINE"]["store_games_cached"]() or []
        except Exception:
            return []

    def _crm():
        return app.config["LO_ENGINE"]["get_crm"]()

    def _lot_for_slug(slug: str):
        for gc, s in SHARE_GAMES.items():
            if s == slug:
                return lo_lotteries.by_game_code(gc), gc
        return None, None

    def _crm_message(e: Exception) -> str:
        p = getattr(e, "payload", None)
        if isinstance(p, dict):
            for k in ("message", "error", "detail"):
                if isinstance(p.get(k), str) and p[k]:
                    return p[k]
        return "We couldn't do that just now. Please try again."

    app.jinja_env.globals["lo_share_offers"] = lambda codes: offers_for(_games(), codes)

    @app.get("/syndicates")
    def syndicates_index():
        offers = offers_for(_games(), list(SHARE_GAMES))
        return render_template("lo/syndicates.html", offers=offers)

    @app.get("/syndicates/<slug>")
    def syndicate_page(slug: str):
        lot, gc = _lot_for_slug(slug)
        if lot is None:
            abort(404)
        product = share_product(_games(), gc)
        cents = weekly_cents(product)
        cid, tok, _ = _cid_token()
        cards, wallet_cents = [], None
        if tok and product:
            try:
                cards = [c for c in ((_crm().wallet_cards(tok) or {}).get("cards") or []) if str(c.get("status") or "active") == "active"]
            except Exception:
                cards = []
        jp = app.jinja_env.globals["lo_jackpot"](gc)
        return render_template("lo/syndicate.html", lot=lot, game_code=gc, product=product, cents=cents, cards=cards,
                               logged_in=bool(tok), jp=jp, lines=LINES_PER_SHARE, shares=SHARES)

    @app.post("/syndicates/<slug>/join")
    def syndicate_join(slug: str):
        if not _csrf_ok():
            abort(400)
        lot, gc = _lot_for_slug(slug)
        if lot is None:
            abort(404)
        cid, tok, email = _cid_token()
        if not tok:
            return redirect(url_for("login", next=f"/syndicates/{slug}"))
        product = share_product(_games(), gc)
        cents = weekly_cents(product)
        if not product or not cents:
            flash("This syndicate is not open just now. Please try again later.", "warning")
            return redirect(url_for("syndicate_page", slug=slug))
        if request.form.get("agree") != "1":
            flash(f"Please confirm that {lo_mail.eur(cents)} is taken every week until you cancel.", "warning")
            return redirect(url_for("syndicate_page", slug=slug) + "#join")
        card_id = (request.form.get("saved_card_id") or "").strip()
        if not card_id.isdigit():
            flash("Please choose the card to pay with each week.", "warning")
            return redirect(url_for("syndicate_page", slug=slug) + "#join")
        payload = {"saved_card_id": int(card_id), "use_wins": False,
                   "items": [{"kind": "syndicate", "ticket_mode": "subscription",
                              "product_code": lo_store.product_code(product), "shares": 1}]}
        try:
            placed = _crm().checkout(tok, payload) or {}
        except CRMError as e:
            app.logger.warning("membership join refused for customer %s: %s", cid, e)
            msg = _crm_message(e)
            if "insufficient" in msg.lower() or "funds" in msg.lower() or getattr(e, "status_code", None) == 402:
                flash(f"Your first week ({lo_mail.eur(cents)}) is paid from your wallet. Please add funds, then join.", "warning")
                return redirect(url_for("wallet_add_funds", next=f"/syndicates/{slug}"))
            flash(msg, "error")
            return redirect(url_for("syndicate_page", slug=slug) + "#join")
        except Exception:
            flash("We couldn't do that just now. Please try again.", "error")
            return redirect(url_for("syndicate_page", slug=slug) + "#join")
        sub = placed.get("subscription") if isinstance(placed.get("subscription"), dict) else {}
        if email:
            mail_joined(email, lot.name, cents, lo_mail.parse_utc(sub.get("next_charge_at")))
        return redirect(url_for("account_memberships", joined=sub.get("id") or 1))

    @app.get("/account/memberships")
    def account_memberships():
        cid, tok, _ = _cid_token()
        if not tok:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        try:
            rows = _rows(_crm().subscriptions(tok))
        except Exception:
            rows = None
        subs = []
        for s in rows or []:
            subs.append({**s, "name": _name(s), "next_at": lo_mail.parse_utc(s.get("next_charge_at")),
                         "paused_until_at": lo_mail.parse_utc(s.get("paused_until"))})
        offers = offers_for(_games(), [g for g in SHARE_GAMES if g not in {str(s.get("game_code")) for s in subs if s.get("status") != "cancelled"}])
        return render_template("lo/memberships.html", subs=subs, failed=rows is None, offers=offers,
                               confirm_cancel=request.args.get("cancel"), pause_max=PAUSE_MAX, pause_default=PAUSE_DEFAULT,
                               noindex="noindex, nofollow")

    @app.post("/account/memberships/<sub_id>/<action>")
    def account_membership_action(sub_id: str, action: str):
        if not _csrf_ok():
            abort(400)
        cid, tok, email = _cid_token()
        if not tok:
            return redirect(url_for("login", next="/account/memberships"))
        if action not in ("pause", "resume", "cancel"):
            abort(404)
        crm = _crm()
        try:
            if action == "pause":
                weeks = int(request.form.get("weeks") or PAUSE_DEFAULT)
                if not 1 <= weeks <= PAUSE_MAX:
                    raise ValueError
                crm.subscription_pause(tok, sub_id, weeks)
                flash(f"Paused for {weeks} week{'s' if weeks != 1 else ''}. Nothing is taken while it is paused.", "success")
            elif action == "resume":
                crm.subscription_resume(tok, sub_id)
                flash("Resumed. You are back in every draw from the next charge.", "success")
            else:
                res = crm.subscription_cancel(tok, sub_id, {}) or {}
                name = _name(res.get("subscription") if isinstance(res.get("subscription"), dict) else {})
                if email:
                    mail_cancelled(email, name)
                flash("Cancelled. Nothing more will be taken.", "success")
        except ValueError:
            flash("Please choose between 1 and 12 weeks.", "warning")
        except CRMError as e:
            flash(_crm_message(e), "error")
        except Exception:
            flash("We couldn't do that just now. Please try again.", "error")
        return redirect(url_for("account_memberships"))

    @app.cli.command("membership-emails")
    def membership_emails_cmd():
        """Hourly: renewal reminders (24h before), receipts and failed-payment emails for memberships."""
        print(run_emails(_crm()))
