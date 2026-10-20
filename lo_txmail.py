"""The emails the site sends the moment something happens: welcome, order confirmation, funds added.

These replace the old site's welcome2, order_confirmation2 (and its no-password and repeat variants) and
deposit_confirmation2 (see the replication list, Plans, 7 and 19 Oct 2026). The designs are in lo_emails.py; this
module only turns what the site knows at that moment into the data each design needs.

* Every send goes through lo_mail.send_template, which skips Danish accounts and, until the SMTP settings are on the
  server, writes the email to data/outbox instead of sending it.
* Each one is sent once: the "send once" ledger is keyed on the account, order or payment.
* Nothing here may stop a sign-up, an order or a payment: every public function catches its own errors and returns
  "failed" instead of raising.
* Results and winnings emails are not here. The site cannot see a customer's tickets without that customer signed
  in, so those two need the CRM (send them itself, or let the site read tickets by draw).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import lo_lotteries
import lo_mail
import lo_store

_log = logging.getLogger(__name__)

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def money(cents: Any, currency: str | None = "EUR") -> str:
    try:
        n = int(cents or 0)
    except (TypeError, ValueError):
        n = 0
    cur = (currency or "EUR").upper()
    sym = SYMBOLS.get(cur)
    return f"{sym}{n / 100:.2f}" if sym else f"{cur} {n / 100:.2f}"


def day(d: datetime | None = None) -> str:
    """'Wed 7 Oct 2026', the way every date in the designs is written."""
    d = (d or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}"


def first_name(customer: dict | None) -> str | None:
    return str((customer or {}).get("first_name") or "").strip() or None


def _nums(v: Any) -> list[int]:
    if isinstance(v, (list, tuple)):
        raw = list(v)
    else:
        raw = str(v or "").replace(" ", ",").split(",")
    out = []
    for x in raw:
        try:
            out.append(int(str(x).strip()))
        except (TypeError, ValueError):
            continue
    return out


def line_balls(line: dict) -> list[dict]:
    """A cart line as the designs' balls: the main group first, every other group as bonus balls."""
    if not isinstance(line, dict):
        return []
    main_key = "main" if "main" in line else next(iter(line), None)
    balls = [{"n": n} for n in _nums(line.get(main_key))] if main_key else []
    for k, v in line.items():
        if k != main_key and not str(k).startswith("_"):
            balls += [{"n": n, "bonus": True} for n in _nums(v)]
    return balls


def _lottery_name(item: dict) -> str:
    if item.get("game_name"):
        return str(item["game_name"])
    lot = lo_lotteries.by_game_code(str(item.get("game_code") or ""))
    return lot.name if lot else "Lottery"


def _draws_text(item: dict, first_draw: str | None) -> str:
    span = lo_store.tier_span({"product_code": str(item.get("product_code") or "")})
    when = f" from {first_draw}" if first_draw else ""
    if span.get("weeks"):
        n = span["weeks"]
        return f"{n} week{'s' if n != 1 else ''} of draws{when}"
    if span.get("draws"):
        return f"{span['draws']} draws{when}"
    return f"1 draw: {first_draw}" if first_draw else "1 draw"


def order_items(items: list[dict], order: dict | None = None) -> list[dict]:
    """The cart that was bought, as the order confirmation's ticket blocks. Draw dates come from the CRM's order
    when it has them (the earliest ticket per lottery)."""
    first_draw: dict[str, str] = {}
    for t in (order or {}).get("tickets") or []:
        if not isinstance(t, dict) or not t.get("draw_date"):
            continue
        d = lo_mail.parse_utc(t.get("draw_date"))
        code = str(t.get("game_code") or "")
        if d and code and (code not in first_draw or d < lo_mail.parse_utc(first_draw[code])):
            first_draw[code] = d.isoformat()
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        code = str(it.get("game_code") or "")
        fd = lo_mail.parse_utc(first_draw.get(code)) if code in first_draw else None
        block: dict[str, Any] = {
            "lottery_name": _lottery_name(it),
            "draws_text": _draws_text(it, day(fd) if fd else None),
            "lines": [{"balls": line_balls(ln)} for ln in it.get("lines") or [] if isinstance(ln, dict)],
        }
        if it.get("kind") == "syndicate":
            q = int(it.get("quantity") or 1)
            block["note"] = f"Syndicate: {q} share{'s' if q != 1 else ''}."
        elif str(it.get("ticket_mode") or "") == "multi_draw":
            block["note"] = "Multi-draw: the same lines in every draw."
        out.append(block)
    return out


def _site() -> str:
    return lo_mail.SITE_URL


def send_welcome(customer: dict, *, homescreen_offer: bool = False, set_password_url: str | None = None) -> str:
    """Account created (old site: welcome2). Service email: everyone gets it, Danish accounts excepted."""
    try:
        email = str((customer or {}).get("email") or "").strip()
        cid = (customer or {}).get("id")
        if not email or not lo_mail.once(f"welcome-{cid if cid is not None else email.lower()}"):
            return "skipped"
        return lo_mail.send_template(email, "welcome", {
            "first_name": first_name(customer), "email": email, "homescreen_offer": bool(homescreen_offer),
            "set_password_url": set_password_url,
        }, country=lo_mail.customer_country(customer))
    except Exception as e:  # noqa: BLE001 - a welcome email must never cost the customer their account
        _log.warning("welcome email not sent: %s", type(e).__name__)
        return "failed"


def send_welcome_friend(customer: dict, *, referrer_first_name: str | None) -> str:
    """Account created through a friend's link (old site: welcome2referfriend). Sent instead of the welcome."""
    try:
        email = str((customer or {}).get("email") or "").strip()
        cid = (customer or {}).get("id")
        if not email or not lo_mail.once(f"welcome-{cid if cid is not None else email.lower()}"):
            return "skipped"
        return lo_mail.send_template(email, "welcome_friend", {
            "first_name": first_name(customer), "referrer_first_name": referrer_first_name or "Your friend",
            "set_password_url": None,
        }, country=lo_mail.customer_country(customer))
    except Exception as e:  # noqa: BLE001
        _log.warning("welcome (friend) email not sent: %s", type(e).__name__)
        return "failed"


def send_order_confirmation(customer: dict, *, order_id: Any, items: list[dict], order: dict | None = None,
                            total_cents: Any = None, currency: str | None = None, pack: dict | None = None,
                            descriptor: str | None = None, set_password_url: str | None = None,
                            is_renewal: bool = False) -> str:
    """An order is paid (old site: order_confirmation2, order_confirmationreset, repeat_order_confirmation2).
    The customer's proof of purchase, so it is a service email."""
    try:
        email = str((customer or {}).get("email") or "").strip()
        if not email or order_id is None or not lo_mail.once(f"order-{order_id}"):
            return "skipped"
        order = order or {}
        cur = str(order.get("currency") or currency or "EUR").upper()
        cents = order.get("total_cents") if order.get("total_cents") is not None else total_cents
        placed = lo_mail.parse_utc(order.get("placed_at") or order.get("created_at"))
        data: dict[str, Any] = {
            "first_name": first_name(customer),
            "order_ref": str(order.get("reference") or order.get("order_ref") or order_id),
            "order_date": day(placed),
            "total": money(cents, cur) if cents is not None else None,
            "payment_method": None,
            "balance_used": None,
            "descriptor": descriptor,
            "is_renewal": bool(is_renewal),
            "items": order_items(items, order),
            "set_password_url": set_password_url,
            # refer a friend (lo_referral.py): the "share with a friend" panel, for customers who allow marketing
            "referral_url": f"{_site()}/account/refer" if lo_mail.marketing_allowed(customer) else None,
            "pack_url": None,
            "pack_is_gold": False,
        }
        if pack and pack.get("pack_id") and pack.get("state", "sealed") == "sealed":
            data["pack_url"] = f"{_site()}/packs/{pack['pack_id']}"
            data["pack_is_gold"] = pack.get("tier") == "premium"
        return lo_mail.send_template(email, "order_confirmation", data, country=lo_mail.customer_country(customer))
    except Exception as e:  # noqa: BLE001 - the order is placed; the email is a courtesy on top of it
        _log.warning("order confirmation for %s not sent: %s", order_id, type(e).__name__)
        return "failed"


def send_deposit_confirmation(customer: dict, *, reference: Any, amount_cents: Any, currency: str | None = "EUR",
                              balance_cents: Any = None, descriptor: str | None = None) -> str:
    """A top-up to the account balance succeeds (old site: deposit_confirmation2). Not sent when the top-up paid
    for an order there and then: the order confirmation covers that payment, as on the old site."""
    try:
        email = str((customer or {}).get("email") or "").strip()
        if not email or reference in (None, "") or not lo_mail.once(f"deposit-{reference}"):
            return "skipped"
        return lo_mail.send_template(email, "deposit_confirmation", {
            "first_name": first_name(customer), "amount": money(amount_cents, currency),
            "deposit_ref": str(reference), "deposit_date": day(), "payment_method": None,
            "balance": money(balance_cents, currency) if balance_cents is not None else None,
            "descriptor": descriptor, "continue_url": None,
        }, country=lo_mail.customer_country(customer))
    except Exception as e:  # noqa: BLE001
        _log.warning("deposit confirmation for %s not sent: %s", reference, type(e).__name__)
        return "failed"
