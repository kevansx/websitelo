"""
Pricing a promo cart.

A bundle is sold at one locked price covering a run of draws. Everyone in this
file arrived from a campaign email quoting that price, so a cart that says
anything else costs the campaign its credibility rather than a few pence.

The CRM owns both numbers - the locked price and the draw run - and overwrites
any schedule the caller sends. The website's job is to ask it, and to never
answer from the catalog on its behalf.
"""

from __future__ import annotations

import json
import logging

import pytest

from crm_api import CRMClient, CRMError

from test_offers import _bundle, catalog, serve_bundle  # noqa: F401 - fixtures


SLUG = "PB_WelcomeDB"
ONE_LINE = json.dumps([{"main": "1,2,3,4,5", "power": 6}])
LOCKED_CENTS = 2250
CATALOG_UNIT_CENTS = 500

# The live fixture: PSX-W x 1, two weeks of Mon/Wed/Sat, six draws, locked at
# GBP 22.50. One board played across the run, not six boards.
ITEMS = [
    {
        "product_code": "PSX-W",
        "quantity": 1,
        "config_json": {
            "draw_weeks": 2,
            "draw_weekdays": ["monday", "wednesday", "saturday"],
            "draws_count": 6,
        },
    }
]


@pytest.fixture
def promo_offer(serve_bundle):  # noqa: F811
    serve_bundle(
        _bundle(
            SLUG,
            ITEMS,
            locked_price_base_cents=LOCKED_CENTS,
            locked_price_eur_cents=2580,
            base_currency="GBP",
        )
    )


@pytest.fixture
def crm_quote(monkeypatch):
    """
    The CRM's side of the contract: it applies the locked price and returns the
    run it computed from the bundle's own config.
    """
    calls: list[dict] = []

    def install(*, fails: bool = False):
        def fake_quote(self, payload, *a, **kw):
            calls.append({"payload": payload, "token": kw.get("token"), "service_key": kw.get("service_key")})
            if fails:
                raise CRMError("CRM HTTP 500", status_code=500)
            return {
                "quote_id": 991,
                "quote": {
                    "currency": "GBP",
                    "total_cents": LOCKED_CENTS,
                    "total_base_cents": LOCKED_CENTS,
                    "items": [
                        {
                            "product_code": "PSX-W",
                            "item_total_in_customer_cents": LOCKED_CENTS,
                            "draws_count": 6,
                            "schedule": {
                                "draw_weeks": 2,
                                "draw_weekdays": ["monday", "wednesday", "saturday"],
                                "draws_count": 6,
                            },
                        }
                    ],
                },
            }

        monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
        return calls

    return install


def _click_through_and_buy(client):
    """The promo click, the boards, and Buy."""
    client.get(
        f"/offer/{SLUG}?src=callcentre&cmp=callcentre-{SLUG}"
        f"&tid=c2_lou9sv44yj13ti&intent=lifecycle"
    )
    return client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})


def _only_lottery_item(call: dict) -> dict:
    return call["payload"]["items"][0]


# --- the reported bug ---


def test_a_signed_out_promo_cart_is_quoted_and_shows_the_locked_price(anon_client, promo_offer, crm_quote):
    """
    The bug as reported. A customer with no password reaches the cart signed
    out, which is the ordinary promo path. Quoting only when a bearer existed
    left the cart answering from the catalog: GBP 5.00, one draw, for a GBP
    22.50 six-draw offer.
    """
    calls = crm_quote()

    _click_through_and_buy(anon_client)
    body = anon_client.get("/cart").get_data(as_text=True)

    assert calls, "the signed-out cart never asked the CRM for a price"
    assert calls[-1]["service_key"] is True, "a signed-out quote needs the service key"
    assert "22.50" in body
    assert "5.00" not in body
    assert "Sign in to see your cart quote" not in body


def test_the_signed_out_quote_carries_the_bundle_and_the_campaign(anon_client, promo_offer, crm_quote):
    """Without the slug the CRM has no reason to apply the locked price at all."""
    calls = crm_quote()

    _click_through_and_buy(anon_client)
    anon_client.get("/cart")

    payload = calls[-1]["payload"]
    assert payload["bundle_slug"] == SLUG
    assert (payload.get("cmp"), payload.get("tid")) == (f"callcentre-{SLUG}", "c2_lou9sv44yj13ti")
    assert payload.get("intent") == "lifecycle"


def test_the_cart_shows_the_draw_run_the_quote_returned(anon_client, promo_offer, crm_quote):
    crm_quote()

    _click_through_and_buy(anon_client)
    body = anon_client.get("/cart").get_data(as_text=True)

    assert "6 draws" in body
    assert "Monday, Wednesday and Saturday" in body


def test_a_signed_in_promo_cart_prices_the_same(client, promo_offer, crm_quote):
    calls = crm_quote()

    _click_through_and_buy(client)
    body = client.get("/cart").get_data(as_text=True)

    assert calls[-1]["token"], "a signed-in quote should still send the bearer"
    assert "22.50" in body


# --- the website must not price a bundle itself ---


def test_a_bundle_cart_never_sends_its_own_draw_schedule(anon_client, promo_offer, crm_quote):
    """
    The CRM overwrites a bundle's schedule from its own config, so ours adds
    nothing - and a stray draw_weeks is a way to inflate a locked price.
    """
    calls = crm_quote()

    _click_through_and_buy(anon_client)
    with anon_client.session_transaction() as s:
        items = s["cart_items"]
        items[0]["draw_weeks"] = 52
        items[0]["draw_weekdays"] = ["monday"]
        s["cart_items"] = items

    body = anon_client.get("/cart").get_data(as_text=True)

    item = _only_lottery_item(calls[-1])
    assert "draw_weeks" not in item
    assert "draw_weekdays" not in item
    assert "22.50" in body


def test_a_failed_quote_falls_back_to_the_locked_price_not_the_catalog_price(anon_client, promo_offer, crm_quote):
    """
    A cart that cannot reach the CRM still must not quote the customer a figure
    the email never mentioned. The locked price is the one they were promised.
    """
    crm_quote(fails=True)

    _click_through_and_buy(anon_client)
    body = anon_client.get("/cart").get_data(as_text=True)

    assert "22.50" in body
    assert "5.00" not in body


def test_a_signed_out_quote_is_not_kept_for_checkout(anon_client, promo_offer, crm_quote):
    """
    An anonymous quote prices the cart for display. Keeping its id would offer
    submit a quote raised against no customer, and is also what would stop a
    sign-in from re-quoting.
    """
    crm_quote()

    _click_through_and_buy(anon_client)
    anon_client.get("/cart")

    with anon_client.session_transaction() as s:
        assert "checkout_quote_id" not in s


def test_signing_in_re_quotes_the_bundle(anon_client, promo_offer, crm_quote):
    calls = crm_quote()

    _click_through_and_buy(anon_client)
    anon_client.get("/cart")
    signed_out_calls = len(calls)

    with anon_client.session_transaction() as s:
        s["crm_token"] = "bearer-xyz"
    anon_client.get("/cart")

    assert len(calls) > signed_out_calls
    assert calls[-1]["token"] == "bearer-xyz"
    assert calls[-1]["payload"]["bundle_slug"] == SLUG


# --- ordinary carts are untouched ---


def test_a_plain_cart_still_asks_a_signed_out_customer_to_sign_in(anon_client, catalog, crm_quote):  # noqa: F811
    """
    Only a bundle cart gained a signed-out quote. A play-page cart has no locked
    price to protect and its own schedule to honour, so it waits for a sign-in
    exactly as before.
    """
    calls = crm_quote()

    with anon_client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "PSX-W", "lines": [{"main": "1,2,3,4,5", "power": 6}], "options": {}}]

    body = anon_client.get("/cart").get_data(as_text=True)

    assert calls == []
    assert "Sign in to see your cart quote" in body


def test_an_ordinary_cart_still_sends_the_schedule_it_chose(client, catalog, crm_quote):  # noqa: F811
    """Outside a bundle the website's schedule is the only one there is."""
    calls = crm_quote()

    with client.session_transaction() as s:
        s["cart_items"] = [
            {
                "kind": "single",
                "product_code": "PSX-W",
                "lines": [{"main": "1,2,3,4,5", "power": 6}],
                "options": {},
                "draw_weeks": 4,
                "draw_weekdays": ["monday"],
            }
        ]

    client.get("/cart")

    item = _only_lottery_item(calls[-1])
    assert item["draw_weeks"] == 4
    assert item["draw_weekdays"] == ["monday"]

# --- what the collapsed card says ---


def test_the_collapsed_cart_card_names_the_game_and_its_price(anon_client, promo_offer, crm_quote):  # noqa: F811
    """
    Most customers confirm the order without ever opening the card, so the
    collapsed row is the whole confirmation. It has to carry the game, its
    artwork, the run and the locked price on its own.
    """
    crm_quote()
    _click_through_and_buy(anon_client)

    body = anon_client.get("/cart").get_data(as_text=True)

    assert "leCartItemLogo" in body
    assert "lottery-assets/logo_large_round_uspow.png" in body
    assert "GBP 22.50" in body
    assert "6 draws" in body


def test_the_cart_headings_share_a_left_edge_with_the_cards(anon_client, promo_offer, crm_quote):  # noqa: F811
    """
    `.processOrderCopy` is a 315px column centred in a 400px panel, so headings
    set with it sit indented from the cards beneath them and the column reads as
    though it has two left edges.
    """
    crm_quote()
    _click_through_and_buy(anon_client)

    body = anon_client.get("/cart").get_data(as_text=True)

    head = body.split("Your cart details")[0].rsplit("Please Confirm Your Order", 1)[1]
    assert "processOrderCopy" not in head
    assert "leCartHeadTitle" in head


# --- the offer page's own label ---


def test_the_headline_is_the_offer_name_marketing_wrote(anon_client, serve_bundle):  # noqa: F811
    """
    The slug is an internal identifier. Printed as the headline it reads as a
    broken page to the one person guaranteed to read it, and it is not what the
    email that brought them here called the offer.
    """
    serve_bundle(
        _bundle(
            "welcome_to_lotto_express",
            [{"product_code": "PSX-W", "quantity": 1}],
            offer_name="Powerball 6 Draw Special",
            contents_description="Special 6 draw Powerball Offer 1 draw free",
        )
    )

    body = anon_client.get("/offer/welcome_to_lotto_express").get_data(as_text=True)
    headline = body.split('class="pageHeading leOfferTitle">')[1].split("</h1>")[0].strip()

    assert headline == "Powerball 6 Draw Special"
    assert "Special 6 draw Powerball Offer 1 draw free" in body


def test_a_bundle_with_no_offer_name_still_never_shows_its_slug(anon_client, serve_bundle):  # noqa: F811
    """`offer_name` is null when the offer row is missing (API 65)."""
    serve_bundle(_bundle("welcome_to_lotto_express", [{"product_code": "PSX-W", "quantity": 1}], offer_name=None, title=None))

    body = anon_client.get("/offer/welcome_to_lotto_express").get_data(as_text=True)
    headline = body.split('class="pageHeading leOfferTitle">')[1].split("</h1>")[0].strip()

    assert headline == "Special offer"
    assert "welcome_to_lotto_express" not in headline


def test_the_offer_price_is_shown_in_the_currency_it_was_locked_in(anon_client, serve_bundle):  # noqa: F811
    """
    A promo is priced in whatever currency marketing locked it at, against that
    currency's catalog with no FX (API 65). `base_currency` is the tenant's, and
    reading it put a pound sign on a EUR 25.00 offer - right number, wrong money.
    """
    serve_bundle(
        _bundle(
            "welcome_to_lotto_express",
            [{"product_code": "PSX-W", "quantity": 1}],
            locked_price_base_cents=2500,
            locked_price_currency="EUR",
            base_currency="GBP",
        )
    )

    body = anon_client.get("/offer/welcome_to_lotto_express").get_data(as_text=True)

    assert "\u20ac25.00" in body
    assert "\u00a325.00" not in body


def test_an_older_bundle_with_no_locked_currency_falls_back_to_the_tenants(anon_client, serve_bundle):  # noqa: F811
    """Older rows have no locked currency, and the tenant's is the only answer."""
    serve_bundle(
        _bundle(
            "welcome_to_lotto_express",
            [{"product_code": "PSX-W", "quantity": 1}],
            locked_price_base_cents=2500,
            base_currency="GBP",
        )
    )

    assert "\u00a325.00" in anon_client.get("/offer/welcome_to_lotto_express").get_data(as_text=True)


# --- a price we could not confirm ---


def test_a_cart_whose_offer_price_is_unconfirmed_cannot_be_bought(anon_client, promo_offer, crm_quote):  # noqa: F811
    """
    Submit re-quotes, so buying against a total the website assembled by itself
    is a payment taken for an order the CRM may then refuse over the price. The
    locked price is still shown - it is what the customer was emailed - but the
    order cannot be placed until the CRM confirms it.
    """
    crm_quote(fails=True)
    _click_through_and_buy(anon_client)

    body = anon_client.get("/cart").get_data(as_text=True)

    assert "22.50" in body
    assert "We can't confirm this price right now" in body
    assert "Confirm Order" not in body


def test_a_confirmed_offer_price_checks_out_as_before(anon_client, promo_offer, crm_quote):  # noqa: F811
    """The guard must only close on a cart the CRM did not price."""
    crm_quote()
    _click_through_and_buy(anon_client)

    body = anon_client.get("/cart").get_data(as_text=True)

    assert "We can't confirm this price right now" not in body
    assert "Confirm Order" in body


def test_an_ordinary_cart_is_not_closed_by_a_failed_quote(client, catalog, crm_quote):  # noqa: F811
    """
    Only a bundle carries a locked price the website could be wrong about. An
    ordinary cart has always priced itself from the catalog and still may.
    """
    crm_quote(fails=True)
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "PSX-W", "lines": [{"main": "1,2,3,4,5", "power": 6}], "options": {}}]

    body = client.get("/cart").get_data(as_text=True)

    assert "We can't confirm this price right now" not in body


def test_a_failed_quote_records_the_status_and_the_body(anon_client, promo_offer, monkeypatch, caplog):  # noqa: F811
    """
    A timeout, a 403 from the IP allowlist and a deliberate 400 all reach the
    customer as one sentence and each needs a different fix. Without the status
    and the body they cannot be told apart from outside.
    """
    def fake_quote(self, payload, *a, **kw):
        raise CRMError(
            "CRM HTTP 403: Forbidden",
            status_code=403,
            payload={"success": False, "error": "egress IP not allowlisted"},
        )

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    _click_through_and_buy(anon_client)

    with caplog.at_level(logging.WARNING):
        anon_client.get("/cart")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "status=403" in logged
    assert "egress IP not allowlisted" in logged
    assert f"bundle={SLUG}" in logged
