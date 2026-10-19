"""The sign-up journey and the gift-pack emails around it (Joey, 19 Oct 2026).

Built on the onboarding plan (Plans, 2 Oct 2026, section 6) and the pack rewards plan (section 4):

* No reward for signing up. The gift pack comes with the first paid order and opens on the confirmation screen.
* Signed up, no order yet: a nudge on day 1 and a last one on day 5 ("first_order_nudge"), pointing at that first
  order. Marketing: only with consent. Both stop the moment they order.
* The day after their first paid order: one message about the draw they are in, and their gift pack if it is
  still sealed ("first_draw_day2"). A service email about their order, so no consent is needed; never for a draw
  that has already happened.
* A sealed gift pack: a reminder on day 3 and day 7, and a last one on day 10 if they have not ordered since
  ("pack_waiting"). Marketing: only with consent. Day 14 the pack opens itself (lo_packs.auto_open_expired) and
  "pack_opened" says so; that one is a service email, it tells them what was put in their account.
* Only one email per pack or per stage, whatever the job's timing: a job that missed a day sends the latest stage
  that is due and marks the earlier ones done.
* Every send goes through lo_mail.send_template: Danish accounts are skipped, and without SMTP settings the email
  goes to data/outbox.

`flask journey-emails` runs it, hourly.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import lo_lotteries
import lo_mail
import lo_packs
import lo_txmail

NUDGE_AFTER = (timedelta(days=1), timedelta(days=5))   # signed up, no order: day 1, then a last one on day 5
NUDGE_GIVE_UP = timedelta(days=8)                      # a stage this late is skipped, not sent
DAY2_AFTER = timedelta(hours=20)                       # "the next day", whatever time they ordered
DAY2_GIVE_UP = timedelta(days=4)
PACK_STAGES = (3, 7, 10)                               # days sealed; 10 is the last, and only if no order since
# The lotteries a nudge features, in order: the first with an open draw and a jackpot on the feed.
NUDGE_LOTTERIES = ("powerball", "megamillions", "euromillions-at", "eurojackpot")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    p = lo_mail._data_dir() / "journey.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS signups (customer_id INTEGER PRIMARY KEY, email TEXT, first_name TEXT,
                 country TEXT, marketing INTEGER NOT NULL, registered_at TEXT NOT NULL, first_order_at TEXT,
                 nudge1_at TEXT, nudge2_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS first_orders (customer_id INTEGER PRIMARY KEY, order_id TEXT NOT NULL,
                 ordered_at TEXT NOT NULL, game_code TEXT, lottery_name TEXT, draw_at TEXT, day2_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS last_orders (customer_id INTEGER PRIMARY KEY, ordered_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS pack_mail (pack_id TEXT NOT NULL, stage INTEGER NOT NULL, at TEXT NOT NULL, "
              "PRIMARY KEY (pack_id, stage))")
    return c


# ------------------------------------------------------------------ what happened
def on_registered(customer: dict, now: datetime | None = None) -> None:
    try:
        cid = int((customer or {}).get("id"))
    except (TypeError, ValueError):
        return
    with closing(_db()) as c:
        c.execute("INSERT OR IGNORE INTO signups (customer_id, email, first_name, country, marketing, registered_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (cid, str(customer.get("email") or "").strip(), lo_txmail.first_name(customer),
                   lo_mail.customer_country(customer) or None, int(lo_mail.marketing_allowed(customer)),
                   _iso(now or _now())))
        c.commit()


def on_order(customer: dict, *, order_id: Any, items: list[dict], order: dict | None = None,
             now: datetime | None = None) -> None:
    """Any paid order. The first one after signing up on this site starts the day-2 email."""
    try:
        cid = int((customer or {}).get("id"))
    except (TypeError, ValueError):
        return
    now = now or _now()
    with closing(_db()) as c:
        c.execute("INSERT OR REPLACE INTO last_orders VALUES (?,?)", (cid, _iso(now)))
        s = c.execute("SELECT first_order_at FROM signups WHERE customer_id=?", (cid,)).fetchone()
        if s is not None and s["first_order_at"] is None:
            c.execute("UPDATE signups SET first_order_at=? WHERE customer_id=?", (_iso(now), cid))
            first = next((it for it in items or [] if isinstance(it, dict) and it.get("game_code")), {})
            code = str(first.get("game_code") or "")
            draw_at = None
            for t in (order or {}).get("tickets") or []:
                d = lo_mail.parse_utc(t.get("draw_date")) if isinstance(t, dict) else None
                if d and str(t.get("game_code") or "") == code and (draw_at is None or d < draw_at):
                    draw_at = d
            c.execute("INSERT OR IGNORE INTO first_orders (customer_id, order_id, ordered_at, game_code, lottery_name, "
                      "draw_at) VALUES (?,?,?,?,?,?)",
                      (cid, str(order_id), _iso(now), code or None,
                       str(first.get("game_name") or "") or None, _iso(draw_at) if draw_at else None))
        c.commit()


# ------------------------------------------------------------------ the hourly job
def _consent(cid: int, fallback: bool) -> tuple[str, bool]:
    """The address and marketing choice, the CRM's latest as the site last saw it."""
    ct = lo_mail.contact(cid) or {}
    return str(ct.get("email") or ""), bool(ct.get("marketing_email")) if ct else fallback


def _featured(jackpot: Callable[[str], dict | None], now: datetime) -> dict:
    for code in NUDGE_LOTTERIES:
        jp = jackpot(code) or {}
        cutoff = lo_mail.parse_utc(jp.get("cutoff_iso"))
        if jp.get("display") and cutoff and cutoff > now and not jp.get("closed"):
            lot = lo_lotteries.by_game_code(code)
            if lot:
                return {"lottery_name": lot.name, "jackpot": jp["display"], "closes_at": lo_mail.when(cutoff),
                        "play_url": lo_mail.SITE_URL + lo_lotteries.play_path(lot)}
    return {}


def _nudges(now: datetime, jackpot: Callable[[str], dict | None], out: dict) -> None:
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM signups WHERE first_order_at IS NULL AND nudge2_at IS NULL")]
    for r in rows:
        cid = int(r["customer_id"])
        age = now - (lo_mail.parse_utc(r["registered_at"]) or now)
        stage = 2 if age >= NUDGE_AFTER[1] else 1 if age >= NUDGE_AFTER[0] else 0
        if stage == 0 or (stage == 1 and r["nudge1_at"]):
            continue
        field = "nudge2_at" if stage == 2 else "nudge1_at"
        _set(cid, "signups", field, now)
        if stage == 2 and not r["nudge1_at"]:
            _set(cid, "signups", "nudge1_at", now)
        if age > NUDGE_GIVE_UP:
            out["skipped_late"] += 1
            continue
        email, allowed = _consent(cid, bool(r["marketing"]))
        email = email or str(r["email"] or "")
        if not (allowed and email):
            out["skipped_consent"] += 1
            continue
        data = {"first_name": r["first_name"], "final": stage == 2, **_featured(jackpot, now)}
        if lo_mail.send_template(email, "first_order_nudge", data, country=r["country"], kind=f"nudge-{stage}") != "blocked":
            out["nudges"] += 1


def _pack_for_order(cid: int, order_id: str) -> dict | None:
    for p in sum(lo_packs.customer_packs(cid).values(), []):
        if str(p.get("order_id")) == str(order_id):
            return p
    return None


def _day2(now: datetime, jackpot: Callable[[str], dict | None], out: dict) -> None:
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM first_orders WHERE day2_at IS NULL")]
    for r in rows:
        cid = int(r["customer_id"])
        age = now - (lo_mail.parse_utc(r["ordered_at"]) or now)
        if age < DAY2_AFTER:
            continue
        _set(cid, "first_orders", "day2_at", now)
        draw_at = lo_mail.parse_utc(r["draw_at"])
        jp = jackpot(r["game_code"]) if r["game_code"] else None
        if draw_at is None:
            # the feed's next draw for that lottery, or failing that its ticket cut-off (shortly before the draw)
            draw_at = lo_mail.parse_utc((jp or {}).get("draw_date") or (jp or {}).get("cutoff_iso"))
        if age > DAY2_GIVE_UP or (draw_at is not None and draw_at <= now):
            out["skipped_late"] += 1           # never "you're in the draw" about a draw that has happened
            continue
        ct = lo_mail.contact(cid) or {}
        with closing(_db()) as c:
            s = c.execute("SELECT * FROM signups WHERE customer_id=?", (cid,)).fetchone()
        email = str(ct.get("email") or (s["email"] if s else "") or "")
        if not email:
            continue
        lot = lo_lotteries.by_game_code(r["game_code"] or "")
        data: dict[str, Any] = {
            "first_name": s["first_name"] if s else None,
            "lottery_name": r["lottery_name"] or (lot.name if lot else "your lottery"),
            "draw_date": lo_txmail.day(draw_at) if draw_at else None,
            "jackpot": (jp or {}).get("display"),
            "pack_url": None, "pack_is_gold": False, "gift_title": None, "gift_detail": None,
        }
        pack = _pack_for_order(cid, r["order_id"])
        if pack and pack["state"] == "sealed":
            data["pack_url"] = f"{lo_mail.SITE_URL}/packs/{pack['pack_id']}"
            data["pack_is_gold"] = pack.get("tier") == "premium"
        elif pack and (pack.get("gift") or {}).get("card"):
            card = pack["gift"]["card"]
            data["gift_title"] = f"{card.get('sub')} on {card.get('title')}".strip()
            data["gift_detail"] = card.get("expiry")
        if lo_mail.send_template(email, "first_draw_day2", data, country=(s["country"] if s else None)) != "blocked":
            out["day2"] += 1


def _pack_reminders(now: datetime, out: dict) -> None:
    with closing(lo_packs._db()) as pc:
        packs = [lo_packs._row(r) for r in pc.execute("SELECT * FROM packs WHERE state='sealed'")]
    for p in packs:
        earned = lo_mail.parse_utc(p["earned_at"])
        expires = lo_mail.parse_utc(p["expires_at"])
        if not earned or (expires and expires <= now):
            continue
        days = (now - earned).days
        due = [s for s in PACK_STAGES if days >= s]
        if not due:
            continue
        stage = due[-1]
        with closing(_db()) as c:
            done = {int(r[0]) for r in c.execute("SELECT stage FROM pack_mail WHERE pack_id=?", (p["pack_id"],))}
            if stage in done:
                continue
            for s in due:
                c.execute("INSERT OR IGNORE INTO pack_mail VALUES (?,?,?)", (p["pack_id"], s, _iso(now)))
            last = c.execute("SELECT ordered_at FROM last_orders WHERE customer_id=?", (int(p["customer_id"]),)).fetchone()
            c.commit()
        if stage == PACK_STAGES[-1]:
            ordered = lo_mail.parse_utc(last[0]) if last else None
            if ordered and ordered > earned + timedelta(minutes=5):
                out["skipped_ordered"] += 1    # day 10 is only for someone who has not been back
                continue
        email, allowed = _consent(int(p["customer_id"]), False)
        if not (allowed and email):
            out["skipped_consent"] += 1
            continue
        if lo_mail.send_template(email, "pack_waiting", {
            "first_name": None, "is_gold": p.get("tier") == "premium", "final": stage == PACK_STAGES[-1],
            "pack_url": f"{lo_mail.SITE_URL}/packs/{p['pack_id']}",
            "opens_on": lo_txmail.day(expires) if expires else None,
        }, kind=f"pack-day{stage}") != "blocked":
            out["pack_reminders"] += 1


def pack_opened_email(pack: dict) -> str:
    """Day 14: the pack opened itself. Tells the customer what is now in their account."""
    try:
        card = ((pack or {}).get("gift") or {}).get("card") or {}
        ct = lo_mail.contact(int(pack["customer_id"])) or {}
        if not ct.get("email") or not lo_mail.once(f"pack-opened-{pack['pack_id']}"):
            return "skipped"
        return lo_mail.send_template(ct["email"], "pack_opened", {
            "first_name": None, "gift_title": f"{card.get('sub', 'A free entry')} on {card.get('title', 'a lottery')}",
            "gift_detail": card.get("expiry"),
        })
    except Exception:  # noqa: BLE001 - the gift is granted either way
        return "failed"


def run(*, jackpot: Callable[[str], dict | None], now: datetime | None = None) -> dict:
    now = now or _now()
    out = {"nudges": 0, "day2": 0, "pack_reminders": 0, "skipped_consent": 0, "skipped_late": 0, "skipped_ordered": 0}
    _nudges(now, jackpot, out)
    _day2(now, jackpot, out)
    _pack_reminders(now, out)
    return out


def _set(cid: int, table: str, field: str, now: datetime) -> None:
    assert (table, field) in {("signups", "nudge1_at"), ("signups", "nudge2_at"), ("first_orders", "day2_at")}
    with closing(_db()) as c:
        c.execute(f"UPDATE {table} SET {field}=? WHERE customer_id=?", (_iso(now), cid))
        c.commit()


def register(app) -> None:
    @app.cli.command("journey-emails")
    def journey_emails_cmd():
        """Hourly: first-order nudges, the day-2 email and gift-pack reminders (see lo_journey.py)."""
        with app.test_request_context("/"):
            print(json.dumps(run(jackpot=app.jinja_env.globals["lo_jackpot"])))
