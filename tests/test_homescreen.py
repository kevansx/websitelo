"""Add to Home Screen + the free Australia Saturday Lotto ticket (lo_homescreen.py)."""
import json

import pytest

import lo_homescreen
from crm_api import CRMClient


@pytest.fixture(autouse=True)
def claims_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lo_homescreen, "DATA", tmp_path / "homescreen_claims.json")
    monkeypatch.setenv("LO_HOMESCREEN_PRODUCT_CODE", "LO-AUTAT-1")


@pytest.fixture
def grants(monkeypatch):
    sent = []
    real = CRMClient._request

    def fake(self, method, path, *a, **k):
        if path.startswith("/api/v1/marketing/incentives/grant-free-ticket"):
            sent.append(k.get("json"))
            return {"success": True, "promo_order_id": 4242}
        return real(self, method, path, *a, **k)

    monkeypatch.setattr(CRMClient, "_request", fake)
    return sent


def _csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s.get("csrf_token")


def _claim(client, token, standalone=True):
    headers = {"X-CSRF-Token": token or ""}
    if standalone:
        headers["X-Display-Mode"] = "standalone"
    return client.post("/homescreen/claim", headers=headers, json={})


def test_the_site_is_installable(anon_client, stub_crm):
    m = anon_client.get("/manifest.webmanifest")
    data = json.loads(m.data)
    assert m.status_code == 200 and data["display"] == "standalone"
    assert data["start_url"] == "/?source=homescreen"
    assert {i["sizes"] for i in data["icons"]} >= {"192x192", "512x512"}
    sw = anon_client.get("/sw.js").get_data(as_text=True)
    assert "caches" not in sw          # network only: a deploy is never hidden behind a cache
    home = anon_client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in home and 'id="loInstall"' in home and "Free ticket" in home


def test_a_logged_in_customer_in_the_app_gets_one_ticket(client, stub_crm, grants):
    token = _csrf(client)
    first = _claim(client, token).get_json()
    second = _claim(client, token).get_json()
    assert first == {"ok": True}
    assert second == {"ok": True, "already": True}
    assert len(grants) == 1
    g = grants[0]
    assert g["product_code"] == "LO-AUTAT-1"
    assert g["idempotency_key"] == "homescreen-1"
    assert len(g["lines"]) == 1 and len(g["lines"][0]["main"].split(",")) == 6
    # the account card now says it has been collected
    assert "Free Saturday Lotto ticket collected" in client.get("/account").get_data(as_text=True)


def test_logged_out_or_in_a_browser_tab_gets_nothing(anon_client, client, stub_crm, grants):
    assert _claim(anon_client, _csrf(anon_client)).get_json()["reason"] == "login_required"
    assert _claim(client, _csrf(client), standalone=False).get_json()["reason"] == "not_installed"
    assert grants == []


def test_a_claim_without_the_form_token_is_refused(client, stub_crm, grants):
    _csrf(client)
    assert _claim(client, "wrong").status_code == 400
    assert grants == []


def test_the_offer_switch(client, stub_crm, grants, monkeypatch):
    monkeypatch.setenv("LO_HOMESCREEN_OFFER", "0")
    assert _claim(client, _csrf(client)).get_json()["reason"] == "offer_off"
    assert grants == []


def test_no_offer_sheet_on_money_pages(client, stub_crm):
    assert 'id="loInstall"' not in client.get("/cart").get_data(as_text=True)


def test_the_ticket_finds_its_product_in_the_real_crm_format(client, stub_crm, grants, monkeypatch):
    # The real /api/v1/store/games (as Lotto Express receives it): products under single_products and the
    # number format as a list of groups. No product code configured: it must be found in the store.
    monkeypatch.delenv("LO_HOMESCREEN_PRODUCT_CODE")
    real_games = [{"game_code": "sat-lotto-au", "game_name": "Saturday Lotto (AU)", "single_products": [
        {"code": "LO-AUTAT", "product_type": "single", "website_enabled": True,
         "line_schema": [{"name": "main", "count": 6, "min": 1, "max": 45}]}]}]
    eng = dict(client.application.config["LO_ENGINE"])
    eng["store_games_cached"] = lambda: real_games
    monkeypatch.setitem(client.application.config, "LO_ENGINE", eng)
    assert _claim(client, _csrf(client)).get_json() == {"ok": True}
    assert grants[0]["product_code"] == "LO-AUTAT"
    nums = [int(x) for x in grants[0]["lines"][0]["main"].split(",")]
    assert len(nums) == 6 and all(1 <= n <= 45 for n in nums)
