"""
Pre-launch tests for the cart: rendering, add-to-cart while logged in, the
logged-out capture-and-resume path, invalid payload handling, clearing, and the
checkout auth gate. Real payment/checkout against the CRM is staging-only (see
docs/PRELAUNCH_TEST_PLAN.md).
"""

from __future__ import annotations

import json

from crm_api import CRMClient

VALID_ADD = {
    "product_code": "PB_SINGLE",
    "game_code": "powerball",
    "game_name": "PowerBall",
    "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}]),
    "options_json": "{}",
}


def test_cart_page_renders_empty(client, stub_crm):
    resp = client.get("/cart")
    assert resp.status_code == 200


def test_cart_add_logged_in(client, stub_crm):
    resp = client.post("/cart/add", data=VALID_ADD)
    assert resp.status_code == 302
    with client.session_transaction() as s:
        items = s.get("cart_items")
        assert isinstance(items, list) and len(items) == 1
        assert items[0]["product_code"] == "PB_SINGLE"
        assert items[0]["lines"]


def test_cart_add_logged_out_captures_pending_and_redirects_to_login(anon_client, stub_crm):
    resp = anon_client.post("/cart/add", data=VALID_ADD)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with anon_client.session_transaction() as s:
        pending = s.get("pending_cart_add")
        assert isinstance(pending, dict)
        assert pending["product_code"] == "PB_SINGLE"


def test_login_completes_pending_cart_add(anon_client, stub_crm):
    anon_client.post("/cart/add", data=VALID_ADD)
    resp = anon_client.post("/login", data={"email": "test@example.com", "password": "pw"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/cart")
    with anon_client.session_transaction() as s:
        items = s.get("cart_items")
        assert isinstance(items, list) and len(items) == 1
        assert not s.get("pending_cart_add")


def test_cart_renders_numbers_as_compact_tiles(client, stub_crm):
    """Big round balls pushed each line down the page; a line now reads as the
    same small tiles the picker collapses to, main and bonus apart."""
    client.post("/cart/add", data=VALID_ADD)
    resp = client.get("/cart")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert html.count('class="leCartNum"') >= 5
    assert 'class="leCartNum leCartNumBonus"' in html


def test_cart_add_missing_product_rejected(client, stub_crm):
    resp = client.post("/cart/add", data={**VALID_ADD, "product_code": ""})
    assert resp.status_code == 400


def test_cart_add_empty_lines_bounces_back(client, stub_crm):
    resp = client.post("/cart/add", data={**VALID_ADD, "lines_json": "[]"})
    # No valid lines: flash a warning and bounce back to the picker.
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_cart_clear(client, stub_crm):
    client.post("/cart/add", data=VALID_ADD)
    resp = client.post("/cart/clear")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_cart_reuse_last_purchase_restores_items(client, stub_crm):
    with client.session_transaction() as s:
        s["last_purchase_cart"] = {
            "items": [
                {
                    "kind": "single",
                    "product_code": "PB_SINGLE",
                    "lines": [{"main": "1,2,3,4,5", "power": "6"}],
                    "options": {},
                    "game_code": "powerball",
                    "game_name": "PowerBall",
                }
            ],
            "order_id": "9",
            "saved_at": "2026-01-01T00:00:00+00:00",
        }
    resp = client.post("/cart/reuse-last-purchase")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert s.get("cart_items")


def test_cart_reuse_last_purchase_without_history_warns(client, stub_crm):
    resp = client.post("/cart/reuse-last-purchase")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_checkout_requires_login(anon_client, stub_crm):
    resp = anon_client.post("/checkout", data={})
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_cart_add_rejects_more_than_50_lines(client, stub_crm):
    lines = [{"main": "1,2,3,4,5", "power": "6"}] * 51
    resp = client.post("/cart/add", data={**VALID_ADD, "lines_json": json.dumps(lines)})
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_cart_add_lotto_ie_requires_two_lines(client, stub_crm):
    resp = client.post(
        "/cart/add",
        data={
            **VALID_ADD,
            "game_code": "lotto-ie",
            "lines_json": json.dumps([{"main": "1,2,3,4,5,6"}]),
        },
    )
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_cart_confirm_total_never_below_crm_quote(client, stub_crm, monkeypatch):
    """Regression: the cart used to subtract a website-derived upsell discount
    from a quote total that already reflected the CRM's discount, showing an
    affordable "Funds Required" figure that checkout then rejected with a 402.
    The confirm figure must equal what the CRM will debit (EUR 25.67 here, not
    the 23.10 the local 10% tier would produce)."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {
            "quote": {
                "currency": "EUR",
                "subtotal_cents": 2567,
                "total_cents": 2567,
                # Base item qualifies the cart for an upsell tier; the upsell item
                # is quoted at full price, i.e. the CRM applied no discount.
                "items": [
                    {"item_total_in_customer_cents": 2000},
                    {"item_total_in_customer_cents": 567},
                ],
            },
        },
    )
    # Wallet can cover 25.67, so the page renders Confirm Order rather than a top-up.
    monkeypatch.setattr(
        CRMClient,
        "wallet",
        lambda self, token: {"wallet": {"currency": "EUR", "balance_cents": 3000, "available_balance_cents": 3000}},
    )

    client.post("/cart/add", data=VALID_ADD)
    client.post(
        "/cart/add-upsell",
        data={
            "product_code": "PB_SINGLE",
            "game_code": "powerball",
            "game_name": "PowerBall",
            "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}]),
            "offer_rule_id": "12",
        },
    )

    resp = client.get("/cart")
    assert resp.status_code == 200
    body = " ".join(resp.get_data(as_text=True).split())
    # The confirm button must quote the CRM's payable amount, not a locally
    # discounted one (the website tier would have shaved 15% off the upsell).
    assert "Funds Required: EUR 25.67" in body
    assert "24.92" not in body
    # No savings line the CRM has not actually applied.
    assert "% Offer" not in body
    assert "upsell discount" not in body


def test_checkout_402_shows_crm_amounts(client, stub_crm, monkeypatch):
    # A CRM 402 must surface the CRM's authoritative required/available amounts,
    # so a displayed-vs-spendable balance mismatch is visible to the customer.
    from crm_api import CRMError

    def fake_checkout(self, token, payload):
        raise CRMError(
            "CRM HTTP 402: insufficient balance",
            status_code=402,
            payload={"balance_cents": 2400, "required_cents": 2450, "currency": "EUR"},
        )

    monkeypatch.setattr(CRMClient, "checkout", fake_checkout)
    client.post("/cart/add", data=VALID_ADD)
    resp = client.post("/checkout", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "24.50" in body
    assert "24.00" in body


def test_checkout_fallback_does_not_spend_winnings_unasked(client, stub_crm, monkeypatch):
    """
    The fallback path used to send `use_wins: true` on every order, which
    spent customers' winnings without anyone being asked. The CRM preserves
    winnings by default so that cannot happen by accident, and sending the
    flag unconditionally overrode that.
    """
    captured = {}

    def fake_checkout(self, token, payload):
        captured.update(payload)
        return {"order_id": 7, "debited_cents": 500, "currency": "USD"}

    monkeypatch.setattr(CRMClient, "checkout", fake_checkout)
    client.post("/cart/add", data=VALID_ADD)
    resp = client.post("/checkout")
    assert resp.status_code == 302
    assert "/orders/7" in resp.headers["Location"]
    assert not captured.get("use_wins")
    assert captured.get("items")


def test_checkout_fallback_carries_an_authorization_the_customer_gave(
    client, stub_crm, monkeypatch
):
    """
    A choice made on the cart must survive the quote path failing, or the
    customer authorises winnings and is refused anyway.
    """
    captured = {}

    def fake_checkout(self, token, payload):
        captured.update(payload)
        return {"order_id": 8, "debited_cents": 500, "currency": "USD"}

    monkeypatch.setattr(CRMClient, "checkout", fake_checkout)
    client.post("/cart/add", data=VALID_ADD)
    client.post("/checkout", data={"use_wins": "1"})
    assert captured.get("use_wins") is True


# ── checkout upsells: the CRM must be told which offer to apply ────────────────

UPSELL_ADD = {
    "product_code": "PB_SINGLE",
    "game_code": "powerball",
    "game_name": "PowerBall",
    "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 3),
    "offer_rule_id": "7",
}


def test_adding_an_upsell_tells_the_crm_which_rule_to_apply(client, stub_crm):
    """The CRM only discounts an upsell if the quote carries its rule id, and it
    re-prices the same payload at submit. Without this the site shows a discount the
    CRM never applied and the order is refused over the price."""
    resp = client.post("/cart/add-upsell", data=UPSELL_ADD)
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert s.get("checkout_selected_checkout_offers") == ["7"]
        assert s["cart_items"][0]["offer_rule_id"] == "7"


def test_removing_the_upsell_withdraws_the_offer_selection(client, stub_crm):
    """A rule id left behind after its item is gone fails the other way: the CRM
    insists on an offered item the cart no longer holds and refuses to quote at all."""
    client.post("/cart/add-upsell", data=UPSELL_ADD)
    with client.session_transaction() as s:
        assert s.get("checkout_selected_checkout_offers") == ["7"]
    resp = client.post("/cart/remove-item", data={"item_idx": "0"})
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("checkout_selected_checkout_offers")


def test_an_upsell_with_no_crm_rule_carries_no_offer_selection(client, stub_crm):
    """Cards are built from the local catalogue, so some have no matching rule. Those
    must be added at full price rather than silently claiming a discount."""
    data = dict(UPSELL_ADD)
    data.pop("offer_rule_id")
    client.post("/cart/add-upsell", data=data)
    with client.session_transaction() as s:
        assert not s.get("checkout_selected_checkout_offers")
        assert s["cart_items"][0]["offer_rule_id"] is None


def test_a_forged_offer_rule_id_is_ignored(client, stub_crm):
    data = dict(UPSELL_ADD, offer_rule_id="7 OR 1=1")
    client.post("/cart/add-upsell", data=data)
    with client.session_transaction() as s:
        assert not s.get("checkout_selected_checkout_offers")
