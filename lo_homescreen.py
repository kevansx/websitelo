"""Add to Home Screen (Android + iPhone) and the free Australia Saturday Lotto ticket for doing it.

* Installable web app: /manifest.webmanifest (name, icons, standalone display, start_url with
  ?source=homescreen) and /sw.js, a service worker that deliberately caches NOTHING (it exists only so
  browsers offer installation; every request still goes to the network, so a deploy can never be hidden behind
  a stale cache).
* The offer: the first time a logged-in customer opens LottosOnline from the home-screen icon, they get one
  free quick-pick line in the next Australia Saturday Lotto draw. The browser reports that it is running as
  the installed app (display-mode: standalone / navigator.standalone) and calls POST /homescreen/claim.
  One per customer, enforced twice: a local claims file and the CRM's idempotency key
  ("homescreen-<customer id>") on POST /api/v1/marketing/incentives/grant-free-ticket.
* The claim needs the Saturday Lotto product code on the LottosOnline brand: LO_HOMESCREEN_PRODUCT_CODE, or the
  first sellable product of game sat-lotto-au in the store. LO_HOMESCREEN_OFFER=0 switches the offer off (the
  install prompt then shows without the incentive).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import lo_store
from flask import Response, abort, jsonify, render_template, request, send_from_directory, session

GAME_CODE = "sat-lotto-au"
DATA = Path(__file__).resolve().parent / "data" / "homescreen_claims.json"
_lock = threading.Lock()


def offer_enabled() -> bool:
    return (os.environ.get("LO_HOMESCREEN_OFFER", "1").strip() != "0")


def _load() -> dict:
    try:
        return json.loads(DATA.read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(DATA)


def _customer_id() -> int | None:
    c = session.get("customer") if isinstance(session.get("customer"), dict) else None
    try:
        return int(c["id"]) if c and c.get("id") is not None else None
    except (TypeError, ValueError):
        return None


def claim_record(customer_id: int | None) -> dict | None:
    if customer_id is None:
        return None
    return _load().get(str(customer_id))


def register(app) -> None:
    static_img = Path(__file__).resolve().parent / "static" / "brands" / "lottosonline" / "img"

    @app.get("/manifest.webmanifest")
    def web_manifest():
        data = {
            "name": "LottosOnline",
            "short_name": "LottosOnline",
            "description": "Buy official lottery tickets online for the world's biggest jackpots.",
            "id": "/?source=homescreen",
            "start_url": "/?source=homescreen",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#582178",
            "theme_color": "#582178",
            "icons": [
                {"src": "/static/brands/lottosonline/img/app-icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/brands/lottosonline/img/app-icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "/static/brands/lottosonline/img/app-icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
                {"src": "/static/brands/lottosonline/img/app-icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        }
        resp = Response(json.dumps(data), mimetype="application/manifest+json")
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @app.get("/sw.js")
    def service_worker():
        # Network only: no caching, so a deploy is never hidden behind stale files.
        js = ("self.addEventListener('install', function () { self.skipWaiting(); });\n"
              "self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });\n"
              "self.addEventListener('fetch', function () { /* network only */ });\n")
        resp = Response(js, mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    def _product_and_schema():
        # Through lo_store: the real CRM lists products under single_products with a list-shaped line_schema.
        code = (os.environ.get("LO_HOMESCREEN_PRODUCT_CODE") or "").strip() or None
        eng = app.config.get("LO_ENGINE") or {}
        try:
            games = eng["store_games_cached"]()
        except Exception:
            games = []
        p = lo_store.find_product(games, game_code=GAME_CODE, code=code)
        if p and lo_store.schema_groups(p.get("line_schema")):
            return lo_store.product_code(p), p["line_schema"]
        return code, [{"name": "main", "count": 6, "min": 1, "max": 45}]

    @app.get("/homescreen/status")
    def homescreen_status():
        cid = _customer_id()
        rec = claim_record(cid)
        return jsonify({"offer": offer_enabled(), "logged_in": cid is not None,
                        "claimed": bool(rec and rec.get("status") == "granted"),
                        "pending": bool(rec and rec.get("status") == "pending")})

    @app.post("/homescreen/claim")
    def homescreen_claim():
        if not offer_enabled():
            return jsonify({"ok": False, "reason": "offer_off"}), 200
        sent = (request.headers.get("X-CSRF-Token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        if not sent or not want or sent != want:
            abort(400)
        if (request.headers.get("X-Display-Mode") or "") != "standalone":
            return jsonify({"ok": False, "reason": "not_installed"}), 200
        cid = _customer_id()
        if cid is None:
            return jsonify({"ok": False, "reason": "login_required"}), 200
        with _lock:
            claims = _load()
            rec = claims.get(str(cid))
            if rec and rec.get("status") == "granted":
                return jsonify({"ok": True, "already": True})
            product_code, schema = _product_and_schema()
            rec = {"status": "pending", "at": datetime.now(timezone.utc).isoformat(), "product_code": product_code}
            if product_code:
                try:
                    eng = app.config["LO_ENGINE"]
                    crm = eng["get_crm"]()
                    res = crm._request("POST", "/api/v1/marketing/incentives/grant-free-ticket", service_key=True, json={
                        "customer_id": cid, "product_code": product_code, "lines": [lo_store.quick_pick(schema)],
                        "incentive_id": "homescreen-install", "reason": "Added LottosOnline to the home screen",
                        "idempotency_key": f"homescreen-{cid}",
                    })
                    if isinstance(res, dict) and res.get("success"):
                        rec.update(status="granted", promo_order_id=res.get("promo_order_id"))
                    else:
                        rec["error"] = str(res)[:300]
                except Exception as e:  # noqa: BLE001 - recorded, granted by hand if the CRM refused
                    rec["error"] = str(e)[:300]
            else:
                rec["error"] = "no Saturday Lotto product on the brand"
            claims[str(cid)] = rec
            _save(claims)
        if rec["status"] == "granted":
            return jsonify({"ok": True})
        app.logger.warning("homescreen claim pending for customer %s: %s", cid, rec.get("error"))
        return jsonify({"ok": True, "pending": True})

    @app.get("/home-screen-offer")
    def homescreen_offer_terms():
        return render_template("lo/homescreen_terms.html", noindex="noindex, follow")

    @app.context_processor
    def _homescreen_ctx():
        cid = _customer_id()
        rec = claim_record(cid) if cid is not None else None
        return {"lo_homescreen": {"offer": offer_enabled(), "claimed": bool(rec and rec.get("status") == "granted"),
                                  "pending": bool(rec and rec.get("status") == "pending")}}
