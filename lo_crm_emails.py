"""The 13 emails that move off the website (plan of 18 Nov 2026, "who sends each one", section 4).

One switch, LO_EMAILS_VIA_CRM, off until the CRM and the Marketing Module confirm their side is live on www1:

* Off: nothing changes. The website sends its own copies, as before.
* On:
  - The 11 emails of sections 2C and 2D are posted to the CRM as `email_requested` events
    (POST /api/v1/marketing/events, service key) instead of being sent. `audience` says who sends:
    service / staff / invite = the CRM, marketing = the Marketing Module.
  - welcome_friend and homescreen_free_line (section 2B) are the CRM's own: the website neither sends nor posts them.
  - The website never sends the customer's address. The CRM looks it up from customer_id. The two exceptions are
    the CRM's: the staff copy goes to support@lottosonline.com, and the invite goes to metadata.to.

Every request is kept in data/crm_email_requests.sqlite under its event_id, so a post the CRM did not take (network,
outage) is posted again by the hourly journey job, with the same event_id. A posted event_id is never posted twice.

Test fire (section 4 item 3): /account/email-test-fire, on test hosts only (www1. and other lottosonline.com hosts
that are not www, and localhost), for the customer ids in LO_TEST_CUSTOMER_IDS only, while the switch is on. Each
button moves that one account's own timer back and runs the real job for that account alone, so it posts exactly
the event the real timer would, now.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

BRAND = "lottosonline"

# Section 2C (the CRM sends) and 2D (the Marketing Module sends).
POSTED: dict[str, str] = {
    "first_draw_day2": "service",
    "pack_opened": "service",
    "referral_reward": "service",
    "withdrawal_received": "service",
    "withdrawal_request_staff": "staff",
    "refer_friend_invite": "invite",
    "jackpot_alert": "marketing",
    "cart_reminder": "marketing",
    "cart_last_call": "marketing",
    "first_order_nudge": "marketing",
    "pack_waiting": "marketing",
}
# Section 2B: the CRM sends these from its own events. The website never posts them.
CRM_OWN = frozenset({"welcome_friend", "homescreen_free_line"})
# Never in metadata.data: the sender looks the address up from customer_id.
_ADDRESS_KEYS = frozenset({"email", "customer_email", "to"})

_state: dict[str, Any] = {"get_crm": None}


def switched_on() -> bool:
    return (os.getenv("LO_EMAILS_VIA_CRM") or "").strip().lower() in ("1", "true", "yes", "on")


def handles(key: str) -> bool:
    """True when the switch is on and this email is no longer the website's to send."""
    return switched_on() and (key in POSTED or key in CRM_OWN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db() -> sqlite3.Connection:
    import lo_mail
    p = lo_mail._data_dir() / "crm_email_requests.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS requests (event_id TEXT PRIMARY KEY, template TEXT NOT NULL,
                 payload TEXT NOT NULL, created_at TEXT NOT NULL, posted_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                 last_error TEXT)""")
    return c


def event_id(key: str, unique: str | None) -> str:
    unique = str(unique or "").strip() or uuid.uuid4().hex[:16]
    return f"web:{BRAND}:email_requested:{key}:{unique}"


def build_event(key: str, data: dict, *, customer_id: Any, unique: str | None, to: str | None = None,
                now: datetime | None = None) -> dict:
    meta: dict[str, Any] = {"template": key, "audience": POSTED[key],
                            "data": {k: v for k, v in (data or {}).items() if k not in _ADDRESS_KEYS}}
    if key == "refer_friend_invite":
        meta["to"] = str(to or "").strip()
    ev: dict[str, Any] = {"event_id": event_id(key, unique), "event_type": "email_requested",
                          "occurred_at": _iso(now or _now()), "metadata": meta}
    try:
        ev["customer_id"] = int(customer_id)
    except (TypeError, ValueError):
        pass
    return json.loads(json.dumps(ev, default=str))       # what is stored is exactly what is posted


def _post(payload: dict) -> None:
    get_crm = _state.get("get_crm")
    if get_crm is None:
        raise RuntimeError("no CRM client")
    get_crm().marketing_events(payload)                   # service key, no customer token


def _try_post(eid: str, payload: dict) -> bool:
    try:
        _post(payload)
        ok, err = True, None
    except Exception as e:  # noqa: BLE001 - kept and posted again later, under the same event_id
        ok, err = False, f"{type(e).__name__}: {str(e)[:200]}"
    with closing(_db()) as c:
        c.execute("UPDATE requests SET attempts=attempts+1, posted_at=?, last_error=? WHERE event_id=?",
                  (_iso(_now()) if ok else None, err, eid))
        c.commit()
    return ok


def request(key: str, data: dict, *, customer_id: Any = None, unique: str | None = None,
            to: str | None = None) -> str:
    """Post one email_requested event. Returns "requested", "queued" (kept, posted again later) or "duplicate"."""
    ev = build_event(key, data, customer_id=customer_id, unique=unique, to=to)
    eid = ev["event_id"]
    with closing(_db()) as c:
        cur = c.execute("INSERT OR IGNORE INTO requests (event_id, template, payload, created_at) VALUES (?,?,?,?)",
                        (eid, key, json.dumps(ev), ev["occurred_at"]))
        c.commit()
        if cur.rowcount == 0:
            row = c.execute("SELECT posted_at FROM requests WHERE event_id=?", (eid,)).fetchone()
            if row and row["posted_at"]:
                return "duplicate"
            ev = json.loads(c.execute("SELECT payload FROM requests WHERE event_id=?", (eid,)).fetchone()[0])
    return "requested" if _try_post(eid, ev) else "queued"


def retry_pending(limit: int = 200) -> dict:
    """Post again every kept request the CRM has not taken yet, oldest first, each under its own event_id."""
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT event_id, payload FROM requests WHERE posted_at IS NULL "
                                           "ORDER BY created_at LIMIT ?", (int(limit),))]
    out = {"posted": 0, "still_pending": 0}
    for r in rows:
        out["posted" if _try_post(r["event_id"], json.loads(r["payload"])) else "still_pending"] += 1
    return out


def recent(customer_id: int, limit: int = 30) -> list[dict]:
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM requests ORDER BY created_at DESC LIMIT 500")]
    out = []
    for r in rows:
        if json.loads(r["payload"]).get("customer_id") == int(customer_id):
            out.append({k: r[k] for k in ("event_id", "template", "created_at", "posted_at", "last_error")})
    return out[:limit]


# ------------------------------------------------------------------ test fire (www1, test accounts only)
def test_customer_ids() -> set[int]:
    out = set()
    for part in (os.getenv("LO_TEST_CUSTOMER_IDS") or "").replace(";", ",").split(","):
        try:
            out.add(int(part.strip()))
        except ValueError:
            pass
    return out


def test_host(host: str) -> bool:
    """www1. and the other lottosonline.com test copies, and a local preview. Never www or the bare domain."""
    host = (host or "").split(":")[0].strip().lower()
    if host in ("www.lottosonline.com", "lottosonline.com"):
        return False
    return host.endswith(".lottosonline.com") or host in ("localhost", "127.0.0.1")


def test_fire_allowed(host: str, customer_id: Any) -> bool:
    try:
        cid = int(customer_id)
    except (TypeError, ValueError):
        return False
    return switched_on() and test_host(host) and cid in test_customer_ids()


FIRES: dict[str, str] = {
    "cart_30m": "Cart reminder (30 minutes)",
    "cart_24h": "Cart last call (24 hours)",
    "nudge_day1": "First-order nudge, day 1",
    "nudge_day5": "First-order nudge, day 5 (final)",
    "day2": "The day after the first order",
    "pack_day3": "Gift pack waiting, day 3",
    "pack_day7": "Gift pack waiting, day 7",
    "pack_day10": "Gift pack waiting, day 10 (final)",
    "pack_autoopen": "Gift pack opens itself (day 14)",
}


def _rewind(path_db: Callable[[], sqlite3.Connection], sql: str, args: tuple) -> int:
    with closing(path_db()) as c:
        n = c.execute(sql, args).rowcount
        c.commit()
    return n


def _age_packs(cid: int, earned: datetime) -> int:
    """Make this account's sealed packs look earned at `earned`, as if the days had passed: the 14-day opening date
    and the order that earned the pack move back with it (so day 10 still sees "no order since")."""
    import lo_journey
    import lo_packs
    n = 0
    with closing(lo_packs._db()) as pc:
        packs = [dict(r) for r in pc.execute("SELECT pack_id, earned_at FROM packs WHERE customer_id=? AND state='sealed'", (cid,))]
        for p in packs:
            was = lo_packs._parse(p["earned_at"])
            if not was:
                continue
            shift = was - earned
            pc.execute("UPDATE packs SET earned_at=?, expires_at=? WHERE pack_id=?",
                       (lo_packs._iso(earned), lo_packs._iso(earned + timedelta(days=lo_packs.SEALED_DAYS)), p["pack_id"]))
            with closing(lo_journey._db()) as jc:
                row = jc.execute("SELECT ordered_at FROM last_orders WHERE customer_id=?", (cid,)).fetchone()
                ordered = lo_packs._parse(row[0]) if row else None
                if ordered and ordered <= was + timedelta(minutes=5):
                    jc.execute("UPDATE last_orders SET ordered_at=? WHERE customer_id=?", (lo_journey._iso(ordered - shift), cid))
                    jc.commit()
            n += 1
        pc.commit()
    return n


def fire(name: str, cid: int, *, jobs: dict[str, Callable[..., dict]], now: datetime | None = None) -> dict:
    """Move this one test account's timer back and run the real job for it alone. jobs: recover, journey, autoopen,
    each taking customer_id=. Returns the job's own counts, or {"error": ...} when there is nothing to fire."""
    import lo_journey
    import lo_packs
    import lo_recover
    now = now or _now()
    cid = int(cid)
    jiso = lo_journey._iso
    if name in ("cart_30m", "cart_24h"):
        back = lo_recover.FIRST_AFTER if name == "cart_30m" else lo_recover.SECOND_AFTER
        sql = "UPDATE carts SET last_seen_at=? WHERE customer_id=? AND completed_at IS NULL AND second_sent_at IS NULL"
        if name == "cart_24h":
            sql += " AND first_sent_at IS NOT NULL"
        if not _rewind(lo_recover._db, sql, (lo_recover._iso(now - back - timedelta(minutes=1)), cid)):
            return {"error": "No open cart for this account" + (" with the 30-minute reminder done" if name == "cart_24h" else "")
                    + ". Put lines in the cart and open the cart page" + (", then fire the 30-minute one" if name == "cart_24h" else "") + "."}
        return jobs["recover"](customer_id=cid)
    if name in ("nudge_day1", "nudge_day5"):
        back = lo_journey.NUDGE_AFTER[0 if name == "nudge_day1" else 1]
        sql = "UPDATE signups SET registered_at=? WHERE customer_id=? AND first_order_at IS NULL AND nudge2_at IS NULL"
        if name == "nudge_day1":
            sql += " AND nudge1_at IS NULL"
        if not _rewind(lo_journey._db, sql, (jiso(now - back - timedelta(minutes=1)), cid)):
            return {"error": "This account has no sign-up waiting for that nudge (it has ordered, or the nudge is done)."}
        return jobs["journey"](customer_id=cid)
    if name == "day2":
        if not _rewind(lo_journey._db, "UPDATE first_orders SET ordered_at=? WHERE customer_id=? AND day2_at IS NULL",
                       (jiso(now - lo_journey.DAY2_AFTER - timedelta(minutes=1)), cid)):
            return {"error": "This account has no first order waiting for the day-after email."}
        return jobs["journey"](customer_id=cid)
    if name.startswith("pack_day"):
        days = int(name[len("pack_day"):])
        if not _age_packs(cid, now - timedelta(days=days, minutes=1)):
            return {"error": "This account has no sealed gift pack."}
        return jobs["journey"](customer_id=cid)
    if name == "pack_autoopen":
        if not _age_packs(cid, now - timedelta(days=lo_packs.SEALED_DAYS, minutes=1)):
            return {"error": "This account has no sealed gift pack."}
        return jobs["autoopen"](customer_id=cid)
    return {"error": "Unknown test fire."}


# ------------------------------------------------------------------ web
def register(app) -> None:
    from flask import abort, render_template, request, session

    _state["get_crm"] = lambda: app.config["LO_ENGINE"]["get_crm"]()

    def _cid() -> int | None:
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        try:
            return int(c["id"]) if c and c.get("id") is not None else None
        except (TypeError, ValueError):
            return None

    def _jobs() -> dict[str, Callable[..., dict]]:
        import lo_journey
        import lo_packs
        import lo_push
        import lo_recover
        jackpot = app.jinja_env.globals["lo_jackpot"]
        return {
            "recover": lambda customer_id: lo_recover.run(
                jackpot=jackpot, resume_url=app.config["LO_RECOVER_RESUME_URL"], push=lo_push.send,
                has_push=lo_push.has_subscription, customer_id=customer_id),
            "journey": lambda customer_id: lo_journey.run(jackpot=jackpot, customer_id=customer_id),
            "autoopen": lambda customer_id: lo_packs.auto_open_expired(
                crm=app.config["LO_ENGINE"]["get_crm"](), games=app.config["LO_PACKS_GAMES"](),
                on_opened=lo_journey.pack_opened_email, customer_id=customer_id),
        }

    def _csrf_ok() -> bool:
        import secrets
        sent = (request.form.get("csrf_token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and secrets.compare_digest(sent, want))

    @app.route("/account/email-test-fire", methods=["GET", "POST"])
    def email_test_fire():
        """www1 only, test accounts only, switch on only: everything else is a plain 404."""
        cid = _cid()
        if not test_fire_allowed(request.host, cid):
            abort(404)
        result = None
        if request.method == "POST":
            name = request.form.get("fire") or ""
            if name not in FIRES or not _csrf_ok():
                abort(400)
            result = {"name": FIRES[name], "out": fire(name, cid, jobs=_jobs())}
        return render_template("lo/email_test_fire.html", fires=FIRES, result=result, recent=recent(cid),
                               customer_id=cid)

    @app.cli.command("crm-email-requests")
    def crm_email_requests_cmd():
        """Post again the email requests the CRM has not taken yet (the hourly journey job does this too)."""
        with app.test_request_context("/"):
            print(json.dumps(retry_pending()))
