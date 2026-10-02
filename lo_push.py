"""Web push (build brief 1, part 4).

* VAPID keys live in the environment only: LO_VAPID_PUBLIC_KEY (sent to browsers), LO_VAPID_PRIVATE_KEY (never
  leaves the server), LO_VAPID_SUBJECT (mailto: contact the push services can reach). `flask push-keys` prints
  a new pair. Without keys push is simply off: no prompt is shown and nothing is sent.
* POST /push/subscribe stores a browser's endpoint + p256dh + auth against the logged-in customer;
  POST /push/unsubscribe removes it. GET /push/key gives the public key.
* The service worker (/sw.js, lo_homescreen.py) shows the notification and opens its link when tapped.
* send(customer_ids, payload) is the server-side sender; subscriptions the push service reports gone (404/410)
  are deleted.
* Permission is asked on the install screen (running as the installed app, next to the free ticket), never on
  a first visit and never by itself: the browser prompt only follows a tap. A customer who says no is not asked
  again automatically; the account's alerts page offers it once more.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def keys() -> dict | None:
    pub = (os.environ.get("LO_VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("LO_VAPID_PRIVATE_KEY") or "").strip()
    if not pub or not priv:
        return None
    return {"public": pub, "private": priv,
            "subject": (os.environ.get("LO_VAPID_SUBJECT") or "mailto:support@lottosonline.com").strip()}


def enabled() -> bool:
    return keys() is not None


def db_path() -> Path:
    base = (os.environ.get("LO_PUSH_DB_PATH") or "").strip()
    if base:
        return Path(base)
    import lo_packs
    return lo_packs.db_path().with_name("push.sqlite")


def _db() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        endpoint TEXT PRIMARY KEY, customer_id INTEGER NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
        created_at TEXT NOT NULL, last_sent_at TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS subs_customer ON subscriptions(customer_id)")
    return c


def subscribe(customer_id: int, sub: dict) -> None:
    endpoint = str(sub.get("endpoint") or "")
    k = sub.get("keys") or {}
    if not endpoint.startswith("https://") or not k.get("p256dh") or not k.get("auth"):
        raise ValueError("bad subscription")
    with closing(_db()) as c:
        c.execute("INSERT OR REPLACE INTO subscriptions (endpoint, customer_id, p256dh, auth, created_at) VALUES (?,?,?,?,?)",
                  (endpoint, int(customer_id), str(k["p256dh"]), str(k["auth"]), datetime.now(timezone.utc).isoformat()))
        c.commit()


def unsubscribe(customer_id: int, endpoint: str | None = None) -> None:
    with closing(_db()) as c:
        if endpoint:
            c.execute("DELETE FROM subscriptions WHERE customer_id=? AND endpoint=?", (int(customer_id), endpoint))
        else:
            c.execute("DELETE FROM subscriptions WHERE customer_id=?", (int(customer_id),))
        c.commit()


def has_subscription(customer_id: int) -> bool:
    with closing(_db()) as c:
        return c.execute("SELECT 1 FROM subscriptions WHERE customer_id=? LIMIT 1", (int(customer_id),)).fetchone() is not None


def send(customer_ids: Iterable[int], payload: dict, *, webpush=None) -> dict:
    """Push one payload ({title, body, url, tag}) to every device of these customers."""
    k = keys()
    if k is None:
        return {"sent": 0, "failed": 0, "removed": 0, "skipped": "no VAPID keys"}
    if webpush is None:
        from pywebpush import webpush  # noqa: PLC0415 - only needed when sending
    ids = [int(i) for i in customer_ids]
    if not ids:
        return {"sent": 0, "failed": 0, "removed": 0}
    with closing(_db()) as c:
        rows = c.execute(f"SELECT * FROM subscriptions WHERE customer_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    sent = failed = removed = 0
    body = json.dumps(payload)
    for r in rows:
        try:
            webpush(subscription_info={"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}},
                    data=body, vapid_private_key=k["private"], vapid_claims={"sub": k["subject"]}, ttl=12 * 3600)
            sent += 1
            with closing(_db()) as c:
                c.execute("UPDATE subscriptions SET last_sent_at=? WHERE endpoint=?", (datetime.now(timezone.utc).isoformat(), r["endpoint"]))
                c.commit()
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):        # the browser dropped this subscription
                with closing(_db()) as c:
                    c.execute("DELETE FROM subscriptions WHERE endpoint=?", (r["endpoint"],))
                    c.commit()
                removed += 1
            else:
                failed += 1
    return {"sent": sent, "failed": failed, "removed": removed}


def register(app) -> None:
    import secrets as _secrets

    from flask import abort, jsonify, request, session

    def _cid() -> int | None:
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        try:
            return int(c["id"]) if c and c.get("id") is not None else None
        except (TypeError, ValueError):
            return None

    def _csrf_ok() -> bool:
        sent = (request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and _secrets.compare_digest(sent, want))

    @app.get("/push/key")
    def push_key():
        k = keys()
        return jsonify({"enabled": k is not None, "key": k["public"] if k else None})

    @app.post("/push/subscribe")
    def push_subscribe():
        if not _csrf_ok():
            abort(400)
        cid = _cid()
        if cid is None:
            return jsonify({"ok": False, "reason": "login_required"}), 401
        if not enabled():
            return jsonify({"ok": False, "reason": "push_off"}), 200
        try:
            subscribe(cid, request.get_json(silent=True) or {})
        except ValueError:
            abort(400)
        return jsonify({"ok": True})

    @app.post("/push/unsubscribe")
    def push_unsubscribe():
        if not _csrf_ok():
            abort(400)
        cid = _cid()
        if cid is None:
            return jsonify({"ok": False, "reason": "login_required"}), 401
        unsubscribe(cid, (request.get_json(silent=True) or {}).get("endpoint"))
        return jsonify({"ok": True})

    @app.context_processor
    def _push_ctx():
        k = keys()
        return {"lo_push": {"enabled": k is not None, "key": k["public"] if k else ""}}

    @app.cli.command("push-keys")
    def push_keys_cmd():
        """Print a new VAPID key pair for LO_VAPID_PUBLIC_KEY / LO_VAPID_PRIVATE_KEY."""
        import base64

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        priv = key.private_numbers().private_value.to_bytes(32, "big")
        pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
        print(f"LO_VAPID_PUBLIC_KEY={b64(pub)}")
        print(f"LO_VAPID_PRIVATE_KEY={b64(priv)}")
        print("LO_VAPID_SUBJECT=mailto:support@lottosonline.com")
