"""
Marketing Module offer landing pages.

These cover the acceptance list in the promotions briefing. Everyone who
reaches `/offer/<slug>` was sent by a campaign we paid for, so the failure
modes are tested as carefully as the happy path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from crm_api import CRMClient, CRMError


POWERBALL = {
    "code": "PSX-W",
    "product_code": "PSX-W",
    "game_code": "powerball",
    "product_type": "single",
    "price_in_base_cents": 500,
    "base_currency": "GBP",
    "line_schema": {"main": {"count": 5, "min": 1, "max": 69}, "power": {"count": 1, "min": 1, "max": 26}},
}

MEGAMILLIONS = {
    "code": "MSX-W",
    "product_code": "MSX-W",
    "game_code": "megamillions",
    "product_type": "single",
    "price_in_base_cents": 500,
    "base_currency": "GBP",
    "line_schema": {"main": {"count": 5, "min": 1, "max": 70}, "mega": {"count": 1, "min": 1, "max": 24}},
}

SUPERENALOTTO = {
    "code": "ENA-W",
    "product_code": "ENA-W",
    "game_code": "superenalotto",
    "product_type": "single",
    "price_in_base_cents": 500,
    "base_currency": "GBP",
    "line_schema": {"main": {"count": 6, "min": 1, "max": 90}},
}

CATALOG = [
    {"game_code": "powerball", "game_name": "PowerBall", "products": [POWERBALL]},
    {"game_code": "megamillions", "game_name": "MegaMillions", "products": [MEGAMILLIONS]},
    {"game_code": "superenalotto", "game_name": "SuperEnalotto", "products": [SUPERENALOTTO]},
]


def _bundle(slug: str, items: list[dict], **overrides) -> dict:
    payload = {
        "bundle_slug": slug,
        "title": "Welcome offer",
        "contents_description": "2 Powerball tickets for just \u00a35.00!",
        "locked_price_base_cents": 500,
        "locked_price_eur_cents": 580,
        "base_currency": "GBP",
        "items": items,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def catalog(stub_crm, monkeypatch):
    """The store's SKUs, so bundle items resolve to real number boards."""
    monkeypatch.setattr(CRMClient, "store_games", lambda self, *a, **k: {"games": CATALOG})
    monkeypatch.setattr(
        CRMClient,
        "store_products",
        lambda self, *a, **k: {"products": [POWERBALL, MEGAMILLIONS, SUPERENALOTTO]},
    )
    return stub_crm


@pytest.fixture
def serve_bundle(catalog, monkeypatch):
    """Serve one bundle from the CRM, matching the slug case-insensitively."""

    def install(bundle: dict):
        wanted = str(bundle["bundle_slug"]).lower()
        seen: list[str] = []

        def fake_bundle(self, bundle_slug: str, *a, **k):
            seen.append(bundle_slug)
            if str(bundle_slug).lower() != wanted:
                raise CRMError("CRM HTTP 404: bundle not found", status_code=404)
            return {"bundle": bundle}

        monkeypatch.setattr(CRMClient, "bundle", fake_bundle)
        return seen

    return install


def test_a_single_lottery_bundle_renders_its_boards_and_the_marketing_copy(anon_client, serve_bundle):
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "2 Powerball tickets for just \u00a35.00!" in body
    tickets = json.loads(body.split('id="leOfferTicketsJson" type="application/json">')[1].split("</script>")[0])
    assert [t["product_code"] for t in tickets] == ["PSX-W", "PSX-W"]
    assert [(t["position"], t["total"]) for t in tickets] == [(1, 2), (2, 2)]

    products = json.loads(body.split('id="leOfferProducts" type="application/json">')[1].split("</script>")[0])
    schema = {p["code"]: p["line_schema"] for p in products}["PSX-W"]
    ranges = {g["name"]: (g["count"], g["min"], g["max"]) for g in schema}
    assert ranges == {"main": (5, 1, 69), "power": (1, 1, 26)}


def test_a_mixed_bundle_gets_one_picker_per_item_counted_across_the_bundle(anon_client, serve_bundle):
    """
    Winnow reads the lottery from a single value on the bundle, so its
    three-lottery offer draws three Mega Millions boards and labels every one of
    them "Ticket 1 of 1". Each item has to carry its own product and the count
    has to run across the bundle.
    """
    serve_bundle(
        _bundle(
            "100mclub",
            [
                {"product_code": "ENA-W", "quantity": 1},
                {"product_code": "MSX-W", "quantity": 1},
                {"product_code": "PSX-W", "quantity": 1},
            ],
        )
    )

    body = anon_client.get("/offer/100mclub").get_data(as_text=True)

    tickets = json.loads(body.split('id="leOfferTicketsJson" type="application/json">')[1].split("</script>")[0])
    assert [t["product_code"] for t in tickets] == ["ENA-W", "MSX-W", "PSX-W"]
    assert [(t["position"], t["total"]) for t in tickets] == [(1, 3), (2, 3), (3, 3)]

    products = json.loads(body.split('id="leOfferProducts" type="application/json">')[1].split("</script>")[0])
    by_code = {p["code"]: {g["name"]: (g["count"], g["min"], g["max"]) for g in p["line_schema"]} for p in products}
    assert by_code["ENA-W"] == {"main": (6, 1, 90)}
    assert by_code["MSX-W"] == {"main": (5, 1, 70), "mega": (1, 1, 24)}
    assert by_code["PSX-W"] == {"main": (5, 1, 69), "power": (1, 1, 26)}


def test_an_unknown_slug_explains_itself_where_the_customer_landed(anon_client, catalog, monkeypatch):
    """
    A campaign click must never be bounced to the promotions list. That page
    reads "No promotions available yet", which tells someone who followed a live
    email link nothing at all about why.
    """
    monkeypatch.setattr(
        CRMClient,
        "bundle",
        lambda self, slug, *a, **k: (_ for _ in ()).throw(CRMError("CRM HTTP 404", status_code=404)),
    )

    resp = anon_client.get("/offer/no_such_offer")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "This offer is not available yet" in body
    assert 'content="noindex, follow"' in body


def test_an_unreachable_bundles_endpoint_does_not_read_as_a_withdrawn_offer(anon_client, catalog, monkeypatch):
    """
    The bundles endpoint is IP-gated. A server whose egress falls off the
    allowlist would otherwise present every live campaign as cancelled.
    """
    monkeypatch.setattr(
        CRMClient,
        "bundle",
        lambda self, slug, *a, **k: (_ for _ in ()).throw(
            CRMError("API access from your location is not allowed.", status_code=403)
        ),
    )

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "We can't load this offer right now" in body
    assert "This offer is not available yet" not in body


@pytest.mark.parametrize("path", ["/offer/PB_Welcome2", "/offer/pb_welcome2", "/OFFER/PB_WELCOME2"])
def test_the_slug_resolves_in_whichever_case_the_link_was_written(anon_client, serve_bundle, path):
    """The Module has stored both cases and links exist in both forms."""
    serve_bundle(_bundle("pb_welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    body = anon_client.get(path, follow_redirects=True).get_data(as_text=True)

    assert "leOfferTicketsJson" in body


def test_a_locale_prefixed_link_resolves_rather_than_spending_the_click_on_a_404(anon_client, serve_bundle):
    """
    The Module templates campaign links per locale. LottoExpress has no locale
    scheme, but the links are already printed in sent email.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    assert anon_client.get("/es-419/offer/PB_Welcome2").status_code == 200
    assert anon_client.get("/pt-br/offer/PB_Welcome2").status_code == 200


def test_a_bundle_built_on_a_sku_the_store_does_not_sell_says_so(anon_client, serve_bundle):
    """
    Winnow's live bundles all point at deactivated codes (`MS1`, `PS1`, `SE1`).
    Those have no line schema here, and a picker with no numbers in it is worse
    than an explanation.
    """
    serve_bundle(_bundle("legacy_bundle", [{"product_code": "PS1", "quantity": 2}]))

    body = anon_client.get("/offer/legacy_bundle").get_data(as_text=True)

    assert "we're not selling at the moment" in body
    assert "leOfferTicketsJson" not in body


def test_the_locked_price_renders_in_the_brands_base_currency(anon_client, serve_bundle):
    """
    The stored column is named `locked_price_eur_cents` for historical reasons
    and holds a different number. This brand is GBP; reading the legacy field
    would overcharge the page by 80p.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "\u00a35.00" in body
    assert "5.80" not in body


def test_starting_an_offer_builds_the_cart_from_the_bundle_not_from_the_form(anon_client, serve_bundle):
    serve_bundle(
        _bundle(
            "mixed",
            [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "ENA-W", "quantity": 1}],
        )
    )
    lines = [
        {"main": "1,2,3,4,5", "power": 6},
        {"main": "7,8,9,10,11", "power": 12},
        {"main": "1,2,3,4,5,6"},
    ]

    resp = anon_client.post("/offer/mixed/start", data={"lines_json": json.dumps(lines)})

    assert resp.headers["Location"].endswith("/cart")
    with anon_client.session_transaction() as s:
        assert s["checkout_bundle_slug"] == "mixed"
        cart = s["cart_items"]
    assert [(i["product_code"], len(i["lines"])) for i in cart] == [("PSX-W", 2), ("ENA-W", 1)]
    assert cart[0]["game_code"] == "powerball"


def test_an_offer_cannot_be_started_with_tickets_left_unplayed(anon_client, serve_bundle):
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    resp = anon_client.post(
        "/offer/PB_Welcome2/start",
        data={"lines_json": json.dumps([{"main": "1,2,3,4,5", "power": 6}])},
    )

    assert "/offer/PB_Welcome2" in resp.headers["Location"]
    with anon_client.session_transaction() as s:
        assert "checkout_bundle_slug" not in s


def test_the_campaign_parameters_survive_the_landing_and_reach_the_quote(client, serve_bundle, monkeypatch):
    """
    `src` / `cmp` / `tid` are how the order joins back to the campaign, and the
    bundle slug is what makes the CRM apply the locked price. An offer cart is a
    cart of ordinary lottery SKUs, so both have to survive that path.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))
    sent: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, *a, **k: sent.append(payload) or {"quote": {"currency": "GBP", "items": []}},
    )

    client.get("/offer/PB_Welcome2?src=cbm&cmp=CB-Meta-0426&tid=c3_ut4g5&intent=acquisition")
    client.post("/offer/PB_Welcome2/start", data={"lines_json": json.dumps([{"main": "1,2,3,4,5", "power": 6}])})
    client.get("/cart")

    assert sent, "the cart never quoted"
    payload = sent[-1]
    assert payload["bundle_slug"] == "PB_Welcome2"
    assert (payload["src"], payload["cmp"], payload["tid"]) == ("cbm", "CB-Meta-0426", "c3_ut4g5")
    assert payload["intent"] == "acquisition"


# --- Multi-draw bundles ---
#
# A bundle can buy one board that plays for a run of draws. `quantity` is
# boards; `draws_count` is how many draws each board enters.

SCHEDULE = {"draw_weeks": 4, "draw_weekdays": ["monday", "wednesday", "saturday"], "draws_count": 12}
SCHEDULE_TEXT = "Your numbers play every Monday, Wednesday and Saturday for 4 weeks \u2014 12 draws."


def _tickets_from(body: str) -> list[dict]:
    return json.loads(body.split('id="leOfferTicketsJson" type="application/json">')[1].split("</script>")[0])


def test_a_multi_draw_bundle_states_its_schedule(anon_client, serve_bundle):
    serve_bundle(_bundle("pb_4weeks", [{"product_code": "PSX-W", "quantity": 1, "config_json": SCHEDULE}]))

    tickets = _tickets_from(anon_client.get("/offer/pb_4weeks").get_data(as_text=True))

    assert [t["schedule"] for t in tickets] == [SCHEDULE_TEXT]


def test_the_schedule_reads_the_same_whichever_way_the_crm_sent_it(anon_client, serve_bundle):
    """
    `config_json` used to arrive as an escaped string and now arrives parsed.
    Both are on the wire depending on which side deployed first, and a reader
    that understands one of them loses the schedule without saying anything.
    """
    serve_bundle(
        _bundle("pb_4weeks", [{"product_code": "PSX-W", "quantity": 1, "config_json": json.dumps(SCHEDULE)}])
    )

    tickets = _tickets_from(anon_client.get("/offer/pb_4weeks").get_data(as_text=True))

    assert [t["schedule"] for t in tickets] == [SCHEDULE_TEXT]


def test_a_twelve_draw_bundle_is_one_board_not_twelve(anon_client, serve_bundle):
    """`draws_count` labels a board. It is never a reason to draw more of them."""
    serve_bundle(_bundle("pb_4weeks", [{"product_code": "PSX-W", "quantity": 1, "config_json": SCHEDULE}]))

    tickets = _tickets_from(anon_client.get("/offer/pb_4weeks").get_data(as_text=True))

    assert len(tickets) == 1
    assert (tickets[0]["position"], tickets[0]["total"]) == (1, 1)


def test_a_bundle_with_no_schedule_says_nothing_about_draws(anon_client, serve_bundle):
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    tickets = _tickets_from(anon_client.get("/offer/PB_Welcome2").get_data(as_text=True))

    assert [t["schedule"] for t in tickets] == ["", ""]


def test_the_cart_states_the_schedule_the_quote_returned(client, serve_bundle, monkeypatch):
    """The locked price covers the whole run, so a cart that shows one draw is
    quoting a number the customer has no way to make sense of."""
    serve_bundle(_bundle("pb_4weeks", [{"product_code": "PSX-W", "quantity": 1, "config_json": SCHEDULE}]))
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, *a, **k: {
            "quote": {"currency": "GBP", "items": [{"name": "US Powerball", "schedule": SCHEDULE}]}
        },
    )

    client.post("/offer/pb_4weeks/start", data={"lines_json": json.dumps([{"main": "1,2,3,4,5", "power": 6}])})
    body = client.get("/cart").get_data(as_text=True)

    assert SCHEDULE_TEXT in body


def test_a_lifecycle_link_does_not_overwrite_an_acquisition_source(client, serve_bundle, monkeypatch):
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))
    sent: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, *a, **k: sent.append(payload) or {"quote": {"currency": "GBP", "items": []}},
    )

    client.get("/offer/PB_Welcome2?cmp=jackpot-alert&tid=c5_x0iar&intent=lifecycle")
    client.post("/offer/PB_Welcome2/start", data={"lines_json": json.dumps([{"main": "1,2,3,4,5", "power": 6}])})
    client.get("/cart")

    assert "src" not in sent[-1]
    assert sent[-1]["tid"] == "c5_x0iar"


# --- The page around the boards ---
#
# The offer page is a landing page for a click someone paid for, so what sits
# around the boards is load-bearing rather than decoration.


@pytest.fixture
def own_cache(tmp_path):
    """A jackpot cache belonging to this test alone."""
    from crm_cache import CacheConfig, CRMCache
    from app import app as flask_app

    original = flask_app.config["CRM_CACHE"]
    cache = CRMCache(CacheConfig(db_path=str(tmp_path / "cache.sqlite"), brand=original.cfg.brand))
    cache.init_db()
    flask_app.config["CRM_CACHE"] = cache
    try:
        yield cache
    finally:
        flask_app.config["CRM_CACHE"] = original


def test_a_single_lottery_offer_leads_with_that_lotterys_jackpot(anon_client, serve_bundle, own_cache):
    own_cache.upsert_jackpots(
        [{"game_code": "powerball", "currency": "USD", "jackpot_total": 207000000, "remaining_seconds": 8000}]
    )
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "$207,000,000" in body
    assert 'data-remaining="8000"' in body


def test_a_bundle_spanning_lotteries_names_each_one_instead_of_picking_a_headline(
    anon_client, serve_bundle, own_cache
):
    """
    Two lotteries means two jackpots, and promoting one of them to the banner
    would tell the customer they are buying a shot at a figure that only one of
    their tickets is playing for.
    """
    own_cache.upsert_jackpots(
        [
            {"game_code": "powerball", "currency": "USD", "jackpot_total": 207000000},
            {"game_code": "superenalotto", "currency": "EUR", "jackpot_total": 41300000},
        ]
    )
    serve_bundle(
        _bundle(
            "mixed",
            [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "ENA-W", "quantity": 1}],
        )
    )

    body = anon_client.get("/offer/mixed").get_data(as_text=True)

    assert "$207,000,000" in body
    assert "\u20ac41,300,000" in body
    assert 'id="bannerJackpotAmount"' not in body


def test_an_offer_with_no_jackpot_to_quote_still_renders_its_boards(anon_client, serve_bundle, own_cache):
    """A cold jackpot cache must cost the banner a figure, not the page."""
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "leOfferTicketsJson" in body
    assert "\u00a35.00" in body


def test_the_boards_keep_the_ids_the_stylesheet_dresses_them_with(anon_client, serve_bundle):
    """
    Every rule for the ball grid, the complete state and the below-768px
    editor is scoped to `#main #tickets_section`. Without those ids the page
    still works and looks unstyled, which is how it looked before, so this is
    worth failing over rather than discovering in a screenshot.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert 'class="noSelect container lePages lotteryOfferPages"' in body
    assert 'id="main"' in body
    assert 'id="tickets_section"' in body
    assert 'id="mobileTicketWindow"' in body


def test_the_offer_page_carries_the_about_copy_without_leaving_the_page(anon_client, serve_bundle):
    """
    A campaign lands strangers here. The About copy is reachable from the offer
    itself so nobody has to navigate away - and lose the boards they have
    filled in - to find out who is taking their money.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "Ralseft Limited" in body
    assert "Access to the World&#39;s Biggest Jackpots" in body
    # `details` collapses it without script, so it cannot be left stuck open
    # on a page whose primary job is the number boards.
    assert '<details class="leOfferAbout">' in body


def test_the_about_page_and_the_offer_page_tell_the_same_story(anon_client, stub_crm, serve_bundle):
    """
    The company details are a legal statement. Two copies drift, and the one
    nobody is watching is the one that goes stale.
    """
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))

    about = anon_client.get("/about").get_data(as_text=True)
    offer = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    claim = "Ralseft Limited was established in 2018"
    assert claim in about
    assert claim in offer


# --- Syndicate offers ---
#
# A syndicate share is not a ticket. The group's boards are wheeled before the
# offer goes out, so there is nothing to pick — and the picker's Continue
# button waits for numbers, which meant an offer built on a share could not be
# bought at all.


ELGORDO_SYNDICATE = {
    "code": "FG20",
    "product_code": "FG20",
    "game_code": "elgordo",
    "game_name": "El Gordo",
    "product_type": "syndicate",
    "name": "El Gordo 20# Wheel",
    "price_in_base_cents": 1200,
    "base_currency": "GBP",
    "syndicate_prebuilt_wheel_name": "20# Full Pick 5 Wheel",
    # What the live store catalogue calls the board count.
    "syndicate_boards_per_group": 15504,
    "syndicate_max_participants": 120,
    "syndicate_shares_remaining": 37,
}

AUSTRIA_SYNDICATE = {
    "code": "AG4",
    "product_code": "AG4",
    "game_code": "austrialotto",
    "game_name": "Austria Lotto",
    "product_type": "syndicate",
    "name": "Austria Lotto Group",
    "price_in_base_cents": 800,
    "base_currency": "GBP",
    "syndicate_prebuilt_wheel_name": "4# Group Wheel",
    "syndicate_wheel_num_lines": 210,
}

SYNDICATE_CATALOG = CATALOG + [
    {"game_code": "elgordo", "game_name": "El Gordo", "syndicate_products": [ELGORDO_SYNDICATE]},
    {"game_code": "austrialotto", "game_name": "Austria Lotto", "syndicate_products": [AUSTRIA_SYNDICATE]},
]


@pytest.fixture
def syndicate_catalog(stub_crm, monkeypatch):
    """A store that sells shares as well as tickets."""
    monkeypatch.setattr(CRMClient, "store_games", lambda self, *a, **k: {"games": SYNDICATE_CATALOG})
    monkeypatch.setattr(
        CRMClient,
        "store_products",
        lambda self, *a, **k: {
            "products": [POWERBALL, MEGAMILLIONS, SUPERENALOTTO, ELGORDO_SYNDICATE, AUSTRIA_SYNDICATE]
        },
    )
    return stub_crm


@pytest.fixture
def serve_syndicate_bundle(syndicate_catalog, monkeypatch):
    def install(bundle: dict):
        wanted = str(bundle["bundle_slug"]).lower()

        def fake_bundle(self, bundle_slug: str, *a, **k):
            if str(bundle_slug).lower() != wanted:
                raise CRMError("CRM HTTP 404: bundle not found", status_code=404)
            return {"bundle": bundle}

        monkeypatch.setattr(CRMClient, "bundle", fake_bundle)

    return install


def test_a_syndicate_offer_shows_no_number_picker(anon_client, serve_syndicate_bundle):
    """
    The whole defect. A share has no numbers, so "Build your play" asked for
    something that does not exist and the board was drawn from a schema the
    product does not have.
    """
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Build your play" not in body
    assert 'id="leOfferTickets"' not in body
    assert 'id="leLineTemplate"' not in body
    assert "offer_picker.js" not in body
    # Stated, or this passes for the wrong reason: before the fix the page had
    # no picker because it had refused the offer outright.
    assert "20# Full Pick 5 Wheel" in body


def test_continue_is_ready_on_a_syndicate_offer(anon_client, serve_syndicate_bundle):
    """
    There is nothing for the customer to complete, and the picker is what
    re-enables the button. With no picker on the page a disabled Continue is
    never switched back on, which is why nothing could be bought.
    """
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    submit = body.split('id="leOfferSubmit"')[1].split(">")[0]
    assert "disabled" not in submit


def test_a_syndicate_offer_says_what_the_group_plays(anon_client, serve_syndicate_bundle):
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "20# Full Pick 5 Wheel" in body
    assert "15,504" in body
    assert "37" in body  # shares remaining
    assert (
        "Your numbers are already selected \u2014 this syndicate plays a fixed wheel "
        "of 15,504 boards at every draw." in body
    )


def test_an_ordinary_offer_still_waits_for_its_numbers(anon_client, serve_bundle):
    """The guard that makes a syndicate purchasable must not hand a customer a
    Continue button on an offer whose boards are still empty."""
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "Build your play" in body
    submit = body.split('id="leOfferSubmit"')[1].split(">")[0]
    assert "disabled" in submit


@pytest.mark.parametrize("code", ["FG20", "FG18", "FG8", "AG4", "GG9", "PG9"])
def test_every_syndicate_code_is_recognised_from_its_type(anon_client, stub_crm, monkeypatch, code):
    """
    Keyed on `product_type`, never on the code or the name: these six share no
    prefix, so any rule written from the codes would miss the seventh the CRM
    adds.
    """
    product = dict(ELGORDO_SYNDICATE, code=code, product_code=code)
    monkeypatch.setattr(
        CRMClient,
        "store_games",
        lambda self, *a, **k: {"games": [{"game_code": "elgordo", "game_name": "El Gordo", "syndicate_products": [product]}]},
    )
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [product]})
    monkeypatch.setattr(
        CRMClient, "bundle", lambda self, slug, *a, **k: {"bundle": _bundle("s", [{"product_code": code, "quantity": 1}])}
    )

    body = anon_client.get("/offer/s").get_data(as_text=True)

    assert "Build your play" not in body
    assert "20# Full Pick 5 Wheel" in body


def test_a_single_named_like_a_syndicate_still_gets_its_picker(anon_client, stub_crm, monkeypatch):
    """The other half of keying off the type. Product names are inconsistent,
    and a single whose name says "syndicate" is still a ticket to be filled in."""
    product = dict(POWERBALL, name="Powerball Syndicate Special")
    monkeypatch.setattr(
        CRMClient,
        "store_games",
        lambda self, *a, **k: {"games": [{"game_code": "powerball", "game_name": "PowerBall", "products": [product]}]},
    )
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [product]})
    monkeypatch.setattr(
        CRMClient,
        "bundle",
        lambda self, slug, *a, **k: {"bundle": _bundle("s", [{"product_code": "PSX-W", "quantity": 1}])},
    )

    body = anon_client.get("/offer/s").get_data(as_text=True)

    assert "Build your play" in body


def test_a_syndicate_is_not_mistaken_for_a_game_we_stopped_selling(anon_client, serve_syndicate_bundle):
    """
    A share has no `line_schema`, and the unsellable check reads a missing
    schema as a deactivated SKU. Judged on that, every syndicate offer refuses
    itself with "a game we're not selling at the moment".
    """
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "not selling at the moment" not in body


def test_a_syndicate_offer_can_actually_be_bought(anon_client, serve_syndicate_bundle):
    """The purchase the customer could not make. No lines are posted because
    there are none to post, and that must not read as an empty offer."""
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    resp = anon_client.post("/offer/gordo_share/start", data={"lines_json": "[]"})

    assert resp.headers["Location"].endswith("/cart")
    with anon_client.session_transaction() as s:
        assert s["checkout_bundle_slug"] == "gordo_share"
        cart = s["cart_items"]
    assert cart == [
        {
            "kind": "syndicate",
            "product_code": "FG20",
            "quantity": 1,
            "options": {},
            "game_code": "elgordo",
            "game_name": "El Gordo",
        }
    ]


def test_several_shares_of_one_syndicate_are_a_quantity_not_a_repeat(anon_client, serve_syndicate_bundle):
    """Three shares are three stakes in the same boards, so the page states them
    once and the cart carries a count rather than three identical items."""
    serve_syndicate_bundle(_bundle("gordo3", [{"product_code": "FG20", "quantity": 3}]))

    body = anon_client.get("/offer/gordo3").get_data(as_text=True)
    assert body.count("20# Full Pick 5 Wheel") == 1
    assert "3 shares" in body

    anon_client.post("/offer/gordo3/start", data={"lines_json": "[]"})
    with anon_client.session_transaction() as s:
        assert [(i["product_code"], i["quantity"]) for i in s["cart_items"]] == [("FG20", 3)]


def test_two_different_syndicates_each_get_their_own_panel(anon_client, serve_syndicate_bundle):
    serve_syndicate_bundle(
        _bundle("two", [{"product_code": "FG20", "quantity": 1}, {"product_code": "AG4", "quantity": 1}])
    )

    body = anon_client.get("/offer/two").get_data(as_text=True)

    assert "20# Full Pick 5 Wheel" in body
    assert "4# Group Wheel" in body
    assert "210" in body


def test_a_mixed_bundle_picks_numbers_for_the_ticket_and_not_for_the_share(
    anon_client, serve_syndicate_bundle
):
    """
    The picker covers the ordinary tickets only. Counting the share among them
    would leave one board permanently unfilled and the button permanently off.
    """
    serve_syndicate_bundle(
        _bundle("mixed_syn", [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "FG20", "quantity": 1}])
    )

    body = anon_client.get("/offer/mixed_syn").get_data(as_text=True)

    assert "Build your play" in body
    assert "20# Full Pick 5 Wheel" in body
    tickets = json.loads(body.split('id="leOfferTicketsJson" type="application/json">')[1].split("</script>")[0])
    assert [t["product_code"] for t in tickets] == ["PSX-W", "PSX-W"]


def test_the_boards_are_counted_without_the_share(anon_client, serve_syndicate_bundle):
    """
    Two boards headed "Ticket 1 of 3" and "Ticket 2 of 3" send the customer
    hunting for a third ticket. The share is the third item in the bundle, but
    it is not one of the boards to fill in.
    """
    serve_syndicate_bundle(
        _bundle("mixed_syn", [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "FG20", "quantity": 1}])
    )

    body = anon_client.get("/offer/mixed_syn").get_data(as_text=True)

    tickets = json.loads(body.split('id="leOfferTicketsJson" type="application/json">')[1].split("</script>")[0])
    assert [(t["position"], t["total"]) for t in tickets] == [(1, 2), (2, 2)]


def test_a_mixed_bundle_carries_both_kinds_into_the_cart(anon_client, serve_syndicate_bundle):
    serve_syndicate_bundle(
        _bundle("mixed_syn", [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "FG20", "quantity": 1}])
    )
    lines = [{"main": "1,2,3,4,5", "power": 6}, {"main": "7,8,9,10,11", "power": 12}]

    resp = anon_client.post("/offer/mixed_syn/start", data={"lines_json": json.dumps(lines)})

    assert resp.headers["Location"].endswith("/cart")
    with anon_client.session_transaction() as s:
        cart = s["cart_items"]
    assert [(i["kind"], i["product_code"]) for i in cart] == [("single", "PSX-W"), ("syndicate", "FG20")]
    assert len(cart[0]["lines"]) == 2
    assert "lines" not in cart[1]


def test_a_mixed_bundle_still_refuses_an_unplayed_ticket(anon_client, serve_syndicate_bundle):
    """The share needs nothing, but the Powerball board still does."""
    serve_syndicate_bundle(
        _bundle("mixed_syn", [{"product_code": "PSX-W", "quantity": 2}, {"product_code": "FG20", "quantity": 1}])
    )

    resp = anon_client.post(
        "/offer/mixed_syn/start",
        data={"lines_json": json.dumps([{"main": "1,2,3,4,5", "power": 6}])},
    )

    assert "/offer/mixed_syn" in resp.headers["Location"]
    with anon_client.session_transaction() as s:
        assert "checkout_bundle_slug" not in s


def test_a_syndicate_banner_does_not_headline_a_jackpot_the_share_does_not_win(
    anon_client, serve_syndicate_bundle, own_cache
):
    """
    A share is a stake in a group's boards, so printing the full jackpot at
    73px beside it states a prize this customer is not buying. The countdown
    takes the middle instead.
    """
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "leOfferHeroSyndicate" in body
    assert 'id="bannerJackpotAmount"' not in body
    assert "3,000,000" not in body
    # Cached and available, so its absence above is the banner suppressing it
    # rather than there being nothing to show.
    assert 'data-remaining="8000"' in body


def test_the_syndicate_banner_counts_down_to_the_offer_closing_not_the_draw(
    anon_client, serve_syndicate_bundle, own_cache
):
    """
    Marketing's closing date is the one that decides whether this page can
    still be bought from. The draw cutoff is a different date, and counting to
    it either hurries a customer who had days left or lets a window close they
    believed was open.
    """
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    ends = datetime.now(timezone.utc) + timedelta(hours=6)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            end_at=ends.isoformat().replace("+00:00", "Z"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" in body
    assert "Draw Cutoff Timer" not in body
    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 6 * 3600 - 120 <= remaining <= 6 * 3600
    # The draw's own countdown is cached and would have been used otherwise.
    assert 'data-remaining="8000"' not in body


@pytest.mark.parametrize(
    "field", ["end_at", "ends_at", "expires_at", "valid_until", "available_until"]
)
def test_the_closing_date_is_read_whatever_the_crm_calls_it(
    anon_client, serve_syndicate_bundle, field
):
    """The bundle payload has not been seen carrying a deadline, so the near
    neighbours of the Module's own `end_at` are accepted rather than the
    countdown quietly falling back to the draw."""
    ends = datetime.now(timezone.utc) + timedelta(hours=3)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            **{field: ends.isoformat().replace("+00:00", "Z")},
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" in body


def test_the_board_count_is_read_from_the_field_the_catalogue_uses(
    anon_client, serve_syndicate_bundle
):
    """
    The store catalogue calls it `syndicate_boards_per_group`. Reading only
    the name the brief gave leaves the panel silent about the one thing that
    makes a wheel worth buying: a share of 15,504 boards reads as an ordinary
    entry without it.
    """
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "15,504" in body
    assert "fixed wheel of 15,504 boards" in body


def test_a_syndicate_names_the_wheel_even_though_the_catalogue_has_no_field_for_it(
    anon_client, serve_syndicate_bundle, syndicate_catalog, monkeypatch
):
    """The game's name is "Lotto (FR)", which does not say which wheel the
    share belongs to. The product's own name does."""
    unnamed = {k: v for k, v in ELGORDO_SYNDICATE.items() if k != "syndicate_prebuilt_wheel_name"}
    monkeypatch.setattr(
        CRMClient,
        "store_games",
        lambda self, *a, **k: {
            "games": CATALOG
            + [{"game_code": "elgordo", "game_name": "El Gordo", "syndicate_products": [unnamed]}]
        },
    )
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [unnamed]})
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "El Gordo 20# Wheel" in body


@pytest.mark.parametrize(
    "field", ["syndicate_boards_per_group", "syndicate_wheel_num_lines", "syndicate_num_lines"]
)
def test_the_board_count_is_read_whatever_the_catalogue_calls_it(
    anon_client, serve_syndicate_bundle, syndicate_catalog, monkeypatch, field
):
    product = {k: v for k, v in ELGORDO_SYNDICATE.items() if k != "syndicate_boards_per_group"}
    product[field] = 15504
    monkeypatch.setattr(
        CRMClient,
        "store_games",
        lambda self, *a, **k: {
            "games": CATALOG
            + [{"game_code": "elgordo", "game_name": "El Gordo", "syndicate_products": [product]}]
        },
    )
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [product]})
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "15,504" in body


def test_a_syndicate_with_no_board_count_still_reads_sensibly(
    anon_client, serve_syndicate_bundle, syndicate_catalog, monkeypatch
):
    """FG20 has `syndicate_boards_per_group` set to null in the live
    catalogue, so the panel has to stand up without it."""
    product = {k: v for k, v in ELGORDO_SYNDICATE.items() if k != "syndicate_boards_per_group"}
    product["syndicate_boards_per_group"] = None
    monkeypatch.setattr(
        CRMClient,
        "store_games",
        lambda self, *a, **k: {
            "games": CATALOG
            + [{"game_code": "elgordo", "game_name": "El Gordo", "syndicate_products": [product]}]
        },
    )
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [product]})
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Your numbers are already selected" in body
    assert "Boards played" not in body
    assert "None" not in body


@pytest.mark.parametrize(
    "field",
    [
        "offer_end_date",
        "closes_at",
        "closing_date",
        "deadline",
        "cutoff_at",
        "expiration_date",
        "sale_ends",
        "active_to",
        "bundle_expiry",
    ],
)
def test_a_closing_date_is_found_under_a_name_nobody_predicted(
    anon_client, serve_syndicate_bundle, field
):
    """
    A fixed list of guesses that misses leaves the page counting to the draw
    as though marketing had set no deadline at all — the wrong clock, and with
    nothing on the page to say so. Any field that reads as a closing date and
    holds a timestamp is taken instead.
    """
    ends = datetime.now(timezone.utc) + timedelta(hours=3)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            **{field: ends.isoformat().replace("+00:00", "Z")},
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" in body
    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 3 * 3600 - 120 <= remaining <= 3 * 3600


def test_a_closing_date_is_found_where_the_crm_nests_it(anon_client, serve_syndicate_bundle):
    """Some tenants hang the selling window off a block of its own rather than
    the top level of the bundle."""
    ends = datetime.now(timezone.utc) + timedelta(hours=5)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            campaign={"name": "September push", "ends": ends.isoformat().replace("+00:00", "Z")},
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" in body
    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 5 * 3600 - 120 <= remaining <= 5 * 3600


@pytest.mark.parametrize(
    "field", ["start_at", "created_at", "updated_at", "draw_cutoff_at", "next_draw_ends_at"]
)
def test_a_date_that_is_not_the_offer_closing_is_not_counted_to(
    anon_client, serve_syndicate_bundle, own_cache, field
):
    """
    Searching by shape rather than by name is only safe if it refuses the
    other dates a bundle carries. Counting to the draw cutoff is the very
    thing this was meant to stop, and counting to `created_at` would show
    every offer as long closed.
    """
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    when = datetime.now(timezone.utc) + timedelta(hours=9)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            **{field: when.isoformat().replace("+00:00", "Z")},
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" not in body
    assert "Draw Cutoff Timer" in body


def test_an_items_own_draw_date_is_not_read_as_the_offer_closing(
    anon_client, serve_syndicate_bundle, own_cache
):
    """A bundle's items carry dates of their own, and none of them is the date
    marketing set for the offer."""
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    when = datetime.now(timezone.utc) + timedelta(hours=9)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [
                {
                    "product_code": "FG20",
                    "quantity": 1,
                    "ends_at": when.isoformat().replace("+00:00", "Z"),
                }
            ],
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" not in body


def test_the_earliest_of_several_closing_dates_is_the_one_that_binds(
    anon_client, serve_syndicate_bundle
):
    """If a bundle states two, the offer stops selling at the first: counting
    to the later one keeps a page live past the point it can be bought."""
    soon = datetime.now(timezone.utc) + timedelta(hours=2)
    later = datetime.now(timezone.utc) + timedelta(hours=20)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            closes_at=soon.isoformat().replace("+00:00", "Z"),
            available_to=later.isoformat().replace("+00:00", "Z"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 2 * 3600 - 120 <= remaining <= 2 * 3600


def test_an_empty_closing_date_is_not_a_deadline(
    anon_client, serve_syndicate_bundle, own_cache
):
    """Marketing leaving the field blank reaches us as an empty string or a
    null, and neither means the offer closed at the epoch."""
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            end_at="",
            closes_at=None,
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Draw Cutoff Timer" in body
    assert 'data-remaining="0"' not in body


def test_a_closing_date_without_a_timezone_is_read_as_utc(anon_client, serve_syndicate_bundle):
    """Read as local time instead, the deadline moves by hours — in whichever
    direction the server happens to sit from UTC."""
    ends = datetime.now(timezone.utc) + timedelta(hours=4)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            end_at=ends.strftime("%Y-%m-%d %H:%M:%S"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 4 * 3600 - 120 <= remaining <= 4 * 3600


def test_an_offer_that_has_already_closed_does_not_count_backwards(
    anon_client, serve_syndicate_bundle
):
    ends = datetime.now(timezone.utc) - timedelta(hours=2)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            end_at=ends.isoformat().replace("+00:00", "Z"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert 'data-remaining="0"' in body
    # "Results pending" would read as a draw the customer is waiting on
    # rather than a sale that is over.
    assert 'data-ended-label="Offer closed"' in body


def test_a_syndicate_offer_with_no_closing_date_still_shows_the_draw_cutoff(
    anon_client, serve_syndicate_bundle, own_cache
):
    """Marketing may simply not have set one. An empty banner would be worse
    than the draw cutoff it used to show."""
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    serve_syndicate_bundle(_bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}]))

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Draw Cutoff Timer" in body
    assert 'data-remaining="8000"' in body


def test_an_ordinary_offer_keeps_counting_to_its_draw(anon_client, serve_bundle, own_cache):
    """Scoped to syndicates. An ordinary offer's boards go into a specific
    draw, and the cutoff for that draw is the deadline that matters there."""
    own_cache.upsert_jackpots(
        [{"game_code": "powerball", "currency": "USD", "jackpot_total": 207000000, "remaining_seconds": 8000}]
    )
    ends = datetime.now(timezone.utc) + timedelta(hours=6)
    serve_bundle(
        _bundle(
            "PB_Welcome2",
            [{"product_code": "PSX-W", "quantity": 2}],
            end_at=ends.isoformat().replace("+00:00", "Z"),
        )
    )

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "Draw Cutoff Timer" in body
    assert "Offer ends in" not in body
    assert 'data-remaining="8000"' in body


def test_an_ordinary_offer_banner_still_leads_with_its_jackpot(anon_client, serve_bundle, own_cache):
    """The other half. Dropping the figure is for shares only — on an ordinary
    offer the jackpot is the reason the click was paid for."""
    own_cache.upsert_jackpots(
        [{"game_code": "powerball", "currency": "USD", "jackpot_total": 207000000, "remaining_seconds": 8000}]
    )
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 2}]))

    body = anon_client.get("/offer/PB_Welcome2").get_data(as_text=True)

    assert "leOfferHeroSyndicate" not in body
    assert 'id="bannerJackpotAmount"' in body
    assert "$207,000,000" in body


def test_a_share_is_counted_as_a_share_in_the_offer_headline(anon_client, serve_syndicate_bundle):
    """"2 tickets" overstates what two shares in one wheel actually buy."""
    serve_syndicate_bundle(
        _bundle("two", [{"product_code": "FG20", "quantity": 2}, {"product_code": "AG4", "quantity": 1}])
    )

    body = anon_client.get("/offer/two").get_data(as_text=True)

    assert "2 shares" in body
    assert "2 tickets" not in body


def test_the_crm_bundle_contract_starts_the_offer_clock(anon_client, serve_syndicate_bundle):
    """The shape the CRM agreed to send: `end_at` and `start_at` from
    `mm_offers`, UTC with a `Z`, always present, null when unset."""
    ends = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0)
    starts = (datetime.now(timezone.utc) - timedelta(days=9)).replace(microsecond=0)
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            offer_id=8,
            offer_name="French 6/49 20 Number Wheel Syndicate",
            end_at=ends.strftime("%Y-%m-%dT%H:%M:%SZ"),
            start_at=starts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Offer ends in" in body
    remaining = int(body.split('data-remaining="')[1].split('"')[0])
    assert 5 * 86400 - 120 <= remaining <= 5 * 86400


def test_the_crm_bundle_contract_with_no_deadline_keeps_the_draw_clock(
    anon_client, serve_syndicate_bundle, own_cache
):
    own_cache.upsert_jackpots(
        [{"game_code": "elgordo", "currency": "EUR", "jackpot_total": 3000000, "remaining_seconds": 8000}]
    )
    serve_syndicate_bundle(
        _bundle(
            "gordo_share",
            [{"product_code": "FG20", "quantity": 1}],
            offer_id=8,
            end_at=None,
            start_at=(datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    assert "Draw Cutoff Timer" in body
    assert "Offer ends in" not in body


# --- An offer past its deadline cannot be continued ---


def _closed(hours_ago: float = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(hours: float = 6) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _continue_button(body: str) -> str:
    return body.split('id="leOfferSubmit"')[1].split(">")[0]


def test_a_closed_offer_cannot_be_continued(anon_client, serve_syndicate_bundle):
    """The banner said "Offer closed" over a live Continue button, and the
    customer only learned the offer was over after going through to checkout."""
    serve_syndicate_bundle(
        _bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}], end_at=_closed(), start_at=None)
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)

    button = _continue_button(body)
    assert "disabled" in button
    assert 'data-offer-closed="1"' in button
    assert "This offer has ended." in body


def test_a_closed_offer_is_refused_even_if_the_form_is_sent(anon_client, serve_syndicate_bundle):
    """A disabled button is a courtesy. A tab left open, or a form posted by
    hand, still reaches here."""
    serve_syndicate_bundle(
        _bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}], end_at=_closed(), start_at=None)
    )

    resp = anon_client.post("/offer/gordo_share/start", data={"lines_json": "[]"})

    assert resp.headers["Location"].endswith("/offer/gordo_share")
    with anon_client.session_transaction() as s:
        assert not s.get("cart_items")
        flashes = [m for _, m in s.get("_flashes", [])]
    assert "This offer has ended." in flashes


def test_an_open_offer_can_still_be_continued(anon_client, serve_syndicate_bundle):
    serve_syndicate_bundle(
        _bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}], end_at=_open(), start_at=None)
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)
    resp = anon_client.post("/offer/gordo_share/start", data={"lines_json": "[]"})

    button = _continue_button(body)
    assert "disabled" not in button
    assert "data-offer-closed" not in button
    # The page closes itself at the deadline, so it has to know when that is.
    remaining = int(button.split('data-offer-remaining="')[1].split('"')[0])
    assert 6 * 3600 - 120 <= remaining <= 6 * 3600
    assert resp.headers["Location"].endswith("/cart")


def test_an_offer_with_no_deadline_is_never_closed(anon_client, serve_syndicate_bundle):
    serve_syndicate_bundle(
        _bundle("gordo_share", [{"product_code": "FG20", "quantity": 1}], end_at=None, start_at=None)
    )

    body = anon_client.get("/offer/gordo_share").get_data(as_text=True)
    resp = anon_client.post("/offer/gordo_share/start", data={"lines_json": "[]"})

    button = _continue_button(body)
    assert "disabled" not in button
    assert "data-offer-remaining" not in button
    assert resp.headers["Location"].endswith("/cart")


def test_a_closed_ordinary_offer_cannot_be_continued_either(anon_client, serve_bundle):
    """The deadline is the offer's, not the syndicate's. Checkout refuses any
    expired offer, so the page has to say so for all of them."""
    serve_bundle(_bundle("pb_welcome2", [{"product_code": "PSX-W", "quantity": 1}], end_at=_closed()))

    body = anon_client.get("/offer/pb_welcome2").get_data(as_text=True)
    resp = anon_client.post(
        "/offer/pb_welcome2/start", data={"lines_json": '[{"main": "1,2,3,4,5", "power": "6"}]'}
    )

    assert 'data-offer-closed="1"' in _continue_button(body)
    assert resp.headers["Location"].endswith("/offer/pb_welcome2")
    with anon_client.session_transaction() as s:
        flashes = [m for _, m in s.get("_flashes", [])]
    assert "This offer has ended." in flashes


def test_the_picker_cannot_switch_a_closed_offer_back_on():
    """The picker enables Continue once every board is filled in. Without
    this it would re-open an ended offer the moment the numbers were chosen."""
    import pathlib

    script = pathlib.Path("static/brands/lottoexpress/js/offer_picker.js").read_text(encoding="utf-8")

    assert 'submitBtn.disabled = closed || outstanding > 0' in script
