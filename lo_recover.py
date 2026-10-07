"""Abandoned checkout recovery (build brief 2, part 7).

* A logged-in customer who looks at a non-empty cart starts (or refreshes) a recovery record: the cart, the time.
* 30 minutes after they were last on the cart with no purchase: a reminder with the lines they picked, the draw and
  a link back to the cart with those lines in it. Push subscribers get this one by push instead of email.
* 24 hours after, if still nothing: an email with the draw's cut-off time and the current jackpot. If that draw has
  closed it is sent for the next draw (the open one the jackpot feed shows), or not at all. Never for a closed draw.
* Both stop the moment an order completes. One cycle only: never a third message. A new cycle starts only after a
  purchase, or a week after the last one.
* Only customers whose marketing email is on (lo_mail.marketing_allowed). Same sender as every other email.
* `flask abandoned-checkout` runs it, every 10 minutes.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import lo_lotteries
import lo_mail

FIRST_AFTER = timedelta(minutes=30)
SECOND_AFTER = timedelta(hours=24)
NEW_CYCLE_AFTER = timedelta(days=7)


def _db() -> sqlite3.Connection:
    p = lo_mail._data_dir() / "recover.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS carts (customer_id INTEGER PRIMARY KEY, cart_json TEXT NOT NULL,
                 cycle_started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, first_sent_at TEXT, second_sent_at TEXT,
                 completed_at TEXT)""")
    return c


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> datetime | None:
    return lo_mail.parse_utc(s) if s else None


def _snapshot(items: list[dict]) -> list[dict]:
    keep = ("kind", "product_code", "lines", "options", "game_code", "game_name", "ticket_mode", "draw_weeks")
    return [{k: it.get(k) for k in keep if k in it} for it in items or [] if isinstance(it, dict) and it.get("kind", "single") == "single"]


def cart_seen(customer_id: int, items: list[dict], now: datetime | None = None) -> None:
    """The customer is on the cart with these items: start a cycle, or keep the current one up to date."""
    snap = _snapshot(items)
    if not snap:
        return
    now = now or _now()
    with closing(_db()) as c:
        r = c.execute("SELECT * FROM carts WHERE customer_id=?", (customer_id,)).fetchone()
        new_cycle = r is None or r["completed_at"] or (now - (_parse(r["cycle_started_at"]) or now) > NEW_CYCLE_AFTER)
        if new_cycle:
            c.execute("INSERT OR REPLACE INTO carts VALUES (?,?,?,?,NULL,NULL,NULL)",
                      (customer_id, json.dumps(snap), _iso(now), _iso(now)))
        else:
            c.execute("UPDATE carts SET cart_json=?, last_seen_at=? WHERE customer_id=?", (json.dumps(snap), _iso(now), customer_id))
        c.commit()


def order_completed(customer_id: int, now: datetime | None = None) -> None:
    with closing(_db()) as c:
        c.execute("UPDATE carts SET completed_at=? WHERE customer_id=?", (_iso(now or _now()), customer_id))
        c.commit()


def cart_for(customer_id: int) -> list[dict]:
    with closing(_db()) as c:
        r = c.execute("SELECT cart_json FROM carts WHERE customer_id=?", (customer_id,)).fetchone()
    return json.loads(r[0]) if r else []


def _lines_text(cart: list[dict]) -> str:
    out = []
    for it in cart:
        name = it.get("game_name") or (lo_lotteries.by_game_code(str(it.get("game_code") or "")) or type("x", (), {"name": "Lottery"})).name
        for ln in it.get("lines") or []:
            parts = []
            for k, v in (ln or {}).items():
                nums = v if isinstance(v, str) else ",".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
                parts.append(nums.replace(",", " ") if k == "main" else f"+ {str(nums).replace(',', ' ')}")
            out.append(f"  {name}: {' '.join(parts)}")
    return "\n".join(out[:12]) + ("\n  ..." if len(out) > 12 else "")


def run(*, jackpot: Callable[[str], dict | None], resume_url: Callable[[int], str], push: Callable[[list[int], dict], dict],
        has_push: Callable[[int], bool], now: datetime | None = None) -> dict:
    now = now or _now()
    out = {"first": 0, "second": 0, "skipped_closed": 0, "skipped_consent": 0}
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM carts WHERE completed_at IS NULL AND second_sent_at IS NULL")]
    for r in rows:
        cid = int(r["customer_id"])
        cart = json.loads(r["cart_json"])
        last = _parse(r["last_seen_at"]) or now
        contact = lo_mail.contact(cid) or {}
        allowed = bool(contact.get("marketing_email")) and bool(contact.get("email"))
        game_codes = [str(it.get("game_code") or "") for it in cart if it.get("game_code")]
        lot = lo_lotteries.by_game_code(game_codes[0]) if game_codes else None
        name = lot.name if lot else "your lottery"
        jp = jackpot(game_codes[0]) if game_codes else None
        cutoff = _parse((jp or {}).get("cutoff_iso"))
        draw_open = bool(cutoff and cutoff > now and not (jp or {}).get("closed"))

        if r["first_sent_at"] is None:
            if now - last < FIRST_AFTER:
                continue
            if not draw_open:
                # the draw they picked has closed and the feed has nothing open yet: not a reminder for a closed draw
                out["skipped_closed"] += 1
                _mark(cid, "first_sent_at", now)
                continue
            if has_push(cid):
                push([cid], {"title": f"Your {name} lines are still in your cart",
                             "body": "Finish your order before the draw closes.", "url": resume_url(cid), "tag": f"cart-{cid}"})
            elif allowed:
                lo_mail.send_template(contact["email"], "cart_reminder",
                             {"lottery_name": name, "lines": [ln.strip() for ln in _lines_text(cart).splitlines()],
                              "closes_at": lo_mail.when(cutoff), "resume_url": resume_url(cid)},
                             text="You picked these lines but didn't finish your order:\n\n" + _lines_text(cart) +
                             f"\n\nThe next draw closes on {lo_mail.when(cutoff)}.\n\n"
                             "Pick up where you left off, with your lines still in your cart:\n" + resume_url(cid),
                             kind="cart-30m")
            else:
                out["skipped_consent"] += 1
            _mark(cid, "first_sent_at", now)
            out["first"] += 1
            continue

        if now - last < SECOND_AFTER:
            continue
        _mark(cid, "second_sent_at", now)       # one cycle only: whatever happens next, never a third
        if not draw_open:
            out["skipped_closed"] += 1
            continue
        if not allowed:
            out["skipped_consent"] += 1
            continue
        jackpot_line = f" The jackpot is {jp['display']}." if (jp or {}).get("display") else ""
        lo_mail.send_template(contact["email"], "cart_last_call",
                     {"lottery_name": name, "closes_at": lo_mail.when(cutoff), "jackpot": (jp or {}).get("display"),
                      "resume_url": resume_url(cid)},
                     text=f"Your {name} lines are still waiting in your cart. Ticket sales for the next draw close on "
                     f"{lo_mail.when(cutoff)}.{jackpot_line}\n\n"
                     "Your cart, with your lines:\n" + resume_url(cid) + "\n\n"
                     "This is the last reminder we'll send about this cart.", kind="cart-24h")
        out["second"] += 1
    return out


def _mark(cid: int, field: str, now: datetime) -> None:
    assert field in ("first_sent_at", "second_sent_at")
    with closing(_db()) as c:
        c.execute(f"UPDATE carts SET {field}=? WHERE customer_id=?", (_iso(now), cid))
        c.commit()


def register(app) -> None:
    from flask import redirect, request, session, url_for
    from itsdangerous import BadSignature, URLSafeTimedSerializer

    import lo_push

    signer = URLSafeTimedSerializer(app.secret_key, salt="lo-cart-resume")

    def resume_url(cid: int) -> str:
        return lo_mail.SITE_URL + url_for("cart_resume", token=signer.dumps({"c": cid}))

    @app.get("/cart/resume/<token>")
    def cart_resume(token: str):
        """The link in the reminders: the cart with the lines the customer picked, once they are logged in."""
        try:
            data = signer.loads(token, max_age=8 * 24 * 3600)
        except BadSignature:
            return redirect(url_for("cart"))
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        if not c or not session.get("crm_token"):
            return redirect(url_for("login", next=request.path))
        if str(c.get("id")) != str(data.get("c")):
            return redirect(url_for("cart"))
        if not session.get("cart_items"):
            session["cart_items"] = cart_for(int(data["c"]))
        return redirect(url_for("cart"))

    @app.before_request
    def _remember_contact():
        # once per session per customer: the address and marketing-email choice the scheduled emails need
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        if c and c.get("id") is not None and session.get("lo_contact_saved") != c.get("id"):
            try:
                lo_mail.remember_contact(c)
                session["lo_contact_saved"] = c.get("id")
            except Exception:
                pass

    @app.after_request
    def _cart_seen(resp):
        if request.endpoint == "cart" and request.method == "GET" and resp.status_code == 200:
            c = session.get("customer") if isinstance(session.get("customer"), dict) else None
            items = session.get("cart_items")
            if c and c.get("id") is not None and items:
                try:
                    cart_seen(int(c["id"]), items)
                except Exception as e:  # noqa: BLE001 - never break the cart page
                    app.logger.warning("recover: cart not recorded: %s", e)
        return resp

    app.config["LO_RECOVER_COMPLETED"] = order_completed

    @app.cli.command("abandoned-checkout")
    def abandoned_checkout_cmd():
        """Every 10 minutes: the 30-minute and 24-hour cart reminders (one cycle, marketing email consent only)."""
        with app.test_request_context("/"):
            print(run(jackpot=app.jinja_env.globals["lo_jackpot"], resume_url=resume_url, push=lo_push.send,
                      has_push=lo_push.has_subscription))
