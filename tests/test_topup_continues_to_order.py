"""
A top-up made to pay for a cart has to finish the order.

Production, 2026-09-14. Customer A1007986 opened the call-centre promo, built a
cart quoted at EUR 25.00, was sent to add funds, and paid CCM intent 3589. The
CRM credited the wallet at 17:27:37. The website then showed them a page that
said "Payment successful" above a Continue button, and that was the end of it:
no order was ever placed, and at 17:29 the cart sent them back to the payment
page for the same EUR 25.00 they had just paid.

Two separate faults, and this file holds both to the fix.

The money was taken and nothing was bought, because the last step of a paid-for
purchase was a button. "Payment successful" is a sentence a customer reads as
"done", and on a phone returning from the processor it was also the easiest
thing on the screen to close.

Then the cart asked again. It could not tell "we checked, and they are short"
apart from "we could not check", and it kept the shortfall it had worked out
before they paid.
"""

from __future__ import annotations

import json
import logging

import pytest

from crm_api import CRMClient, CRMError

from test_offers import _bundle, catalog, serve_bundle  # noqa: F401 - fixtures


SLUG = "PB_WelcomeDB"
ONE_LINE = json.dumps([{"main": "1,2,3,4,5", "power": 6}])
# The quote they were actually shown: EUR 30.00 less EUR 5.00.
PAYABLE_CENTS = 2500
INTENT = "3589"


@pytest.fixture
def promo_offer(serve_bundle):  # noqa: F811
    serve_bundle(
        _bundle(SLUG, [{"product_code": "PSX-W", "quantity": 1}], locked_price_base_cents=PAYABLE_CENTS,
                base_currency="EUR")
    )


@pytest.fixture
def wallet(monkeypatch):
    """
    The CRM wallet, with the balance a test can move.

    Topping up credits added funds, which is the pot checkout spends from, so
    these tests keep the whole balance there unless they say otherwise.
    """
    state = {
        "balance_cents": 0,
        "available_balance_cents": 0,
        "wins_balance_cents": 0,
        "reserved_added_funds_cents": 0,
        "currency": "EUR",
        "fails": False,
    }

    def fake_wallet(self, token, *a, **kw):
        if state["fails"]:
            raise CRMError("CRM HTTP 503: wallet unavailable", status_code=503)
        added = state["balance_cents"] - state["wins_balance_cents"]
        return {
            "wallet": {
                "currency": state["currency"],
                "balance_cents": state["balance_cents"],
                "added_funds_balance_cents": max(0, added),
                "wins_balance_cents": state["wins_balance_cents"],
                "reserved_added_funds_cents": state["reserved_added_funds_cents"],
                "reserved_wins_cents": 0,
                "available_balance_cents": state["available_balance_cents"],
                "withdrawable_cents": state["balance_cents"],
            }
        }

    monkeypatch.setattr(CRMClient, "wallet", fake_wallet)
    return state


@pytest.fixture
def quote(monkeypatch):
    def fake_quote(self, payload, *a, **kw):
        return {
            "quote_id": 991,
            "quote": {"currency": "EUR", "total_cents": PAYABLE_CENTS, "total_base_cents": PAYABLE_CENTS,
                      "items": [{"product_code": "PSX-W", "item_total_in_customer_cents": PAYABLE_CENTS,
                                 "draws_count": 6}]},
        }

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)


@pytest.fixture
def orders_placed(monkeypatch):
    """Records every order the website actually submitted to the CRM."""
    placed: list[dict] = []

    def fake_submit(self, token, *a, **kw):
        placed.append({"args": a, "kwargs": dict(kw)})
        return {"order_id": 4762, "quote_id": 991, "currency": "EUR", "total_cents": PAYABLE_CENTS}

    monkeypatch.setattr(CRMClient, "checkout_submit", fake_submit)
    monkeypatch.setattr(CRMClient, "checkout", fake_submit)
    return placed


def _build_the_cart(client):
    """The promo click, the numbers, and Buy - up to the cart."""
    client.get(
        f"/offer/{SLUG}?src=callcentre&cmp=callcentre-{SLUG}"
        f"&tid=c4_fxh0b1ji8bpsxd&intent=lifecycle"
    )
    client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})
    return client.get("/cart")


def _pay(client, wallet):
    """The processor credits the wallet and sends the browser back."""
    wallet["balance_cents"] = PAYABLE_CENTS
    wallet["available_balance_cents"] = PAYABLE_CENTS
    return client.get(f"/wallet/topup/success?next=/checkout/after-topup&intent_id={INTENT}")


def _asks_for_more_money(body: str) -> bool:
    """
    Whether the cart is sending them off to pay.

    Not merely whether "add-funds" appears: every page carries a wallet link in
    its navigation, and the thing that matters is the checkout top-up route
    with an amount attached - the URL A1007986 was handed twice.

    The shortfall notice names the amounts rather than saying "insufficient
    wallet balance", so this matches the instruction that closes it instead of
    the wording of the sum.
    """
    return "add-funds?next=" in body or "Use the payment button" in body


# --- the order gets placed ---


def test_paying_for_a_cart_continues_to_the_order_without_a_click(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """
    The whole bug in one test. Intent 3589 was paid, the wallet was credited,
    and the customer was shown a button instead of an order.
    """
    _build_the_cart(client)
    landed = _pay(client, wallet)

    assert landed.status_code == 302
    assert landed.headers["Location"].endswith("/checkout/after-topup")


def test_the_page_that_needed_a_tap_is_no_longer_in_the_way(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """
    Server-side, because the step it replaces needed a tap on a phone browser
    coming back from the processor. A redirect asks nothing of the browser, the
    customer, or whether their JavaScript ran.
    """
    _build_the_cart(client)
    landed = _pay(client, wallet)
    body = landed.get_data(as_text=True)

    assert "Payment successful" not in body
    assert "Continue" not in body


def test_the_order_is_actually_submitted_at_the_end_of_it(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """Following the redirect the way a browser does reaches a placed order."""
    _build_the_cart(client)
    after = client.get(_pay(client, wallet).headers["Location"])

    assert after.status_code == 200
    # The page that finishes the job posts to /checkout on load.
    assert 'action="/checkout"' in after.get_data(as_text=True)

    client.post("/checkout")

    assert len(orders_placed) == 1


def test_topping_up_the_wallet_on_its_own_still_confirms_and_stops(
    client, stub_crm, wallet, orders_placed
):
    """
    Someone adding money to their wallet for its own sake is not mid-purchase
    and has nothing to be carried on to. They still get told it worked.
    """
    landed = client.get(f"/wallet/topup/success?intent_id={INTENT}")
    body = landed.get_data(as_text=True)

    assert landed.status_code == 200
    assert "Payment successful" in body
    assert orders_placed == []


def test_an_empty_cart_does_not_send_them_into_a_checkout(
    client, stub_crm, wallet, orders_placed
):
    """
    If the cart went away between paying and returning, continuing would land
    them on an error. Confirm the payment instead and leave them somewhere
    sensible.
    """
    landed = client.get(f"/wallet/topup/success?next=/checkout/after-topup&intent_id={INTENT}")

    assert landed.status_code == 200
    assert "Payment successful" in landed.get_data(as_text=True)


def test_continuing_is_recorded_so_the_hop_can_be_seen_in_the_log(
    client, stub_crm, promo_offer, quote, wallet, orders_placed, caplog
):
    """
    The production trace showed `/wallet/topup/success` answering 200 and then
    nothing at all, and there was no way to tell a customer who abandoned it
    from one the site failed to carry forward.
    """
    _build_the_cart(client)

    with caplog.at_level(logging.INFO):
        _pay(client, wallet)

    assert "funded a pending cart" in caplog.text
    assert INTENT in caplog.text


# --- and the cart stops asking for money already paid ---


def test_the_cart_does_not_ask_again_for_money_already_in_the_wallet(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """
    At 17:29 the cart sent them to `/wallet/add-funds` still asking for the
    EUR 25.00 they had paid two minutes earlier.
    """
    _build_the_cart(client)
    _pay(client, wallet)

    back_on_the_cart = client.get("/cart").get_data(as_text=True)

    assert not _asks_for_more_money(back_on_the_cart)


def test_a_paid_top_up_does_not_leave_its_shortfall_behind_in_the_session(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """
    The figures describe a wallet that no longer exists. Left in the session
    they are what the cart fell back on, and they always said EUR 25.00 short.
    """
    _build_the_cart(client)

    with client.session_transaction() as s:
        assert s["pending_checkout"]["amount_cents"] == PAYABLE_CENTS

    _pay(client, wallet)

    with client.session_transaction() as s:
        pending = s.get("pending_checkout") or {}
        assert "amount_cents" not in pending
        assert "required_cents" not in pending


def test_a_wallet_we_cannot_read_is_not_treated_as_an_empty_one(
    client, stub_crm, promo_offer, quote, wallet, orders_placed, caplog
):
    """
    "They are short" and "we could not find out" need opposite responses, and
    only the first justifies asking anyone for money. If we cannot tell,
    checkout refuses at submit and routes them properly - it does not invent a
    shortfall from figures it worked out earlier.
    """
    _build_the_cart(client)
    _pay(client, wallet)
    wallet["fails"] = True

    with caplog.at_level(logging.WARNING):
        page = client.get("/cart").get_data(as_text=True)

    assert not _asks_for_more_money(page)
    assert "could not read the wallet balance" in caplog.text


def test_a_genuine_shortfall_still_routes_them_to_add_funds(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """The fix must not stop an empty wallet asking to be filled."""
    page = _build_the_cart(client).get_data(as_text=True)

    assert _asks_for_more_money(page)


def test_a_shortfall_records_both_balances_so_the_next_one_is_answerable(
    client, stub_crm, promo_offer, quote, wallet, orders_placed, caplog
):
    """
    A settled top-up whose reservation has not been released yet reads as an
    empty wallet. Which figure we believed is the entire question when a
    customer says the money is already there, and it was not written down
    anywhere.
    """
    wallet["balance_cents"] = PAYABLE_CENTS
    wallet["reserved_added_funds_cents"] = PAYABLE_CENTS

    with caplog.at_level(logging.INFO):
        _build_the_cart(client)

    assert "cart deposits do not cover it" in caplog.text
    assert f"required={PAYABLE_CENTS}" in caplog.text
    assert "added=0" in caplog.text


def test_paying_only_part_of_it_still_asks_for_the_rest(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    _build_the_cart(client)
    wallet["balance_cents"] = 1000
    wallet["available_balance_cents"] = 1000
    client.get(f"/wallet/topup/success?next=/checkout/after-topup&intent_id={INTENT}")

    assert _asks_for_more_money(client.get("/cart").get_data(as_text=True))


# --- the session that has to survive the processor ---


def test_the_session_cookie_survives_a_return_from_the_payment_processor():
    """
    The customer had no password - they arrived on a set-password link - so a
    session lost on the way back from the processor cannot be rebuilt by
    logging in. `Strict` would drop the cookie on exactly the top-level GET
    the processor sends them back with, and strand them for good.
    """
    from app import app as flask_app

    assert flask_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert flask_app.config["SESSION_COOKIE_HTTPONLY"] is True


def test_a_set_password_token_is_still_there_after_the_payment_return(
    client, stub_crm, promo_offer, quote, wallet, orders_placed
):
    """
    Same journey as A1007986: arrived with `spt`, paid, came back. If the
    token were lost they could neither check out nor sign in again.
    """
    client.get(f"/offer/{SLUG}?spt=abcdef0123456789abcdef&intent=lifecycle")
    _build_the_cart(client)
    _pay(client, wallet)

    with client.session_transaction() as s:
        assert s.get("set_password_token") == "abcdef0123456789abcdef"
