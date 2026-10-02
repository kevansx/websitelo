"""Jackpot alerts (build brief 1, part 5). Needs nothing from the CRM: it reads the jackpots the site already caches.

* A customer follows every lottery they have played or been gifted (from lo_packs' activity record and opened
  packs), at a default threshold, unless they removed it; they can add others and change any threshold.
* Default threshold: twice the lottery's base (starting) jackpot, so an alert means a real rollover run; for a
  lottery with no known base, one and a half times the jackpot when the default was first worked out.
* The watcher (`flask jackpot-alerts`, every 30 minutes) compares cached jackpots to each threshold and fires once
  per lottery per draw, never twice. Delivery: push first (lo_push.py), email second (lo_mail.py) for customers
  with no push device who allow marketing email.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import lo_lotteries


def db_path() -> Path:
    import lo_packs
    return lo_packs.db_path().with_name("alerts.sqlite")


def _db() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        customer_id INTEGER NOT NULL, game_code TEXT NOT NULL, threshold REAL, removed INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL, PRIMARY KEY (customer_id, game_code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS fired (
        customer_id INTEGER NOT NULL, game_code TEXT NOT NULL, draw_key TEXT NOT NULL, fired_at TEXT NOT NULL,
        PRIMARY KEY (customer_id, game_code, draw_key))""")
    return c


def default_threshold(game_code: str, current: float | None = None) -> float | None:
    base = lo_lotteries.BASE_JACKPOTS.get(game_code)
    if base:
        return float(base) * 2
    if current:
        return _round_nice(float(current) * 1.5)
    return None


def _round_nice(v: float) -> float:
    """1.5 x 6.2M = 9.3M -> 9M; keeps thresholds readable."""
    if v >= 1_000_000:
        return float(round(v / 1_000_000) * 1_000_000)
    return float(round(v / 1_000) * 1_000)


def played_or_gifted(customer_id: int) -> set[str]:
    import lo_packs
    games: set[str] = set()
    try:
        with closing(lo_packs._db()) as c:
            a = lo_packs._activity(c, customer_id)
            if a:
                games |= set(a["games"])
            for r in c.execute("SELECT gift_json FROM packs WHERE customer_id=? AND state IN ('opened','auto_opened')", (customer_id,)):
                g = json.loads(r[0] or "{}")
                if g.get("game_code"):
                    games.add(g["game_code"])
    except Exception:
        pass
    return {g for g in games if lo_lotteries.by_game_code(g)}


def customer_alerts(customer_id: int, jackpot: Callable[[str], dict | None] | None = None) -> list[dict]:
    """Every lottery this customer follows, with its threshold (explicit rows win over defaults)."""
    with closing(_db()) as c:
        rows = {r["game_code"]: dict(r) for r in c.execute("SELECT * FROM alerts WHERE customer_id=?", (customer_id,))}
    out = []
    for gc in sorted(set(rows) | played_or_gifted(customer_id)):
        r = rows.get(gc)
        if r and r["removed"]:
            continue
        lot = lo_lotteries.by_game_code(gc)
        if lot is None:
            continue
        jp = jackpot(gc) if jackpot else None
        threshold = (r or {}).get("threshold") or default_threshold(gc, (jp or {}).get("amount"))
        out.append({"game_code": gc, "name": lot.name, "threshold": threshold, "custom": bool(r and r.get("threshold")),
                    "jackpot": jp})
    return out


def follow(customer_id: int, game_code: str, threshold: float | None = None) -> None:
    if lo_lotteries.by_game_code(game_code) is None:
        raise ValueError("unknown lottery")
    with closing(_db()) as c:
        c.execute("""INSERT INTO alerts (customer_id, game_code, threshold, removed, updated_at) VALUES (?,?,?,0,?)
                     ON CONFLICT(customer_id, game_code) DO UPDATE SET threshold=excluded.threshold, removed=0,
                     updated_at=excluded.updated_at""",
                  (customer_id, game_code, threshold, datetime.now(timezone.utc).isoformat()))
        c.commit()


def unfollow(customer_id: int, game_code: str) -> None:
    with closing(_db()) as c:
        c.execute("""INSERT INTO alerts (customer_id, game_code, threshold, removed, updated_at) VALUES (?,?,NULL,1,?)
                     ON CONFLICT(customer_id, game_code) DO UPDATE SET removed=1, updated_at=excluded.updated_at""",
                  (customer_id, game_code, datetime.now(timezone.utc).isoformat()))
        c.commit()


def _draw_key(jp: dict) -> str:
    return str(jp.get("draw_date") or jp.get("cutoff_iso") or "")[:10]


def run_watcher(*, customers: list[int], jackpot: Callable[[str], dict | None], fmt: Callable[[Any, str], str],
                send: Callable[[list[int], dict], dict]) -> dict:
    """Fire every alert whose jackpot has reached its threshold, once per lottery per draw."""
    fired = sent = 0
    for cid in customers:
        for a in customer_alerts(cid, jackpot):
            jp = a["jackpot"]
            if not jp or jp.get("closed") or a["threshold"] is None:
                continue
            try:
                amount = float(jp.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            key = _draw_key(jp)
            if amount < float(a["threshold"]) or not key:
                continue
            with closing(_db()) as c:
                try:
                    c.execute("INSERT INTO fired (customer_id, game_code, draw_key, fired_at) VALUES (?,?,?,?)",
                              (cid, a["game_code"], key, datetime.now(timezone.utc).isoformat()))
                    c.commit()
                except sqlite3.IntegrityError:
                    continue                      # already told them about this draw
            lot = lo_lotteries.by_game_code(a["game_code"])
            fired += 1
            res = send([cid], {
                "title": f"{a['name']}: {jp.get('display')}",
                "body": f"The {a['name']} jackpot you follow has passed {fmt(a['threshold'], jp.get('currency') or '')}.",
                "url": lo_lotteries.play_path(lot) if lot and lot.sells else "/",
                "tag": f"jackpot-{a['game_code']}-{key}",
            })
            sent += int((res or {}).get("sent") or 0)
    return {"fired": fired, "sent": sent}


def register(app) -> None:
    import secrets as _secrets

    from flask import abort, jsonify, redirect, render_template, request, session, url_for

    import lo_push

    def _cid() -> int | None:
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        try:
            return int(c["id"]) if c and c.get("id") is not None else None
        except (TypeError, ValueError):
            return None

    def _csrf_ok() -> bool:
        sent = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and _secrets.compare_digest(sent, want))

    def _jackpot(gc: str):
        return app.jinja_env.globals["lo_jackpot"](gc)

    @app.get("/account/alerts")
    def account_alerts():
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next=request.path))
        alerts = customer_alerts(cid, _jackpot)
        followed = {a["game_code"] for a in alerts}
        others = [l for l in lo_lotteries.LOTTERIES if l.sells and l.game_code not in followed]
        return render_template("lo/alerts.html", alerts=alerts, others=others, push_on=lo_push.has_subscription(cid),
                               fmt=app.jinja_env.globals["lo_fmt_jackpot"], noindex="noindex, nofollow")

    @app.post("/account/alerts")
    def account_alerts_save():
        if not _csrf_ok():
            abort(400)
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next="/account/alerts"))
        action, gc = request.form.get("action"), (request.form.get("game_code") or "").strip()
        wants_json = "application/json" in (request.headers.get("Accept") or "")
        try:
            if action == "remove":
                unfollow(cid, gc)
            else:
                raw = (request.form.get("threshold_millions") or "").strip()
                threshold = float(raw) * 1_000_000 if raw else None
                if threshold is not None and not (0 < threshold < 1e11):
                    raise ValueError("bad threshold")
                follow(cid, gc, threshold)
        except ValueError:
            if wants_json:
                return jsonify({"ok": False}), 400
            return redirect(url_for("account_alerts", error=1))
        if wants_json:
            return jsonify({"ok": True})
        return redirect(url_for("account_alerts", saved=1))

    @app.cli.command("jackpot-alerts")
    def jackpot_alerts_cmd():
        """Every 30 minutes: tell followers when a jackpot passes their threshold (once per draw)."""
        import lo_mail
        with closing(lo_push._db()) as c:
            customers = {r[0] for r in c.execute("SELECT DISTINCT customer_id FROM subscriptions")}
        customers |= {int(r["customer_id"]) for r in lo_mail.marketing_contacts()}
        with app.test_request_context("/"):
            print(run_watcher(customers=sorted(customers), jackpot=_jackpot, fmt=app.jinja_env.globals["lo_fmt_jackpot"],
                              send=deliver))

    def deliver(ids: list[int], payload: dict) -> dict:
        """Push first; email second, for customers with no push device who allow marketing email."""
        import lo_mail
        res = dict(lo_push.send(ids, payload))
        for cid in ids:
            if lo_push.has_subscription(cid):
                continue
            ct = lo_mail.contact(cid) or {}
            if ct.get("marketing_email") and ct.get("email"):
                lo_mail.send(ct["email"], payload["title"],
                             payload["body"] + "\n\nPlay here: " + lo_mail.SITE_URL + payload["url"] +
                             "\n\nTo change or stop these alerts: " + lo_mail.SITE_URL + "/account/alerts",
                             kind="jackpot-alert")
                res["emailed"] = res.get("emailed", 0) + 1
        return res

    app.config["LO_ALERTS_DELIVER"] = deliver
