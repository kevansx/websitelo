"""LOCAL PREVIEW ONLY: a stand-in CRM so the play, results, cart and account pages can be built and
reviewed before the LottosOnline brand's service key exists.

Switched on by CRM_FAKE=1 and refused unless WEBSITE_ENV=local, so it can never answer on staging or
production. It replaces CRMClient's public methods (the same seam the test suite stubs) with:

* the LottosOnline catalogue exactly as the CRM reply of 2 October 2026 lists it (crm-setup/): a base single-draw
  product per lottery, the multi-draw tier products with their locked prices, and the three weekly syndicate
  subscriptions, in the store API's shape (single_products, list-shaped line_schema);
* subscriptions: join (POST /checkout with a syndicate item), list, pause, resume and cancel, held in memory;
* any email + password logs in as a demo customer with a EUR 50 wallet; nothing is saved anywhere.
  Test login used for browser checks: demo@lottosonline.local / preview-only-1 (local fake only).

Jackpots and draw results come from the preview cache (tools/seed_preview_cache.py), which holds real
CRM data captured on 1 October 2026.
"""
from __future__ import annotations

import os

import lo_lotteries

# group name -> (count, min, max), main group first. German Lotto is 6 from 1-49 only: the Superzahl is drawn,
# not picked (CRM reply, 2 October 2026).
SCHEMAS: dict[str, dict[str, tuple[int, int, int]]] = {
    "powerball": {"main": (5, 1, 69), "powerball": (1, 1, 26)},
    "megamillions": {"main": (5, 1, 70), "megaball": (1, 1, 24)},
    "superlotto-plus-ca-us": {"main": (5, 1, 47), "mega": (1, 1, 27)},
    "lotto-america": {"main": (5, 1, 52), "star": (1, 1, 10)},
    "millionaire-for-life": {"main": (5, 1, 58), "millionaire": (1, 1, 5)},
    "euromillions-at": {"main": (5, 1, 50), "stars": (2, 1, 12)},
    "eurojackpot": {"main": (5, 1, 50), "euro": (2, 1, 12)},
    "superenalotto": {"main": (6, 1, 90)},
    "el-gordo-primitiva": {"main": (5, 1, 54), "key": (1, 0, 9)},
    "la-primitiva": {"main": (6, 1, 49)},
    "bonoloto": {"main": (6, 1, 49)},
    "lotto-6aus49": {"main": (6, 1, 49)},
    "lotto-fr": {"main": (5, 1, 49), "chance": (1, 1, 10)},
    "lotto-ie": {"main": (6, 1, 47)},
    "thunderball": {"main": (5, 1, 39), "thunderball": (1, 1, 14)},
    "powerball-au": {"main": (7, 1, 35), "powerball": (1, 1, 20)},
    "oz-lotto-au": {"main": (7, 1, 47)},
    "sat-lotto-au": {"main": (6, 1, 45)},
    "weekday-windfall-au": {"main": (6, 1, 45)},
}

# The catalogue in crm-setup/2026-10-02 CRM reply - Lottos Online setup.md (locked EUR cents):
# base code, game, price per line, "send at least", {tier suffix: price}, weekly subscription price or None.
CATALOGUE = [
    ("LO-USPOW", "powerball", 520, 3, {"1W": 468, "3W": 442, "5W": 416}, 390),
    ("LO-USMEG", "megamillions", 1000, 1, {"4": 900, "8": 850}, 500),
    ("LO-USCAL", "superlotto-plus-ca-us", 220, 5, {"4": 198, "8": 187, "16": 176}, None),
    ("LO-USLOT", "lotto-america", 260, 5, {"1W": 234, "3W": 221, "5W": 208}, None),
    ("LO-USMIL", "millionaire-for-life", 830, 1, {}, None),
    ("LO-EUEUR", "euromillions-at", 590, 3, {"4": 531, "8": 502, "16": 472}, 295),
    ("LO-EUJAC", "eurojackpot", 550, 3, {"4": 495, "8": 468, "16": 440}, None),
    ("LO-ITSUP", "superenalotto", 290, 4, {"4": 261, "8": 247, "16": 232}, None),
    ("LO-ESELG", "el-gordo-primitiva", 440, 3, {"4": 396, "8": 374, "16": 352}, None),
    ("LO-ESLAP", "la-primitiva", 300, 4, {"1W": 270, "3W": 255, "5W": 240}, None),
    ("LO-ESBON", "bonoloto", 150, 5, {}, None),
    ("LO-DELOT", "lotto-6aus49", 290, 5, {"4": 261, "8": 247, "16": 232}, None),
    ("LO-FRLOT", "lotto-fr", 600, 3, {}, None),
    ("LO-IELOT", "lotto-ie", 550, 3, {"4": 495, "8": 468, "16": 440}, None),
    ("LO-UKTHU", "thunderball", 350, 3, {"4": 315, "8": 298, "16": 280}, None),
    ("LO-AUPOW", "powerball-au", 170, 5, {"4": 153, "8": 145, "16": 136}, None),
    ("LO-AULOT", "oz-lotto-au", 240, 5, {"4": 216, "8": 204, "16": 192}, None),
    ("LO-AUTAT", "sat-lotto-au", 130, 5, {"4": 117, "8": 111, "16": 104}, None),
    ("LO-AUMON", "weekday-windfall-au", 100, 5, {"1W": 90, "3W": 85, "5W": 80}, None),
]
# The three Australian bundle games: the store API returns default_lines 1 (the site sends 5).
AU_BOARDS = {"powerball-au", "sat-lotto-au", "weekday-windfall-au"}

DEMO_CUSTOMER = {
    "id": 900001, "email": "demo@lottosonline.local", "first_name": "Demo", "last_name": "Customer",
    "email_verified": True, "currency": "EUR", "country": "IE", "street": "1 Demo Street", "city": "Dublin",
    "postal_code": "D01", "phone": "+353 1 000 0000",
}


def _schema(game_code: str) -> list[dict]:
    return [{"name": k, "count": c, "min": lo, "max": hi}
            for k, (c, lo, hi) in SCHEMAS.get(game_code, {"main": (6, 1, 49)}).items()]


def _price(cents: int) -> dict:
    return {"price_in_base_cents": cents, "base_currency": "EUR",
            "prices_by_currency": {"EUR": {"amount_cents": cents, "is_base": True, "is_manual": True}}}


def _game(lot) -> dict:
    """One game in the store API's shape, with its base, multi-draw tier and subscription products."""
    row = next(r for r in CATALOGUE if r[1] == lot.game_code)
    code, game_code, cents, min_lines, tiers, sub = row
    base = {"code": code, "product_code": code, "game_code": game_code, "product_type": "single",
            "name": f"{lot.name} single draw", **_price(cents), "line_schema": _schema(game_code), "addons": [],
            "available_ticket_modes": ["standard"], "multi_draw_enabled": False, "subscription_enabled": False,
            "website_default": True, "website_enabled": True, "is_active": True,
            "default_lines": 1 if game_code in AU_BOARDS else min_lines}
    tier_products = []
    for suffix, t_cents in tiers.items():
        t_code = f"{code}-{suffix}"
        # still lists "standard": the site's guard is what stops a tier being sold as a one-draw ticket
        tier_products.append({**base, "code": t_code, "product_code": t_code, "name": f"{lot.name} multi-draw {suffix}",
                              **_price(t_cents), "available_ticket_modes": ["standard", "multi_draw"],
                              "multi_draw_enabled": True, "website_default": False})
    subs = []
    if sub:
        s_code = f"{code}-W"
        subs.append({"code": s_code, "product_code": s_code, "game_code": game_code, "product_type": "syndicate",
                     "name": f"{lot.name} weekly syndicate", "available_ticket_modes": ["subscription"],
                     "subscription_enabled": True, "subscription_standard_price_cents": sub,
                     # deliberately not the weekly price: the site must bill subscription_standard_price_cents
                     **_price(9999), "lines_per_share": 10, "shares_total": 40, "billing_period": "weekly",
                     "line_schema": _schema(game_code), "website_enabled": True, "is_active": True})
    return {"game_code": game_code, "game_name": lot.name, "products": [base, *tier_products, *subs],
            "single_products": [base, *tier_products], "single_product": base, "syndicate_products": subs}


def enabled() -> bool:
    import sys
    # Never under the test suite: the tests stub the CRM themselves and a local .env must not override them.
    if "pytest" in sys.modules:
        return False
    return os.environ.get("CRM_FAKE", "").strip() == "1"


def install() -> None:
    if not enabled():
        return
    if (os.environ.get("WEBSITE_ENV") or "").strip().lower() != "local":
        raise RuntimeError("CRM_FAKE=1 is only allowed with WEBSITE_ENV=local")
    from crm_api import CRMClient, CRMError

    games = [_game(l) for l in lo_lotteries.LOTTERIES if l.sells]
    by_code = {g["game_code"]: g for g in games}
    products = [p for g in games for p in g["products"]]
    wallet = {"wallet": {"currency": "EUR", "balance_cents": 5000, "withdrawable_cents": 0,
                         "added_funds_cents": 5000, "winnings_cents": 0}}

    def store_game(self, game_code, *a, **k):
        g = by_code.get(game_code)
        if not g:
            raise CRMError("CRM HTTP 404: not found", status_code=404)
        return {"game": g}

    answers = {
        "health": {"ok": True},
        "countries": {"countries": [{"iso2": c, "name": n, "active": 1} for c, n in (
            ("AE", "United Arab Emirates"), ("AU", "Australia"), ("BR", "Brazil"), ("CA", "Canada"),
            ("CO", "Colombia"), ("IE", "Ireland"), ("IN", "India"), ("ID", "Indonesia"), ("IT", "Italy"),
            ("PH", "Philippines"), ("SA", "Saudi Arabia"), ("ZA", "South Africa"), ("GB", "United Kingdom"))]},
        "store_games": {"games": games},
        "store_products": {"products": products},
        "bundle": {"bundle": None},
        "auth_login": {"token": "demo-token", "customer": DEMO_CUSTOMER},
        "auth_register": {"token": "demo-token", "customer": DEMO_CUSTOMER},
        "auth_me": {"customer": DEMO_CUSTOMER},
        "customer_me": {"customer": DEMO_CUSTOMER},
        "customer_update": {"customer": DEMO_CUSTOMER},
        "password_reset_request": {"success": True},
        "password_reset_confirm": {"success": True},
        "auth_set_password_check": {"valid": False},
        "auth_legacy_signup_check": {"success": False, "reason": "unknown"},
        "auth_email_verification_request": {"success": True},
        "auth_email_verification_confirm": {"success": True},
        "wallet": wallet,
        "wallet_transactions": {"transactions": []},
        "wallet_cards": {"cards": []},
        "winnings_tickets": {"tickets": []},
        "orders": {"orders": []},
        "legacy_orders": {"success": True, "page": 1, "per_page": 25, "total": 0, "orders": []},
        "marketing_banners": {"banners": []},
        "marketing_events": {"ok": True},
    }

    def make(payload):
        def fake(self, *a, **k):
            return payload
        return fake

    # The engine also calls two endpoints through _request directly. Answer them from the real CRM data
    # captured on 1 October (inventory/), with draw times rolled forward so countdowns stay live.
    import json
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    inv = Path(__file__).resolve().parent.parent / "inventory"
    jackpots = json.loads((inv / "crm_global_jackpots.json").read_text()) if (inv / "crm_global_jackpots.json").exists() else []
    draws = json.loads((inv / "crm_draw_results_sample.json").read_text()) if (inv / "crm_draw_results_sample.json").exists() else []
    real_request = CRMClient._request

    def fake_request(self, method, path, *a, **k):
        if path.startswith("/api/v1/jackpots"):
            now = datetime.now(timezone.utc)
            out = []
            for j in jackpots:
                j = dict(j)
                nd = j.get("next_draw_utc")
                if nd:
                    t = datetime.fromisoformat(nd.replace("Z", "")).replace(tzinfo=timezone.utc)
                    while t < now:
                        t += timedelta(days=7)
                    j["cutoff_at_utc"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
                    j["remaining_seconds"] = int((t - now).total_seconds())
                out.append(j)
            return {"jackpots": out}
        if path.startswith("/api/v1/draw-results"):
            params = k.get("params") or {}
            code = params.get("game_code")
            rows = [d for d in draws if not code or d.get("game_code") == code]
            return {"draws": rows, "draw_results": rows, "next_cursor": None, "has_more": False}
        if path.startswith("/api/v1/marketing/incentives/grant-free-ticket"):
            return {"success": True, "promo_order_id": 990001}
        if path.rstrip("/") == "/api/v1/store/games":
            return {"games": games}
        if path.startswith("/api/v1/store/games/"):
            g = by_code.get(path.rsplit("/", 1)[-1])
            if g:
                return {"game": g}
        if path.startswith("/api/v1/store/products"):
            return {"products": products}
        raise CRMError(f"CRM HTTP 404: fake CRM has no {path}", status_code=404)

    CRMClient._request = fake_request

    for name, payload in answers.items():
        if hasattr(CRMClient, name):
            setattr(CRMClient, name, make(payload))
    CRMClient.store_game = store_game

    import itertools
    import lo_store

    by_product = {p["product_code"]: p for p in products}
    per_week = {"megamillions": 2, "superlotto-plus-ca-us": 2, "euromillions-at": 2, "eurojackpot": 2, "lotto-6aus49": 2,
                "lotto-ie": 2, "superenalotto": 4, "thunderball": 4, "el-gordo-primitiva": 1, "powerball-au": 1,
                "oz-lotto-au": 1, "sat-lotto-au": 1, "powerball": 3, "lotto-america": 3, "la-primitiva": 3,
                "weekday-windfall-au": 3, "bonoloto": 6, "millionaire-for-life": 7, "lotto-fr": 3}

    def _draws(it: dict, prod: dict) -> int:
        if str(it.get("ticket_mode") or "standard") != "multi_draw":
            return 1
        lock = lo_store.tier_draw_weeks(prod)
        if lock is None or int(it.get("draw_weeks") or 0) != lock:
            # the real CRM rejects any other draw_weeks for a tier product
            raise CRMError(f"CRM HTTP 400: draw_weeks must be {lock} for {prod.get('code')}", status_code=400)
        return lock * per_week.get(prod.get("game_code"), 1)

    def checkout_quote(self, payload, *a, **k):
        # Line price x lines x draws in the schedule, as the CRM charges. A tier sent as "standard" is priced as one
        # draw at its discounted price, exactly the hole the site's guard closes.
        out, total = [], 0
        for it in (payload or {}).get("items") or []:
            prod = by_product.get(it.get("product_code")) or {}
            lines = max(len(it.get("lines") or []), 1)
            cents = int(prod.get("price_in_base_cents") or 300) * lines * int(it.get("quantity") or 1) * _draws(it, prod)
            total += cents
            out.append({"product_code": it.get("product_code"), "quantity": it.get("quantity") or 1,
                        "item_total_in_customer_cents": cents})
        return {"quote_id": 1, "quote": {"currency": "EUR", "items": out,
                                         "subtotal_in_customer_cents": total, "total_in_customer_cents": total}}

    CRMClient.checkout_quote = checkout_quote

    # ------------------------------------------------------------------ orders (so packs and order pages work)
    order_ids = itertools.count(700001)
    placed: list[dict] = []

    def checkout_submit(self, token, *, quote_id=None, use_wins=False, **k):
        oid = next(order_ids)
        placed.insert(0, {"id": oid, "status": "paid", "created_at": datetime.now(timezone.utc).isoformat(), "tickets": []})
        return {"order_id": oid, "status": "paid"}

    def orders(self, token, *, page=1, per_page=25):
        return {"orders": placed if page == 1 else [], "total": len(placed)}

    def order(self, token, order_id):
        o = next((x for x in placed if x["id"] == int(order_id)), None)
        if o is None:
            raise CRMError("CRM HTTP 404: not found", status_code=404)
        return {"order": o}

    CRMClient.checkout_submit = checkout_submit
    CRMClient.orders = orders
    CRMClient.order = order

    # ------------------------------------------------------------------ syndicate subscriptions
    subs: list[dict] = []
    sub_ids = itertools.count(5001)

    def checkout(self, token, payload, *a, **k):
        item = ((payload or {}).get("items") or [{}])[0]
        prod = by_product.get(item.get("product_code")) or {}
        if item.get("kind") != "syndicate" or item.get("ticket_mode") != "subscription":
            return {"order_id": next(order_ids), "status": "paid"}
        if lo_store.product_kind(prod) != "subscription":
            raise CRMError("CRM HTTP 400: not a subscription product", status_code=400)
        if not payload.get("saved_card_id"):
            raise CRMError("CRM HTTP 400: saved_card_id required", status_code=400)
        now = datetime.now(timezone.utc)
        qty = int(item.get("shares") or 1)
        amount = int(prod["subscription_standard_price_cents"]) * qty
        sub = {"id": next(sub_ids), "status": "active", "product_code": prod["code"], "product_name": prod["name"],
               "game_code": prod["game_code"], "quantity": qty, "next_amount_cents": amount, "currency": "EUR",
               "next_charge_at": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"), "period_number": 1,
               "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "paused_until": None,
               "email": DEMO_CUSTOMER["email"]}
        subs.append(sub)
        return {"order_id": next(order_ids), "status": "paid", "subscription": sub}

    def subscriptions(self, token=None, **k):
        return {"subscriptions": [dict(x) for x in subs]}

    def _sub(sid):
        s_ = next((x for x in subs if str(x["id"]) == str(sid)), None)
        if s_ is None:
            raise CRMError("CRM HTTP 404: not found", status_code=404)
        return s_

    def subscription_pause(self, token, sid, weeks=None):
        s_ = _sub(sid)
        if s_["status"] != "active":
            raise CRMError("CRM HTTP 409: only an active membership can pause", status_code=409)
        w = int(weeks or 4)
        if not 1 <= w <= 12:
            raise CRMError("CRM HTTP 400: weeks must be 1-12", status_code=400)
        s_["status"] = "paused"
        s_["paused_until"] = (datetime.now(timezone.utc) + timedelta(weeks=w)).strftime("%Y-%m-%dT%H:%M:%SZ")
        s_["next_charge_at"] = s_["paused_until"]
        return {"subscription": dict(s_)}

    def subscription_resume(self, token, sid):
        s_ = _sub(sid)
        s_["status"], s_["paused_until"] = "active", None
        s_["next_charge_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"subscription": dict(s_)}

    def subscription_cancel(self, token, sid, payload=None):
        s_ = _sub(sid)
        s_["status"], s_["next_charge_at"] = "cancelled", None
        return {"subscription": dict(s_)}

    def subscriptions_due(self, *, next_charge_after=None, next_charge_before=None):
        return {"subscriptions": [dict(x) for x in subs if x["status"] in ("active", "past_due")]}

    CRMClient.checkout = checkout
    CRMClient.subscriptions = subscriptions
    CRMClient.subscription_pause = subscription_pause
    CRMClient.subscription_resume = subscription_resume
    CRMClient.subscription_cancel = subscription_cancel
    CRMClient.subscriptions_due = subscriptions_due
    # one saved card, so the membership join can be walked through locally
    CRMClient.wallet_cards = lambda self, *a, **k: {"cards": [{"id": 42, "brand": "Visa", "last4": "4242", "status": "active",
                                                                "exp_month": 12, "exp_year": 2030}]}
