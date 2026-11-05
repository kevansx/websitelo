"""
Joey's decisions on the last old URLs (5 Nov 2026), and Marketing Module offers on the LottosOnline rules.

B1: /direct-opt-in goes to the account's Communication Preferences. The encrypted email in ?eid= stays behind.
B2: the two raffle feeds are retired.
B3: the old /package offers are gone: home page, affiliate credit kept. New offers come from the Module.
"""
from __future__ import annotations

import json

import pytest

from crm_api import CRMClient, CRMError

OLD_OFFERS = (
    "/package?id=FSFPAWJCYTY9BX9E&a=8001&c=15645",
    "/package?id=1NS49V5GVT5KZKBI&a=8003&c=15646",
    "/package?id=SF8AY7GRWOA11UV7",
)


@pytest.mark.parametrize("path", OLD_OFFERS)
def test_an_old_offer_goes_home_for_good(anon_client, stub_crm, path):
    resp = anon_client.get(path)
    assert resp.status_code == 301
    assert resp.headers["Location"] == "/"


def test_an_old_offer_keeps_the_affiliate_credit(anon_client, stub_crm):
    resp = anon_client.get("/package?id=1NS49V5GVT5KZKBI&a=8003&c=15646")

    assert resp.status_code == 301
    assert "abc=8003--15646-" in resp.headers.get("Set-Cookie", "")
    with anon_client.session_transaction() as s:
        assert (s["mkt"]["src"], s["mkt"]["cmp"]) == ("8003", "15646")


def test_any_other_old_url_keeps_the_affiliate_credit_too(anon_client, stub_crm):
    resp = anon_client.get("/package?id=SOMETHINGELSE&a=9001&c=77")

    assert resp.status_code in (301, 302)
    assert "abc=9001--77-" in resp.headers.get("Set-Cookie", "")


@pytest.mark.parametrize("path", ("/direct-opt-in", "/direct-opt-in.php"))
def test_the_old_opt_in_link_goes_to_login_without_the_email_token(anon_client, stub_crm, path):
    resp = anon_client.get(f"{path}?eid=ENCRYPTEDEMAIL")

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")
    assert "account" in resp.headers["Location"]
    assert "ENCRYPTEDEMAIL" not in resp.headers["Location"]


def test_the_old_opt_in_link_opens_the_account_when_signed_in(client, stub_crm):
    resp = client.get("/direct-opt-in?eid=ENCRYPTEDEMAIL")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account")


def test_the_account_page_has_the_communication_preferences(client, stub_crm):
    body = client.get("/account").get_data(as_text=True)
    assert "Communication Preferences" in body


@pytest.mark.parametrize("path", ("/raffle_feed_sat", "/raffle_feed_thu", "/raffle_feed_sat.php", "/raffle_feed_thu.php"))
def test_the_raffle_feeds_are_retired(anon_client, stub_crm, path):
    assert anon_client.get(path).status_code == 404


def test_the_sign_up_complete_page_no_longer_sells_the_old_offer(anon_client, stub_crm):
    resp = anon_client.get("/registration-complete")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "/package" not in body
    assert "12.50" not in body


# --- Marketing Module offers ------------------------------------------------------------------------

POWERBALL = {
    "code": "LO-USPOW",
    "product_code": "LO-USPOW",
    "game_code": "powerball",
    "product_type": "single",
    "price_in_base_cents": 580,
    "base_currency": "EUR",
    "available_ticket_modes": ["standard"],
    "line_schema": [
        {"name": "main", "count": 5, "min": 1, "max": 69},
        {"name": "power", "count": 1, "min": 1, "max": 26},
    ],
}
LINE = {"main": "1,2,3,4,5", "power": 6}


@pytest.fixture
def lo_offer(stub_crm, monkeypatch):
    """A Module offer of one or more Powerball lines, on LottosOnline's own product code, in EUR."""
    games = [{"game_code": "powerball", "game_name": "Powerball", "products": [POWERBALL]}]
    monkeypatch.setattr(CRMClient, "store_games", lambda self, *a, **k: {"games": games})
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [POWERBALL]})

    def install(quantity: int):
        bundle = {
            "bundle_slug": "pb_try",
            "title": "Try Powerball",
            "contents_description": f"{quantity} Powerball lines for a special price",
            "locked_price_base_cents": 250 * quantity,
            "base_currency": "EUR",
            "items": [{"product_code": "LO-USPOW", "quantity": quantity}],
        }

        def fake_bundle(self, slug, *a, **k):
            if str(slug).lower() != "pb_try":
                raise CRMError("CRM HTTP 404: bundle not found", status_code=404)
            return {"bundle": bundle}

        monkeypatch.setattr(CRMClient, "bundle", fake_bundle)

    return install


def test_an_offer_renders_with_the_brands_euro_price(anon_client, lo_offer):
    lo_offer(3)
    body = anon_client.get("/offer/pb_try").get_data(as_text=True)

    assert "3 Powerball lines for a special price" in body
    assert "€7.50" in body
    assert "lottosonline" in body.lower()


def test_an_offer_under_the_sites_minimum_lines_still_reaches_the_crm(client, lo_offer, monkeypatch, caplog):
    """Powerball needs 3 lines on the play page. An offer is a fixed set marketing chose, so it may be fewer:
    without this the customer paid for a click, picked numbers, and was turned away at the last step."""
    lo_offer(1)
    client.post("/offer/pb_try/start", data={"lines_json": json.dumps([LINE])})

    with caplog.at_level("WARNING"):
        client.post("/checkout", data={})

    assert "checkout guard refused" not in caplog.text


def test_the_same_short_ticket_without_an_offer_is_still_refused(client, stub_crm, monkeypatch, caplog):
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [POWERBALL]})
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "LO-USPOW", "lines": [LINE], "options": {},
                            "game_code": "powerball", "game_name": "Powerball"}]

    with caplog.at_level("WARNING"):
        resp = client.post("/checkout", data={})

    assert "checkout guard refused" in caplog.text
    assert resp.headers["Location"].endswith("/cart")


def test_the_offer_marker_does_not_excuse_a_ticket_once_the_offer_is_gone(client, stub_crm, monkeypatch, caplog):
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": [POWERBALL]})
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "LO-USPOW", "lines": [LINE], "options": {},
                            "from_offer": True, "game_code": "powerball", "game_name": "Powerball"}]

    with caplog.at_level("WARNING"):
        client.post("/checkout", data={})

    assert "checkout guard refused" in caplog.text


def test_the_offer_marker_never_reaches_the_crm(client, lo_offer, monkeypatch):
    lo_offer(1)
    sent: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, *a, **k: sent.append(payload) or {"quote": {"currency": "EUR", "items": []}},
    )
    client.get("/offer/pb_try?src=mm&cmp=CAMP1&tid=T1&intent=lifecycle")
    client.post("/offer/pb_try/start", data={"lines_json": json.dumps([LINE])})
    client.get("/cart")

    assert sent, "the cart never quoted"
    assert sent[-1]["bundle_slug"] == "pb_try"
    assert (sent[-1]["cmp"], sent[-1]["tid"]) == ("CAMP1", "T1")
    assert "from_offer" not in json.dumps(sent[-1])
