"""LOCAL PREVIEW ONLY: a stand-in CRM so the play, results, cart and account pages can be built and
reviewed before the LottosOnline brand's service key exists.

Switched on by CRM_FAKE=1 and refused unless WEBSITE_ENV=local, so it can never answer on staging or
production. It replaces CRMClient's public methods (the same seam the test suite stubs) with:

* the 19 LottosOnline lotteries with their real number formats (main + bonus groups);
* placeholder EUR ticket prices, labelled as such on screen by the engine's normal price display
  (the four the old home page showed are the old prices: Powerball 5.20, Mega Millions 10.00,
  EuroJackpot 5.50, SuperLotto Plus 2.20; the rest are round placeholders);
* any email + password logs in as a demo customer with a EUR 50 wallet; nothing is saved anywhere.
  Test login used for browser checks: demo@lottosonline.local / preview-only-1 (local fake only).

Jackpots and draw results come from the preview cache (tools/seed_preview_cache.py), which holds real
CRM data captured on 1 October 2026.
"""
from __future__ import annotations

import os

import lo_lotteries

# group name -> (count, min, max), main group first
SCHEMAS: dict[str, dict[str, tuple[int, int, int]]] = {
    "powerball": {"main": (5, 1, 69), "powerball": (1, 1, 26)},
    "megamillions": {"main": (5, 1, 70), "megaball": (1, 1, 24)},
    "superlotto-plus-ca-us": {"main": (5, 1, 47), "mega": (1, 1, 27)},
    "lotto-america": {"main": (5, 1, 52), "star": (1, 1, 10)},
    "millionaire-for-life-us": {"main": (5, 1, 58), "millionaire": (1, 1, 5)},
    "euromillions": {"main": (5, 1, 50), "stars": (2, 1, 12)},
    "eurojackpot": {"main": (5, 1, 50), "euro": (2, 1, 12)},
    "superenalotto": {"main": (6, 1, 90)},
    "el-gordo-primitiva": {"main": (5, 1, 54), "key": (1, 0, 9)},
    "la-primitiva-es": {"main": (6, 1, 49)},
    "bonoloto": {"main": (6, 1, 49)},
    "lotto-6aus49": {"main": (6, 1, 49), "super": (1, 0, 9)},
    "lotto-fr": {"main": (5, 1, 49), "chance": (1, 1, 10)},
    "lotto-ie": {"main": (6, 1, 47)},
    "thunderball": {"main": (5, 1, 39), "thunderball": (1, 1, 14)},
    "powerball-au": {"main": (7, 1, 35), "powerball": (1, 1, 20)},
    "oz-lotto-au": {"main": (7, 1, 47)},
    "sat-lotto-au": {"main": (6, 1, 45)},
    "weekday-windfall-au": {"main": (6, 1, 45)},
}

PRICE_CENTS: dict[str, int] = {
    "powerball": 520, "megamillions": 1000, "eurojackpot": 550, "superlotto-plus-ca-us": 220,
    "lotto-america": 300, "millionaire-for-life-us": 500, "euromillions": 450, "superenalotto": 300,
    "el-gordo-primitiva": 300, "la-primitiva-es": 250, "bonoloto": 200, "lotto-6aus49": 350,
    "lotto-fr": 350, "lotto-ie": 400, "thunderball": 300, "powerball-au": 300, "oz-lotto-au": 350,
    "sat-lotto-au": 250, "weekday-windfall-au": 200,
}

DEMO_CUSTOMER = {
    "id": 900001, "email": "demo@lottosonline.local", "first_name": "Demo", "last_name": "Customer",
    "email_verified": True, "currency": "EUR", "country": "IE", "street": "1 Demo Street", "city": "Dublin",
    "postal_code": "D01", "phone": "+353 1 000 0000",
}


def _product(lot) -> dict:
    code = f"LO-{lot.legacy_code.upper()}-1"
    schema = {k: {"count": c, "min": lo, "max": hi} for k, (c, lo, hi) in SCHEMAS.get(lot.game_code, {"main": (6, 1, 49)}).items()}
    cents = PRICE_CENTS.get(lot.game_code, 300)
    return {
        "code": code, "product_code": code, "game_code": lot.game_code, "product_type": "single",
        "name": f"{lot.name} ticket", "price_in_base_cents": cents, "base_currency": "EUR",
        "prices_by_currency": {"EUR": {"amount_cents": cents, "is_base": True, "is_manual": True}},
        "line_schema": schema, "addons": [], "multi_draw_enabled": True,
        "available_ticket_modes": ["standard", "multi_draw"], "is_active": True, "website_enabled": True,
    }


def _game(lot) -> dict:
    return {"game_code": lot.game_code, "game_name": lot.name, "products": [_product(lot)]}


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
        "checkout_quote": {"quote": {"currency": "EUR", "subtotal_cents": 0, "items": []}},
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
