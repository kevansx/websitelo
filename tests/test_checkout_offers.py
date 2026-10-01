"""
Checkout offers (upsell discounts).

The CRM owns offer pricing: its rules hold the cart-value thresholds, it names
the discount, and it re-prices the same cart again at submit. So the website may
only display a saving the quote evidences, must ask for the offer in a form the
rules can match, and must recover rather than dead-end when the CRM refuses a
selection.
"""

from __future__ import annotations

import json

from crm_api import CRMClient, CRMError

BASE_ADD = {
    "product_code": "PB_SINGLE",
    "game_code": "powerball",
    "game_name": "PowerBall",
    "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 3),
    "options_json": "{}",
}

UPSELL_ADD = {
    "product_code": "PB_SINGLE",
    "game_code": "powerball",
    "game_name": "PowerBall",
    "lines_json": json.dumps([{"main": "1,2,3,4,5", "power": "6"}] * 3),
    "offer_rule_id": "7",
}


def _quote(**overrides):
    quote = {
        "contract_version": "mm_offers_quote_v5",
        "currency": "EUR",
        "subtotal_in_customer_cents": 3000,
        "discount_in_customer_cents": 300,
        "total_in_customer_cents": 2700,
        "base_currency": "EUR",
        "subtotal_base_cents": 3000,
        "discount_base_cents": 300,
        "total_base_cents": 2700,
        "discount_breakdown": [
            {
                "source_type": "checkout_offer_rule",
                "source_id": 7,
                "amount_in_customer_cents": 300,
                "amount_cents": 300,
            }
        ],
        "lines": [
            {"line_total_in_customer_cents": 1500, "discount_in_customer_cents": 0},
            {"line_total_in_customer_cents": 1200, "discount_in_customer_cents": 300, "applied_mm_offer_rule_id": 7},
        ],
    }
    quote.update(overrides)
    return quote


def test_cart_shows_the_discount_the_crm_applied(client, stub_crm, monkeypatch):
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {"quote": _quote()},
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet",
        lambda self, token: {"wallet": {"currency": "EUR", "balance_cents": 9000, "available_balance_cents": 9000}},
    )
    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/add-upsell", data=UPSELL_ADD)

    resp = client.get("/cart")
    assert resp.status_code == 200
    body = " ".join(resp.get_data(as_text=True).split())
    # The CRM's 3.00 saving, and its total, not a locally derived pair.
    assert "10% Offer" in body
    assert "- EUR 3.00" in body
    assert "EUR 27.00" in body


def test_no_discount_is_shown_when_the_crm_applied_none(client, stub_crm, monkeypatch):
    """Regression: the cart used to pick 10/15/20% off a local ladder, so an
    upsell the CRM quoted at full price still advertised a saving — and the order
    was then refused over the price."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {
            "quote": _quote(
                discount_in_customer_cents=0,
                discount_base_cents=0,
                total_in_customer_cents=3000,
                total_base_cents=3000,
                discount_breakdown=[],
                lines=[
                    {"line_total_in_customer_cents": 1500},
                    {"line_total_in_customer_cents": 1500},
                ],
            )
        },
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet",
        lambda self, token: {"wallet": {"currency": "EUR", "balance_cents": 9000, "available_balance_cents": 9000}},
    )
    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/add-upsell", data=UPSELL_ADD)

    resp = client.get("/cart")
    body = " ".join(resp.get_data(as_text=True).split())
    assert "Offer" not in body.replace("Offers", "")
    assert "Discount applied" not in body
    assert "EUR 30.00" in body


def test_upsell_card_is_cut_to_a_line_count_the_crm_has_a_rule_for(client, stub_crm, monkeypatch):
    """Rules are keyed to a locked line count, so a card offering a different
    quantity can never be discounted."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {
            "quote": _quote(),
            "eligible_checkout_offers": [
                {
                    "rule_id": 7,
                    "product_code": "PB_SINGLE",
                    "offered_quantity": 3,
                    "discount_percent": 10,
                }
            ],
        },
    )
    client.post("/cart/add", data=BASE_ADD)
    resp = client.get("/cart")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Cards are built locally at 3 or 4 lines; any 4-line card must have been
    # re-cut to the 3 lines the rule names, so no card offers 4 lines.
    assert "4 Lines" not in body
    if 'name="offer_rule_id"' in body:
        assert 'value="7"' in body


def test_website_bookkeeping_is_not_sent_to_the_crm(client, stub_crm, monkeypatch):
    """`options` is the field the CRM prices add-ons from, so the site's private
    upsell marker must not travel in it."""
    captured: list[dict] = []

    def fake_quote(self, payload, token=None, service_key=False):
        captured.append(payload)
        return {"quote": _quote()}

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/add-upsell", data=UPSELL_ADD)
    client.get("/cart")

    assert captured
    for item in captured[-1]["items"]:
        assert "offer_rule_id" not in item
        assert "estimated_item_total_cents" not in item
        assert "is_upsell" not in item
        assert "game_name" not in item
        assert "_is_upsell" not in (item.get("options") or {})
        assert item["lines"], "offers require explicit lines[] on every item"


def test_a_refused_offer_is_dropped_and_the_cart_re_quoted(client, stub_crm, monkeypatch):
    """The CRM refuses the whole quote when a selected offer doesn't match the
    cart. Showing an error banner leaves the customer with an unpriced cart."""
    calls: list[dict] = []

    def fake_quote(self, payload, token=None, service_key=False):
        calls.append(payload)
        if payload.get("selected_checkout_offers"):
            raise CRMError(
                "Selected offer requires PB_SINGLE with exactly 4 lines in cart",
                status_code=400,
                payload={"error": "Selected offer requires PB_SINGLE with exactly 4 lines in cart"},
            )
        return {"quote": _quote(discount_in_customer_cents=0, discount_breakdown=[], total_in_customer_cents=3000)}

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/add-upsell", data=UPSELL_ADD)

    resp = client.get("/cart")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "no longer applies" in body
    assert "EUR 30.00" in " ".join(body.split())
    assert len(calls) >= 2, "the cart should have been re-quoted without the offer"
    assert not calls[-1].get("selected_checkout_offers")
    with client.session_transaction() as s:
        assert not s.get("checkout_selected_checkout_offers")


def test_a_rejected_promo_is_cleared_and_the_cart_re_quoted(client, stub_crm, monkeypatch):
    def fake_quote(self, payload, token=None, service_key=False):
        if payload.get("promo_code"):
            raise CRMError(
                "Promo code is not valid",
                status_code=400,
                payload={"error_code": "promo_invalid", "error": "Promo code is not valid"},
            )
        return {"quote": _quote(discount_in_customer_cents=0, discount_breakdown=[], total_in_customer_cents=3000)}

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/apply-promo", data={"promo_code": "NOPE"})

    resp = client.get("/cart")
    assert resp.status_code == 200
    assert "valid for this order" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get("pc")


def test_the_site_does_not_ask_for_the_unimplemented_offers_flag(client, stub_crm, monkeypatch):
    """`include_eligible_checkout_offers` is not implemented in the CRM, so the
    site must not send it or depend on having asked."""
    captured: list[dict] = []

    def fake_quote(self, payload, token=None, service_key=False):
        captured.append(payload)
        return {"quote": _quote()}

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    client.post("/cart/add", data=BASE_ADD)
    client.get("/cart")
    client.post("/checkout")

    assert captured
    for payload in captured:
        assert "include_eligible_checkout_offers" not in payload


def test_an_offer_named_differently_still_binds_to_a_card(client, stub_crm, monkeypatch):
    """The rule id is the only thing that makes a discount happen, so it is read
    from whichever field carries it rather than one assumed key."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {
            "quote": _quote(),
            "eligible_offers": [
                {"id": 7, "product_code": "PB_SINGLE", "quantity": 3, "percent_off": 10}
            ],
        },
    )
    client.post("/cart/add", data=BASE_ADD)
    resp = client.get("/cart")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    if 'name="offer_rule_id"' in body:
        assert 'value="7"' in body


def test_a_discounted_cart_is_not_quietly_sold_at_full_price(client, stub_crm, monkeypatch):
    """`/api/v1/checkout` prices the cart itself. Falling back to it after a quote
    failure charged full price on an order that looked successful from both ends,
    which is how undiscounted sales went unnoticed."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        # A quote body with no id: /checkout/submit is unreachable.
        lambda self, payload, token=None, service_key=False: {"quote": _quote()},
    )

    def fail_direct(self, token, payload):
        raise AssertionError("a cart with an offer must not be priced without a quote")

    monkeypatch.setattr(CRMClient, "checkout", fail_direct)

    client.post("/cart/add", data=BASE_ADD)
    client.post("/cart/add-upsell", data=UPSELL_ADD)
    with client.session_transaction() as s:
        assert s.get("checkout_selected_checkout_offers"), "offer selection not captured"

    resp = client.post("/checkout", follow_redirects=True)
    assert resp.status_code == 200
    assert "couldn&#39;t confirm your discounted total" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert s.get("cart_items"), "the cart must survive a refused checkout"


def test_a_cart_with_no_discount_at_stake_still_completes(client, stub_crm, monkeypatch):
    """The fallback is a last resort, not a blocker: with no offer or promo the
    price is the same either way, so the sale goes through (and is logged)."""
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {"quote": _quote()},
    )
    monkeypatch.setattr(
        CRMClient,
        "checkout",
        lambda self, token, payload: {"order_id": 51, "currency": "EUR", "debited_cents": 3000},
    )

    client.post("/cart/add", data=BASE_ADD)
    resp = client.post("/checkout")
    assert resp.status_code == 302
    assert "/orders/51" in resp.headers["Location"]


def test_a_non_numeric_quote_id_is_submitted_as_issued(client, stub_crm, monkeypatch):
    """A quote id the site can't cast to int used to be discarded, which sent the
    order down the undiscounted path."""
    submitted: list[object] = []

    def fake_submit(self, token, quote_id, use_wins=False):
        submitted.append(quote_id)
        return {"order_id": 77, "currency": "EUR", "total_cents": 2700}

    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {"quote_id": "Q-2026-08", "quote": _quote()},
    )
    monkeypatch.setattr(CRMClient, "checkout_submit", fake_submit)
    monkeypatch.setattr(
        CRMClient,
        "checkout",
        lambda self, token, payload: (_ for _ in ()).throw(AssertionError("must use the quote")),
    )

    client.post("/cart/add", data=BASE_ADD)
    resp = client.post("/checkout")
    assert resp.status_code == 302
    assert submitted == ["Q-2026-08"]


def test_a_stale_quote_is_re_quoted_and_submitted(client, stub_crm, monkeypatch):
    """A 409 at submit means the CRM re-priced and the stored quote no longer
    matches; re-quoting completes the order instead of failing it."""
    submits: list[int] = []

    def fake_submit(self, token, quote_id, use_wins=False):
        submits.append(quote_id)
        if len(submits) == 1:
            raise CRMError(
                "Quote has changed; please re-quote",
                status_code=409,
                payload={"error": "Quote has changed; please re-quote"},
            )
        return {"order_id": 42, "currency": "EUR", "total_cents": 2700}

    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, token=None, service_key=False: {"quote_id": 99, "quote": _quote()},
    )
    monkeypatch.setattr(CRMClient, "checkout_submit", fake_submit)

    def fail_direct(self, token, payload):
        raise AssertionError("a recoverable 409 must not fall through to direct checkout")

    monkeypatch.setattr(CRMClient, "checkout", fail_direct)

    client.post("/cart/add", data=BASE_ADD)
    resp = client.post("/checkout")
    assert resp.status_code == 302
    assert "/orders/42" in resp.headers["Location"]
    assert len(submits) == 2
