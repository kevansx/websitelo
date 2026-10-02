"""
Customer-facing prices must come from the CRM's per-currency retail prices
(`prices_by_currency[<display currency>].amount_cents`), never from
`price_in_base_cents`, which is an amount in a different currency. Quoting a
base amount under the customer's currency symbol shows a price the cart and
checkout will not honour.

Also covers the API v58 requirement that the customer's country is persisted on
the CRM record, since Website Processor Rules route wallet payments on it.
"""

from __future__ import annotations

import copy
import json

import time

from crm_api import CRMClient, CRMError
from crm_cache import CRMCache

VALID_ADD = {
    "product_code": "PB_SINGLE",
    "game_code": "powerball",
    "game_name": "PowerBall",
    "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}]),
    "options_json": "{}",
}


def _game_with_eur_price(base_game: dict) -> dict:
    """Product priced 5.00 in its USD base currency and 8.00 for EUR customers."""
    game = copy.deepcopy(base_game)
    game["products"][0]["prices_by_currency"] = {
        "EUR": {"amount_cents": 800, "currency": "EUR"},
        "USD": {"amount_cents": 500, "currency": "USD"},
    }
    return game


def _use_eur_customer(monkeypatch, stub_crm, client=None) -> None:
    stub_crm["wallet"]["wallet"] = {
        "currency": "EUR",
        "balance_cents": 5000,
        "available_balance_cents": 5000,
    }
    # The customer record wins over the wallet when resolving display currency,
    # so a EUR customer has to be one on both.
    for key in ("customer_me", "auth_me", "auth_login", "auth_register"):
        if isinstance(stub_crm.get(key), dict) and isinstance(stub_crm[key].get("customer"), dict):
            stub_crm[key]["customer"] = {**stub_crm[key]["customer"], "currency": "EUR"}
    if client is not None:
        with client.session_transaction() as s:
            s["customer"] = {**(s.get("customer") or {}), "currency": "EUR"}
    game = _game_with_eur_price(stub_crm["store_games"]["games"][0])
    stub_crm["store_games"]["games"] = [game]
    stub_crm["store_game"]["game"] = game
    stub_crm["store_products"]["products"] = game["products"]

    # The catalogue used for cart pricing is served from the SQLite cache, not
    # the CRM client, so seed it through a read-only stub.
    real_get_state = CRMCache.get_state

    def fake_get_state(self, k, default=None):
        if k == "store_games_json":
            return json.dumps({"games": [game]})
        if k == "store_games_fetched_at":
            return str(int(time.time()))
        return real_get_state(self, k, default)

    monkeypatch.setattr(CRMCache, "get_state", fake_get_state)
    # A quote with no usable totals forces the cart's cached-price fallback,
    # which is the path that used to display base-currency amounts.
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {"quote": {"currency": "EUR", "items": []}},
    )


def test_cart_fallback_price_uses_display_currency_not_base(client, stub_crm, monkeypatch):
    _use_eur_customer(monkeypatch, stub_crm, client)
    client.post("/cart/add", data=VALID_ADD)
    resp = client.get("/cart")
    assert resp.status_code == 200
    body = " ".join(resp.get_data(as_text=True).split())
    assert "8.00" in body
    assert "5.00" not in body


def test_upsell_estimate_uses_display_currency_not_base(client, stub_crm, monkeypatch):
    _use_eur_customer(monkeypatch, stub_crm, client)
    resp = client.post(
        "/cart/add-upsell",
        data={
            "product_code": "PB_SINGLE",
            "game_code": "powerball",
            "game_name": "PowerBall",
            "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 2),
        },
    )
    assert resp.status_code == 302
    with client.session_transaction() as s:
        # Two lines at the EUR retail price, not the USD base price.
        assert s["cart_items"][0]["estimated_item_total_cents"] == 1600


def test_play_picker_prices_carry_the_display_currency_map(client, stub_crm, monkeypatch):
    _use_eur_customer(monkeypatch, stub_crm)
    resp = client.get("/lottery-tickets/us-powerball")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '"prices_by_currency"' in body
    assert '"amount_cents": 800' in body or '"amount_cents":800' in body


# ── line-count rules come from the product, not from hardcoded numbers ────────


def _seed_catalog(monkeypatch, game: dict) -> None:
    real_get_state = CRMCache.get_state

    def fake_get_state(self, k, default=None):
        if k == "store_games_json":
            return json.dumps({"games": [game]})
        if k == "store_games_fetched_at":
            return str(int(time.time()))
        return real_get_state(self, k, default)

    monkeypatch.setattr(CRMCache, "get_state", fake_get_state)


def test_bundle_priced_game_requires_whole_blocks(client, stub_crm, monkeypatch):
    """A non-partial bundle product only sells in multiples of bundle_min_lines;
    anything else is a 400 (INVALID_LINES_COUNT) from the CRM."""
    game = copy.deepcopy(stub_crm["store_games"]["games"][0])
    game["products"][0].update({"pricing_kind": "bundle", "bundle_min_lines": 4})
    _seed_catalog(monkeypatch, game)

    resp = client.post(
        "/cart/add",
        data={**VALID_ADD, "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 3)},
    )
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")

    resp = client.post(
        "/cart/add",
        data={**VALID_ADD, "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 4)},
    )
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert len(s.get("cart_items") or []) == 1


def test_partial_bundle_game_sells_a_single_board(client, stub_crm, monkeypatch):
    game = copy.deepcopy(stub_crm["store_games"]["games"][0])
    game["products"][0].update(
        {
            "pricing_kind": "bundle",
            "bundle_min_lines": 4,
            "partial_bundle_sales_enabled": True,
            "sale_unit_lines": 1,
        }
    )
    _seed_catalog(monkeypatch, game)

    resp = client.post("/cart/add", data=VALID_ADD)
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert len(s.get("cart_items") or []) == 1


def test_line_cap_follows_the_product(client, stub_crm, monkeypatch):
    game = copy.deepcopy(stub_crm["store_games"]["games"][0])
    game["products"][0]["website_max_lines_per_item"] = 10
    _seed_catalog(monkeypatch, game)

    resp = client.post(
        "/cart/add",
        data={**VALID_ADD, "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 11)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "maximum of 10 lines" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("cart_items")


# ── API v58: Website Processor Rules match on the persisted CRM country ────────


def test_register_persists_the_selected_country(anon_client, stub_crm, monkeypatch):
    """Without a saved country, processor rules fall through to No Match and the
    customer's first top-up can be refused outright."""
    captured: dict = {}

    def fake_register(self, payload):
        captured.update(payload)
        return stub_crm["auth_register"]

    monkeypatch.setattr(CRMClient, "auth_register", fake_register)
    monkeypatch.setattr(CRMCache, "is_country_active", lambda self, iso2: True)
    monkeypatch.setattr(CRMCache, "is_country_blocked_for_website", lambda self, iso2: False)
    resp = anon_client.post(
        "/create-account",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "new@example.com",
            "password": "Password123!",
            "country": "US",
            "accept_terms": "1",
        },
    )
    assert resp.status_code == 302
    assert captured.get("country") == "US"


def test_topup_init_sends_the_routing_country(client, stub_crm, monkeypatch):
    """The hosted-only flow collects no billing address, so the intent itself has
    to carry the country the CRM routes on."""
    captured: list[dict] = []

    def fake_init(self, token, payload):
        captured.append(payload)
        return stub_crm["wallet_topup_init"]

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)
    with client.session_transaction() as s:
        s["customer"] = {**stub_crm["customer_me"]["customer"], "country": "CA"}
    resp = client.post("/wallet/add-funds", data={"amount": "10", "payment_flow": "hpp"})
    assert resp.status_code in (302, 303)
    assert captured, "top-up init was not called"
    assert captured[0].get("country") == "CA"


def test_routes_exhausted_is_explained_not_retried(client, stub_crm, monkeypatch):
    """PAYMENT_ROUTES_EXHAUSTED means no processor serves this country; telling
    the customer to try again just loops them."""

    def fake_init(self, token, payload):
        raise CRMError(
            "No eligible website payment processor matched this customer.",
            status_code=422,
            payload={
                "success": False,
                "error": "No eligible website payment processor matched this customer.",
                "error_code": "PAYMENT_ROUTES_EXHAUSTED",
            },
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)
    resp = client.post(
        "/wallet/add-funds",
        data={"amount": "10", "payment_flow": "hpp"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "not available for your country" in body
    assert "contact support" in body.lower()
