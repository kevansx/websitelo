"""Refer a friend (Joey, 20 Oct 2026), on the Live Friends model.

* Every customer has a personal link, https://www.lottosonline.com/r/<code>, on /account/refer, with copy and share
  buttons and an "email a friend" box (the refer_friend_invite email).
* A friend who opens the link and creates an account within 30 days is recorded as that customer's referral, and gets
  the "welcome, joined through a friend" email instead of the ordinary welcome.
* When the friend's first order of €5 or more goes through, both get a gift pack (type "friend", drawn like any other
  pack) and both get the "friend reward" email.
* No cap on friends (Joey). Safeguards against abuse instead:
    refused  the link's owner signs up with it, or the friend's email is the referrer's (gmail dots and +tags
             ignored); no reward, ever.
    held     the friend signed up from a connection the referrer has used, or the referrer already has 5 rewards in
             the last 7 days. Nothing is granted until the team approves it (`flask referral-approve <friend id>`;
             `flask referrals-held` lists them).
  Once the CRM can say whether a friend's card was already used on another account (CRM ask, 20 Oct), that becomes a
  third check.
* Starts fresh: old-site referral links and codes are not honoured.
* Every email goes through lo_mail.send_template (Danish accounts excluded; the CRM sends them once the website posts
  email_requested events).
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

import lo_mail

LINK_DAYS = 30                                   # sign up within 30 days of opening the link
MIN_ORDER_EUR_CENTS = 500                        # the friend's first order of €5 or more
VELOCITY = (5, timedelta(days=7))                # more than this many rewards in a week: hold for the team
INVITES_PER_DAY = 10
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to misread
APPROX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "AUD": 0.61, "CAD": 0.68, "NZD": 0.56}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    p = lo_mail._data_dir() / "referral.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS codes (customer_id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, "
              "created_at TEXT NOT NULL, first_name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS ips (customer_id INTEGER NOT NULL, ip TEXT NOT NULL, seen_at TEXT NOT NULL, "
              "PRIMARY KEY (customer_id, ip))")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (friend_id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL,
                 code TEXT NOT NULL, friend_first_name TEXT, signed_up_at TEXT NOT NULL, signup_ip TEXT,
                 status TEXT NOT NULL, reason TEXT, order_id TEXT, rewarded_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS invites (customer_id INTEGER NOT NULL, email TEXT NOT NULL, sent_at TEXT NOT NULL)")
    return c


# ------------------------------------------------------------------ codes and links
def code_for(customer_id: int, first_name: str | None = None) -> str:
    """The customer's code, made the first time. first_name is kept with it for the emails that name the referrer."""
    first_name = str(first_name or "").strip() or None
    with closing(_db()) as c:
        r = c.execute("SELECT code FROM codes WHERE customer_id=?", (int(customer_id),)).fetchone()
        if r:
            if first_name:
                c.execute("UPDATE codes SET first_name=? WHERE customer_id=?", (first_name, int(customer_id)))
                c.commit()
            return r[0]
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(7))
            try:
                c.execute("INSERT INTO codes VALUES (?,?,?,?)", (int(customer_id), code, _iso(_now()), first_name))
                c.commit()
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("could not make a referral code")


def link_for(customer_id: int, first_name: str | None = None) -> str:
    return f"{lo_mail.SITE_URL}/r/{code_for(customer_id, first_name)}"


def referrer_for_code(code: str) -> int | None:
    code = str(code or "").strip().upper()
    if not re.fullmatch(f"[{CODE_ALPHABET}]{{7}}", code):
        return None
    with closing(_db()) as c:
        r = c.execute("SELECT customer_id FROM codes WHERE code=?", (code,)).fetchone()
    return int(r[0]) if r else None


def note_ip(customer_id: int, ip: str | None, now: datetime | None = None) -> None:
    """The connections a customer uses, so a friend signing up from one of them is held for the team."""
    if not ip:
        return
    with closing(_db()) as c:
        c.execute("INSERT OR REPLACE INTO ips VALUES (?,?,?)", (int(customer_id), str(ip), _iso(now or _now())))
        c.commit()


def normal_email(email: str) -> str:
    """Lower case; for Gmail, dots and +tags removed (a.b+x@gmail.com is ab@gmail.com)."""
    e = str(email or "").strip().lower()
    if "@" not in e:
        return e
    local, domain = e.split("@", 1)
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


# ------------------------------------------------------------------ sign-up
def on_signup(friend: dict, code: str, ip: str | None, now: datetime | None = None) -> dict | None:
    """Record a friend's sign-up through a link. Returns the referral (status pending or held), or None when the link
    is unknown or the sign-up is refused."""
    now = now or _now()
    try:
        friend_id = int((friend or {}).get("id"))
    except (TypeError, ValueError):
        return None
    referrer_id = referrer_for_code(code)
    if referrer_id is None:
        return None
    status, reason = "pending", None
    ref_email = str((lo_mail.contact(referrer_id) or {}).get("email") or "")
    if referrer_id == friend_id or (ref_email and normal_email(ref_email) == normal_email(friend.get("email"))):
        status, reason = "refused", "the referrer's own account"
    elif ip:
        with closing(_db()) as c:
            if c.execute("SELECT 1 FROM ips WHERE customer_id=? AND ip=?", (referrer_id, str(ip))).fetchone():
                status, reason = "held", "signed up from a connection the referrer has used"
    with closing(_db()) as c:
        c.execute("INSERT OR IGNORE INTO referrals (friend_id, referrer_id, code, friend_first_name, signed_up_at, "
                  "signup_ip, status, reason) VALUES (?,?,?,?,?,?,?,?)",
                  (friend_id, referrer_id, code.upper(), str(friend.get("first_name") or "").strip() or None,
                   _iso(now), ip, status, reason))
        c.commit()
    return None if status == "refused" else get(friend_id)


def get(friend_id: int) -> dict | None:
    with closing(_db()) as c:
        r = c.execute("SELECT * FROM referrals WHERE friend_id=?", (int(friend_id),)).fetchone()
    return dict(r) if r else None


def referrals_of(referrer_id: int) -> list[dict]:
    with closing(_db()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM referrals WHERE referrer_id=? AND status != 'refused' "
                                           "ORDER BY signed_up_at DESC", (int(referrer_id),))]


# ------------------------------------------------------------------ the reward
def _in_eur(cents: Any, currency: str | None) -> float:
    try:
        return int(cents or 0) * APPROX_TO_EUR.get(str(currency or "EUR").upper(), 0.0)
    except (TypeError, ValueError):
        return 0.0


def on_order(friend_id: int, *, order_id: Any, total_cents: Any, currency: str | None,
             now: datetime | None = None) -> str:
    """A paid order by someone who may be a referred friend. Returns what happened: none, too_small, held,
    rewarded or already."""
    now = now or _now()
    r = get(friend_id)
    if not r or r["status"] == "refused":
        return "none"
    if r["status"] == "rewarded":
        return "already"
    if r["status"] == "held":
        return "held"
    if _in_eur(total_cents, currency) < MIN_ORDER_EUR_CENTS:
        return "too_small"
    limit, window = VELOCITY
    with closing(_db()) as c:
        recent = c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND status='rewarded' AND rewarded_at >= ?",
                           (r["referrer_id"], _iso(now - window))).fetchone()[0]
        if recent >= limit:
            c.execute("UPDATE referrals SET status='held', reason=?, order_id=? WHERE friend_id=?",
                      (f"more than {limit} friend rewards in {window.days} days", str(order_id), int(friend_id)))
            c.commit()
            return "held"
    _reward(int(friend_id), order_id, now)
    return "rewarded"


def _reward(friend_id: int, order_id: Any, now: datetime) -> None:
    import lo_packs
    r = get(friend_id)
    key = f"ref-{friend_id}"
    friend_pack = lo_packs.grant_pack(customer_id=friend_id, kind="friend", key=f"{key}-friend", order_id=order_id)
    referrer_pack = lo_packs.grant_pack(customer_id=r["referrer_id"], kind="friend", key=f"{key}-referrer")
    with closing(_db()) as c:
        c.execute("UPDATE referrals SET status='rewarded', reason=NULL, order_id=COALESCE(order_id, ?), rewarded_at=? "
                  "WHERE friend_id=?", (str(order_id) if order_id is not None else None, _iso(now), friend_id))
        c.commit()
    friend, referrer = lo_mail.contact(friend_id) or {}, lo_mail.contact(r["referrer_id"]) or {}
    ref_name = _first_name(r["referrer_id"])
    for to, pack, is_referrer in ((friend.get("email"), friend_pack, False), (referrer.get("email"), referrer_pack, True)):
        if to and lo_mail.once(f"referral-reward-{friend_id}-{int(is_referrer)}"):
            lo_mail.send_template(to, "referral_reward", {
                "first_name": ref_name if is_referrer else r["friend_first_name"],
                "friend_first_name": r["friend_first_name"] or "Your friend", "referrer_first_name": ref_name or "your friend",
                "is_referrer": is_referrer, "pack_url": f"{lo_mail.SITE_URL}/packs/{pack['pack_id']}",
                "pack_is_gold": False, "referral_url": f"{lo_mail.SITE_URL}/account/refer",
            }, kind="referral-reward")


def approve(friend_id: int, now: datetime | None = None) -> bool:
    """The team approves a held referral: the gift packs and emails go out now."""
    r = get(friend_id)
    if not r or r["status"] != "held":
        return False
    _reward(int(friend_id), r["order_id"], now or _now())
    return True


def refuse(friend_id: int, reason: str = "refused by the team") -> bool:
    r = get(friend_id)
    if not r or r["status"] == "rewarded":
        return False
    with closing(_db()) as c:
        c.execute("UPDATE referrals SET status='refused', reason=? WHERE friend_id=?", (reason, int(friend_id)))
        c.commit()
    return True


def held() -> list[dict]:
    with closing(_db()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM referrals WHERE status='held' ORDER BY signed_up_at")]


# ------------------------------------------------------------------ names and invites
def _first_name(customer_id: int) -> str | None:
    with closing(_db()) as c:
        r = c.execute("SELECT first_name FROM codes WHERE customer_id=?", (int(customer_id),)).fetchone()
    return r[0] if r and r[0] else None


def invite(customer_id: int, first_name: str | None, email: str, message: str | None,
           now: datetime | None = None) -> str:
    """Email a friend the link. Returns sent, limit, bad_email or self."""
    now = now or _now()
    email = str(email or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return "bad_email"
    own = str((lo_mail.contact(customer_id) or {}).get("email") or "")
    if own and normal_email(own) == normal_email(email):
        return "self"
    with closing(_db()) as c:
        n = c.execute("SELECT COUNT(*) FROM invites WHERE customer_id=? AND sent_at >= ?",
                      (int(customer_id), _iso(now - timedelta(days=1)))).fetchone()[0]
        if n >= INVITES_PER_DAY:
            return "limit"
        c.execute("INSERT INTO invites VALUES (?,?,?)", (int(customer_id), email, _iso(now)))
        c.commit()
    lo_mail.send_template(email, "refer_friend_invite", {
        "referrer_first_name": (first_name or "A friend").strip(), "invite_url": link_for(customer_id, first_name),
        "message": (str(message or "").strip()[:300] or None),
    }, kind="referral-invite")
    return "sent"


# ------------------------------------------------------------------ web
def register(app) -> None:
    from flask import abort, flash, redirect, render_template, request, session, url_for
    import secrets as _secrets

    def _cid() -> int | None:
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        try:
            return int(c["id"]) if c and c.get("id") is not None else None
        except (TypeError, ValueError):
            return None

    @app.before_request
    def _referral_seen():
        # each signed-in customer's connection, once per session (the "same connection" safeguard)
        cid = _cid()
        if cid is not None and session.get("lo_ref_ip_saved") != cid:
            try:
                note_ip(cid, request.remote_addr)
                session["lo_ref_ip_saved"] = cid
            except Exception:
                pass

    @app.get("/r/<code>")
    def referral_link(code: str):
        """A friend's link: remembered for 30 days, then on to the sign-up form."""
        if referrer_for_code(code) is not None:
            session["lo_ref"] = {"code": code.upper(), "at": _iso(_now())}
            session.permanent = True
        return redirect(url_for("register"))

    @app.get("/account/refer")
    def account_refer():
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next=request.path))
        friends = referrals_of(cid)
        c = session.get("customer") or {}
        return render_template("lo/refer.html", link=link_for(cid, c.get("first_name")), friends=friends,
                               rewarded=sum(1 for f in friends if f["status"] == "rewarded"),
                               noindex="noindex, nofollow")

    @app.post("/account/refer/invite")
    def account_refer_invite():
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next="/account/refer"))
        sent = (request.form.get("csrf_token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        if not (sent and want and _secrets.compare_digest(sent, want)):
            abort(400)
        c = session.get("customer") or {}
        result = invite(cid, c.get("first_name"), request.form.get("email"), request.form.get("message"))
        flash({"sent": "Invitation sent.", "limit": "You've sent the most invitations for today. Try again tomorrow.",
               "bad_email": "Please enter a valid email address.",
               "self": "That's your own email address."}[result], "success" if result == "sent" else "error")
        return redirect(url_for("account_refer"))

    app.config["LO_REFERRAL"] = {"pending_code": _pending_code}

    @app.cli.command("referrals-held")
    def referrals_held_cmd():
        """List referrals held for the team to check."""
        for r in held():
            print(f"friend {r['friend_id']}  referrer {r['referrer_id']}  signed up {r['signed_up_at'][:10]}  "
                  f"order {r['order_id'] or '-'}  reason: {r['reason']}")

    import click

    @app.cli.command("referral-approve")
    @click.argument("friend_id", type=int)
    def referral_approve_cmd(friend_id: int):
        """Approve a held referral: both gift packs and emails go out."""
        print("approved" if approve(friend_id) else "not held")

    @app.cli.command("referral-refuse")
    @click.argument("friend_id", type=int)
    def referral_refuse_cmd(friend_id: int):
        """Refuse a referral: no gift packs."""
        print("refused" if refuse(friend_id) else "not refused (unknown, or already rewarded)")


def _pending_code(session: Any) -> str | None:
    """The link a visitor opened, if it is still within 30 days."""
    ref = session.get("lo_ref") if isinstance(session.get("lo_ref"), dict) else None
    at = lo_mail.parse_utc((ref or {}).get("at"))
    if not ref or not at or _now() - at > timedelta(days=LINK_DAYS):
        return None
    return str(ref.get("code") or "") or None
