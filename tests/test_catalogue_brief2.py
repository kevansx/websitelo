"""Build brief 2, part 1 (the pricing hole) and part 3 (catalogue rules), against the CRM reply's catalogue.

Part 9's pricing-hole checks are 5, 6 and 10: "If any of them fails, do not cut over."
"""
import json
import re

import pytest

import fake_crm
import lo_lotteries
import lo_store
from crm_api import CRMClient

GAMES = [fake_crm._game(l) for l in lo_lotteries.LOTTERIES if l.sells]
BY_GAME = {g["game_code"]: g for g in GAMES}
PRODUCTS = [p for g in GAMES for p in g["products"]]


@pytest.fixture
def catalogue(monkeypatch, stub_crm):
    monkeypatch.setattr(CRMClient, "store_game", lambda self, code, *a, **k: {"game": BY_GAME[code]})
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": PRODUCTS})
    monkeypatch.setattr(CRMClient, "store_games", lambda self, *a, **k: {"games": GAMES})
    return GAMES


def _lines(n, game="powerball"):
    if game == "sat-lotto-au":
        return json.dumps([{"main": "1,2,3,4,5,6"}] * n)
    return json.dumps([{"main": "1,2,3,4,5", "powerball": "6"}] * n)


def _add(client, code, *, mode=None, weeks=None, n=3, game="powerball"):
    data = {"product_code": code, "game_code": game, "game_name": "x", "lines_json": _lines(n, game), "options_json": "{}"}
    if mode:
        data["ticket_mode"] = mode
    if weeks is not None:
        data["draw_weeks"] = str(weeks)
    client.post("/cart/add", data=data)
    with client.session_transaction() as s:
        return list(s.get("cart_items") or [])


# ------------------------------------------------------------------ the classifier
def test_every_catalogue_product_is_classified():
    kinds = {lo_store.product_code(p): lo_store.product_kind(p) for p in PRODUCTS}
    assert kinds["LO-USPOW"] == "base" and kinds["LO-USPOW-5W"] == "tier" and kinds["LO-USPOW-W"] == "subscription"
    assert kinds["LO-USMEG-8"] == "tier" and "LO-USMEG-16" not in kinds          # Mega Millions has no 16
    assert None not in kinds.values()
    assert {lo_store.tier_draw_weeks(p) for p in PRODUCTS if lo_store.product_code(p) == "LO-ESELG-16"} == {16}


def test_fields_and_code_disagreeing_is_not_sellable():
    assert lo_store.product_kind({"code": "LO-USPOW", "available_ticket_modes": ["standard", "multi_draw"]}) is None
    assert lo_store.product_kind({"code": "LO-USPOW-3W", "available_ticket_modes": ["standard"]}) is None
    assert lo_store.product_kind({"code": "LO-USPOW-3W", "available_ticket_modes": ["standard", "multi_draw"],
                                  "draw_weeks": 4}) is None       # the CRM's lock disagrees with the CRM reply


# ------------------------------------------------------------------ check 10: one product, structured data EUR 5.20
def test_powerball_page_sells_one_product_at_5_20(client, catalogue):
    html = client.get("/lottery-tickets/us-powerball").get_data(as_text=True)
    assert re.search(r'id="leProductCode" name="product_code" value="LO-USPOW"', html)
    assert "<select" not in html.split('id="singlePlayBetForm"')[1].split("</form>")[0]
    ld = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
    prices = [d["offers"]["price"] for d in ld if d.get("@type") == "Product"]
    assert prices == ["5.20"]
    picker = json.loads(re.search(r'<script id="lePickerProducts" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert all(not p["code"].endswith("-W") for p in picker)          # never the subscription
    assert "1 week" in html and "3 weeks" in html and "5 weeks" in html and "16 draws" not in html


def test_mega_millions_offers_4_and_8_draws_not_16(client, catalogue):
    html = client.get("/lottery-tickets/mega-millions").get_data(as_text=True)
    assert "4 draws" in html and "8 draws" in html and "16 draws" not in html


@pytest.mark.parametrize("slug", ["bonoloto", "millionaire4life", "fr-lotto"])
def test_single_draw_lotteries_have_no_duration_picker(client, catalogue, slug):
    assert 'name="lo_duration"' not in client.get(f"/lottery-tickets/{slug}").get_data(as_text=True)


# ------------------------------------------------------------------ checks 5 and 6: the server guard
def test_check5_a_tier_sent_as_standard_is_refused(client, catalogue):
    assert _add(client, "LO-USPOW-5W", mode="standard") == []
    assert _add(client, "LO-USPOW-5W") == []


def test_check6_the_base_sent_as_multi_draw_is_refused(client, catalogue):
    assert _add(client, "LO-USPOW", mode="multi_draw", weeks=3) == []


def test_a_tier_needs_its_locked_draw_weeks(client, catalogue):
    assert _add(client, "LO-USPOW-3W", mode="multi_draw", weeks=5) == []
    cart = _add(client, "LO-USPOW-3W", mode="multi_draw", weeks=3)
    assert cart[-1]["product_code"] == "LO-USPOW-3W" and cart[-1]["ticket_mode"] == "multi_draw" and cart[-1]["draw_weeks"] == 3


def test_a_subscription_never_goes_in_the_ticket_cart(client, catalogue):
    assert _add(client, "LO-USPOW-W", mode="subscription") == []


def test_an_unknown_product_is_refused(client, catalogue):
    assert _add(client, "LO-NOPE") == []


def test_checkout_refuses_a_tampered_cart(client, catalogue):
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "LO-USPOW-5W", "lines": json.loads(_lines(3)),
                            "options": {}, "game_code": "powerball", "game_name": "Powerball"}]
    called = []
    import crm_api
    orig = crm_api.CRMClient.checkout_submit
    try:
        crm_api.CRMClient.checkout_submit = lambda *a, **k: called.append(1) or {"order_id": 1}
        r = client.post("/checkout")
    finally:
        crm_api.CRMClient.checkout_submit = orig
    assert r.status_code == 302 and r.headers["Location"].endswith("/cart") and called == []


# ------------------------------------------------------------------ part 3: rules
def test_saturday_lotto_needs_5_lines(client, catalogue):
    assert _add(client, "LO-AUTAT", n=4, game="sat-lotto-au") == []
    assert len(_add(client, "LO-AUTAT", n=5, game="sat-lotto-au")[-1]["lines"]) == 5


def test_add_ons_are_never_sent(client, catalogue):
    data = {"product_code": "LO-USPOW", "game_code": "powerball", "game_name": "x", "lines_json": _lines(3),
            "options_json": json.dumps({"powerplay": True, "_weeks": 1})}
    client.post("/cart/add", data=data)
    with client.session_transaction() as s:
        assert s["cart_items"][-1]["options"] == {"_weeks": 1}


def test_german_lotto_superzahl_is_not_picked():
    schema = [{"name": "main", "count": 6, "min": 1, "max": 49}, {"name": "super", "count": 1, "min": 0, "max": 9}]
    assert [g["name"] for g in lo_store.pickable_schema("lotto-6aus49", schema)] == ["main"]
    assert set(lo_store.quick_pick(schema, "lotto-6aus49")) == {"main"}


def test_new_game_codes():
    assert lo_lotteries.by_slug("euromillions").game_code == "euromillions-at"
    assert lo_lotteries.by_slug("la-primitiva").game_code == "la-primitiva"
    assert lo_lotteries.by_slug("millionaire4life").game_code == "millionaire-for-life"


def test_cash4life_goes_to_millionaire_for_life(anon_client, stub_crm):
    r = anon_client.get("/lottery-tickets/cash4life")
    assert r.status_code == 301 and r.headers["Location"].endswith("/lottery-tickets/millionaire4life")
