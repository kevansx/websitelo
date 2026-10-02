"""Gift packs (lo_packs.py): triggers, the server-side gift draw, idempotent opening, the routes."""
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

import lo_packs
from crm_api import CRMClient

GAMES = [  # the real CRM shape: single_products, list line_schema
    {"game_code": gc, "game_name": name, "single_products": [
        {"code": code, "product_type": "single", "website_enabled": True,
         "line_schema": [{"name": "main", "count": 6, "min": 1, "max": 45}]}]}
    for gc, name, code in (("weekday-windfall-au", "Weekday Windfall", "LO-AUMON"),
                           ("sat-lotto-au", "Saturday Lotto", "LO-AUTAT"),
                           ("bonoloto", "BonoLoto", "LO-ESBON"),
                           ("powerball-au", "Australia Powerball", "LO-AUPOW"),
                           ("euromillions", "EuroMillions", "LO-EUEUR"))
]


@pytest.fixture(autouse=True)
def packs_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))


@pytest.fixture
def grants(monkeypatch):
    sent = []
    real = CRMClient._request

    def fake(self, method, path, *a, **k):
        if path.startswith("/api/v1/marketing/incentives/grant-free-ticket"):
            sent.append(k.get("json"))
            return {"success": True, "promo_order_id": 7000 + len(sent)}
        return real(self, method, path, *a, **k)

    monkeypatch.setattr(CRMClient, "_request", fake)
    return sent


def blank(**kw):
    a = {"orders_count": 0, "first_order_at": None, "games": {}, "played_raffle": False, "played_long": False,
         "seen_orders": set()}
    a.update(kw)
    return a


def facts(games=("euromillions",), multi_game=None):
    return {"games": set(games), "multi_draw": multi_game is not None, "multi_game": multi_game}


NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


# ------------------------------------------------------------------ triggers
def test_first_order_is_first_play_only():
    assert lo_packs.triggers_for(blank(), facts(), NOW) == ["first_play"]


def test_return_within_14_days_and_not_after():
    first = (NOW - timedelta(days=10)).isoformat()
    late = (NOW - timedelta(days=20)).isoformat()
    played = {"euromillions": 1}
    assert "return" in lo_packs.triggers_for(blank(orders_count=1, first_order_at=first, games=played), facts(), NOW)
    assert "return" not in lo_packs.triggers_for(blank(orders_count=1, first_order_at=late, games=played), facts(), NOW)


def test_explorer_is_a_new_lottery_after_the_first_order():
    before = blank(orders_count=3, first_order_at="2026-01-01T00:00:00Z", games={"euromillions": 3})
    assert lo_packs.triggers_for(before, facts(("bonoloto",)), NOW) == ["explorer"]
    assert lo_packs.triggers_for(before, facts(("euromillions",)), NOW) == []


def test_long_play_is_the_first_multi_draw_tier_purchase():
    before = blank(orders_count=2, first_order_at="2026-01-01T00:00:00Z", games={"euromillions": 2})
    assert lo_packs.triggers_for(before, facts(multi_game="euromillions"), NOW) == ["long_play"]
    assert lo_packs.triggers_for(dict(before, played_long=True), facts(multi_game="euromillions"), NOW) == []


def test_a_two_week_mega_millions_tier_counts_without_weekdays():
    # brief 2, 7.3: a tier order sends draw_weeks and maybe no weekdays; it must still be Long Play
    f = lo_packs._order_facts([{"game_code": "megamillions", "product_code": "LO-USMEG-4", "ticket_mode": "multi_draw",
                                "draw_weeks": 2}])
    assert f == {"games": {"megamillions"}, "multi_draw": True, "multi_game": "megamillions"}
    assert lo_packs._order_facts([{"game_code": "megamillions", "product_code": "LO-USMEG"}])["multi_draw"] is False


def test_no_raffle_or_welcome_packs():
    assert lo_packs.PACK_TYPES == ("first_play", "return", "explorer", "long_play", "regular")
    before = blank(orders_count=2, first_order_at="2026-01-01T00:00:00Z", games={"euromillions": 2})
    assert lo_packs.triggers_for(before, lo_packs._order_facts([{"game_code": "raffle-es", "kind": "raffle"}]), NOW) == ["explorer"]


@pytest.mark.parametrize("nth,earns", [(4, False), (5, True), (6, False), (7, False), (8, True), (11, True), (12, False)])
def test_regular_on_the_5th_then_every_3rd(nth, earns):
    before = blank(orders_count=nth - 1, first_order_at="2026-01-01T00:00:00Z", games={"euromillions": 9})
    assert ("regular" in lo_packs.triggers_for(before, facts(), NOW)) is earns


def test_same_order_twice_earns_nothing_the_second_time():
    one = lo_packs.on_order_placed(customer_id=1, order_id=55, items=[{"game_code": "euromillions"}])
    two = lo_packs.on_order_placed(customer_id=1, order_id=55, items=[{"game_code": "euromillions"}])
    assert [p["type"] for p in one] == ["first_play"] and two == []


def test_long_standing_customers_never_get_first_play():
    seeded = lambda: blank(orders_count=41, first_order_at="2020-01-01T00:00:00Z", games={"euromillions": 40})
    earned = lo_packs.on_order_placed(customer_id=2, order_id=1, items=[{"game_code": "euromillions"}], seed=seeded)
    assert earned == []


# ------------------------------------------------------------------ the gift
def test_gift_prefers_lotteries_never_played_and_is_playable():
    pack = {"type": "first_play", "gift_json": None}
    seen = set()
    for i in range(60):
        g = lo_packs.choose_gift(pack, {"sat-lotto-au": 3}, GAMES, rng=random.Random(i))
        assert g["shape"] == "A" and g["game_code"] != "sat-lotto-au" and g["lines"] == 5
        seen.add(g["game_code"])
    assert seen == {"weekday-windfall-au", "bonoloto", "powerball-au"}   # random within the chosen three


def test_a_new_customer_can_get_any_of_the_four():
    seen = {lo_packs.choose_gift({"type": "first_play", "gift_json": None}, {}, GAMES, rng=random.Random(i))["game_code"]
            for i in range(80)}
    assert seen == {"weekday-windfall-au", "sat-lotto-au", "bonoloto", "powerball-au"}


def test_order_page_opens_a_just_earned_pack(client, stub_crm, monkeypatch):
    pack = _earn(customer_id=_customer_id(client))
    with client.session_transaction() as s:
        s["lo_pack_just_earned"] = pack["pack_id"]
    monkeypatch.setattr(CRMClient, "order", lambda self, *a, **k: {"order": {"id": 1, "status": "paid", "tickets": []}}, raising=False)
    html = client.get("/orders/1").get_data(as_text=True)
    assert 'id="loPack"' in html and "lo-pack--overlay" in html
    assert 'id="loPack"' not in client.get("/orders/1").get_data(as_text=True)     # once only


def test_all_four_played_falls_back_to_two_lines_on_the_favourite():
    played = {"weekday-windfall-au": 1, "sat-lotto-au": 2, "bonoloto": 1, "powerball-au": 1, "euromillions": 9}
    g = lo_packs.choose_gift({"type": "regular", "gift_json": None}, played, GAMES)
    assert g == {**g, "shape": "B", "game_code": "euromillions", "lines": 2}


def test_shape_b_grants_on_the_base_product_never_a_tier_or_subscription():
    games = [{"game_code": "powerball", "game_name": "Powerball", "single_products": [
        {"code": "LO-USPOW-5W", "available_ticket_modes": ["standard", "multi_draw"], "line_schema": []},
        {"code": "LO-USPOW-W", "product_type": "syndicate", "available_ticket_modes": ["subscription"]},
        {"code": "LO-USPOW", "available_ticket_modes": ["standard"], "website_default": True,
         "line_schema": [{"name": "main", "count": 5, "min": 1, "max": 69}]}]}]
    g = lo_packs.choose_gift({"type": "long_play", "gift_json": json.dumps({"_hint_game": "powerball"})}, {}, games)
    assert g["product_code"] == "LO-USPOW" and g["lines"] == 2


def test_long_play_gift_is_two_lines_on_that_lottery():
    g = lo_packs.choose_gift({"type": "long_play", "gift_json": json.dumps({"_hint_game": "euromillions"})}, {}, GAMES)
    assert (g["shape"], g["game_code"], g["lines"]) == ("B", "euromillions", 2)


def test_the_card_never_shows_amounts_or_win_words():
    card = lo_packs.card_text({"game_name": "Saturday Lotto", "lines": 5})
    text = " ".join(card.values()).lower()
    assert card["sub"] == "5 free lines"
    assert not any(w in text for w in ("win", "prize", "jackpot", "lucky", "€", "eur"))
    assert len(card["title"]) <= 22 and len(card["sub"]) <= 18 and len(card["expiry"]) <= 28


# ------------------------------------------------------------------ opening
def _earn(customer_id=1, order_id=1):
    return lo_packs.on_order_placed(customer_id=customer_id, order_id=order_id, items=[{"game_code": "euromillions"}])[0]


def test_open_grants_once_with_the_pack_key(grants, stub_crm):
    pack = _earn()
    crm = CRMClient.__new__(CRMClient)
    a = lo_packs.open_pack(pack["pack_id"], customer_id=1, crm=crm, games=GAMES)
    b = lo_packs.open_pack(pack["pack_id"], customer_id=1, crm=crm, games=GAMES)
    assert len(grants) == 1 and a["gift"] == b["gift"] and a["state"] == "opened"
    g = grants[0]
    assert g["idempotency_key"] == f"pack-{pack['pack_id']}" and g["customer_id"] == 1
    assert len(g["lines"]) == 5 and len(g["lines"][0]["main"].split(",")) == 6


def test_a_failed_grant_leaves_the_pack_sealed_and_retries_the_same_gift(monkeypatch, stub_crm):
    pack = _earn()
    calls = []

    def flaky(self, method, path, *a, **k):
        calls.append(k["json"])
        if len(calls) == 1:
            raise RuntimeError("CRM down")
        return {"success": True, "promo_order_id": 1}
    monkeypatch.setattr(CRMClient, "_request", flaky)
    crm = CRMClient.__new__(CRMClient)
    with pytest.raises(lo_packs.PackError):
        lo_packs.open_pack(pack["pack_id"], customer_id=1, crm=crm, games=GAMES)
    assert lo_packs.get_pack(pack["pack_id"])["state"] == "sealed"
    lo_packs.open_pack(pack["pack_id"], customer_id=1, crm=crm, games=GAMES)
    assert calls[0]["product_code"] == calls[1]["product_code"]           # the draw was recorded, not redrawn
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]


def test_another_customer_cannot_open_it(grants, stub_crm):
    pack = _earn(customer_id=1)
    with pytest.raises(lo_packs.PackError):
        lo_packs.open_pack(pack["pack_id"], customer_id=2, crm=CRMClient.__new__(CRMClient), games=GAMES)
    assert grants == []


def test_sealed_packs_open_themselves_after_14_days(grants, stub_crm, monkeypatch):
    pack = _earn()
    monkeypatch.setattr(lo_packs, "_now", lambda: datetime.now(timezone.utc) + timedelta(days=15))
    assert lo_packs.auto_open_expired(crm=CRMClient.__new__(CRMClient), games=GAMES) == {"opened": 1, "failed": 0}
    assert lo_packs.get_pack(pack["pack_id"])["state"] == "auto_opened" and len(grants) == 1


# ------------------------------------------------------------------ the web side
def _csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s.get("csrf_token")


def _with_games(client, monkeypatch):
    eng = dict(client.application.config["LO_ENGINE"])
    eng["store_games_cached"] = lambda: GAMES
    monkeypatch.setitem(client.application.config, "LO_ENGINE", eng)


def _customer_id(client):
    with client.session_transaction() as s:
        return int(s["customer"]["id"])


def test_open_by_fetch_returns_the_card(client, stub_crm, grants, monkeypatch):
    _with_games(client, monkeypatch)
    pack = _earn(customer_id=_customer_id(client))
    token = _csrf(client)
    r = client.post(f"/packs/{pack['pack_id']}/open", headers={"Accept": "application/json", "X-CSRF-Token": token})
    d = r.get_json()
    assert d["ok"] and d["card"]["sub"] == "5 free lines" and "Your gift:" in d["announce"]
    again = client.post(f"/packs/{pack['pack_id']}/open", headers={"Accept": "application/json", "X-CSRF-Token": token})
    assert again.get_json()["card"] == d["card"] and len(grants) == 1


def test_without_javascript_the_form_post_still_grants(client, stub_crm, grants, monkeypatch):
    _with_games(client, monkeypatch)
    pack = _earn(customer_id=_customer_id(client))
    r = client.post(f"/packs/{pack['pack_id']}/open", data={"csrf_token": _csrf(client)})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/packs/{pack['pack_id']}")
    page = client.get(f"/packs/{pack['pack_id']}").get_data(as_text=True)
    assert "5 free lines" in page and len(grants) == 1


def test_open_needs_the_form_token(client, stub_crm, grants):
    pack = _earn(customer_id=_customer_id(client))
    _csrf(client)
    assert client.post(f"/packs/{pack['pack_id']}/open", data={"csrf_token": "wrong"}).status_code == 400
    assert grants == []


def test_account_lists_sealed_packs_with_days_left(client, stub_crm):
    _earn(customer_id=_customer_id(client))
    html = client.get("/account/packs").get_data(as_text=True)
    assert "A gift pack for you" in html and "Opens by itself in 13 days" in html or "in 14 days" in html


def test_pages_need_a_login(anon_client, stub_crm):
    assert anon_client.get("/account/packs").status_code == 302


def test_a_pack_failure_never_breaks_checkout(client, stub_crm, monkeypatch):
    def boom(**k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(lo_packs, "on_order_placed", boom)
    with client.application.test_request_context():
        from flask import session
        session["customer"] = {"id": 1}
        client.application.config["LO_PACKS_AFTER_CHECKOUT"](token="t", order_id=9, items=[])   # no exception
