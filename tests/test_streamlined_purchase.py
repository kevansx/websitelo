"""
The purchase flow in as few steps as possible (Joey, 15 Oct 2026).

Reported on www1: he picked numbers, pressed Play, was asked to sign in, opened
a free account from the login page, and landed on his account page with the
order gone. Then the cart sent him to a separate Add Funds page to pick an
amount, when all he wanted was to pay for the order.

Now: a ticket picked before signing in or signing up is waiting in the cart
afterwards, and the cart takes the card payment for the order itself and
places the order once it clears.
"""

from __future__ import annotations

import json

from test_cart_checkout import VALID_ADD
from test_checkout_winnings import _cart, offer, quote, submits, wallet  # noqa: F401 - fixtures
from test_offers import catalog, serve_bundle  # noqa: F401 - fixtures

NEW_ACCOUNT = {
    "title": "Mr",
    "first_name": "Test",
    "last_name": "User",
    "email": "new@example.com",
    "password": "Str0ngPassw0rd!",
    "currency": "USD",
    "accept_terms": "1",
}


# --- signing up mid-purchase ---


def test_the_login_page_open_account_button_keeps_the_order(anon_client, stub_crm):
    login_url = anon_client.post("/cart/add", data=VALID_ADD).headers["Location"]
    body = anon_client.get(login_url).get_data(as_text=True)
    assert 'href="/create-account?next=/cart"' in body


def test_a_new_account_lands_on_the_cart_with_the_ticket_in_it(anon_client, stub_crm):
    anon_client.post("/cart/add", data=VALID_ADD)
    resp = anon_client.post("/create-account", data={**NEW_ACCOUNT, "next": "/cart"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/cart")
    with anon_client.session_transaction() as s:
        items = s.get("cart_items")
        assert isinstance(items, list) and len(items) == 1
        assert items[0]["product_code"] == "PB_SINGLE"
        assert not s.get("pending_cart_add")


def test_the_ticket_waits_even_when_the_account_link_carried_no_next(anon_client, stub_crm):
    """The header's own Open Account link has no `next`. They still came to buy."""
    anon_client.post("/cart/add", data=VALID_ADD)
    resp = anon_client.post("/create-account", data=NEW_ACCOUNT)
    assert resp.headers["Location"].endswith("/cart")


def test_an_account_opened_with_nothing_picked_still_goes_to_the_account(anon_client, stub_crm):
    resp = anon_client.post("/create-account", data=NEW_ACCOUNT)
    assert resp.headers["Location"].endswith("/account")


def test_a_multi_draw_choice_is_remembered_through_sign_in(anon_client, stub_crm):
    """Lost, it came back as a one-draw ticket at the multi-draw price."""
    anon_client.post("/cart/add", data={**VALID_ADD, "ticket_mode": "multi_draw", "draw_weeks": "4"})
    with anon_client.session_transaction() as s:
        assert s["pending_cart_add"]["ticket_mode"] == "multi_draw"
        assert s["pending_cart_add"]["draw_weeks"] == "4"


def test_a_ticket_with_no_numbers_is_not_put_in_the_cart(anon_client, stub_crm):
    anon_client.post("/cart/add", data={**VALID_ADD, "lines_json": json.dumps([{"main": "", "power": ""}])})
    resp = anon_client.post("/login", data={"email": "test@example.com", "password": "pw"})
    assert resp.headers["Location"].endswith("/account")
    with anon_client.session_transaction() as s:
        assert not s.get("cart_items")


# --- paying for the order on the cart ---


def test_an_empty_wallet_pays_for_the_order_by_card_on_the_cart(client, offer, quote, wallet, submits):
    wallet["added_cents"] = 0
    wallet["wins_cents"] = 0
    body = _cart(client).get_data(as_text=True)
    assert 'class="leCartCardPay"' in body
    assert 'action="/wallet/add-funds"' in body and 'method="post"' in body
    assert 'name="amount" value="5.80"' in body, "exactly the order, no amount to pick"
    assert 'name="next" value="/checkout/after-topup"' in body, "the order is placed once the payment clears"
    assert "add-funds?next=" not in body, "no detour through the Add Funds page"
    assert "Pay USD 5.80 by Card" in body
    assert "left over" not in body


def test_a_small_shortfall_says_where_the_minimum_payment_goes(client, offer, quote, wallet, submits):
    """507 held against a 580 cart: 73c short, 5.00 is the smallest card payment."""
    wallet["wins_cents"] = 0
    body = _cart(client).get_data(as_text=True)
    assert 'name="amount" value="5.00"' in body
    assert "USD 4.27 left over stays in your account" in body


def test_the_cart_asks_for_country_and_address_only_when_we_hold_neither(client, offer, quote, wallet, submits):
    """Some processors will not open a payment page without them, and there is no later page to ask on."""
    wallet["added_cents"] = 0
    wallet["wins_cents"] = 0
    _cart(client)
    with client.session_transaction() as s:
        s["customer"] = {"id": 1, "email": "test@example.com"}
    body = client.get("/cart").get_data(as_text=True)
    form = body[body.index('class="leCartCardPay"'):]
    form = form[: form.index("</form>")]
    assert 'name="country"' in form
    assert 'name="billing_street"' in form

    resp = client.post(
        "/wallet/add-funds",
        data={"amount": "5.80", "next": "/checkout/after-topup", "return_to": "cart"},
    )
    assert resp.headers["Location"].endswith("/cart"), "back to the cart's own fields, not the Add Funds page"


def test_a_payment_that_cannot_start_returns_to_the_cart(client, stub_crm):
    resp = client.post(
        "/wallet/add-funds",
        data={"amount": "1.00", "next": "/checkout/after-topup", "return_to": "cart"},
    )
    assert resp.headers["Location"].endswith("/cart")


def test_add_funds_from_the_account_page_still_returns_to_add_funds(client, stub_crm):
    resp = client.post("/wallet/add-funds", data={"amount": "1.00"})
    assert "/wallet/add-funds" in resp.headers["Location"]
