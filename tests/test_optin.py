"""Joining the marketing list with a welcome gift pack (lo_optin.py; Joey, 21 Oct 2026): asked on the order page and in
the sign-up box, never in the UAE, Saudi Arabia or Denmark, and the gift comes only with a paid order."""
from __future__ import annotations

import pytest

import lo_optin
import lo_packs
from tests.conftest import TEST_CUSTOMER
from tests.test_cart_checkout import VALID_ADD

ACCOUNT_FORM = {"title": "Ms", "first_name": "Nia", "last_name": "Test", "email": "new@example.com",
                "password": "Str0ngPassw0rd!", "currency": "EUR", "country": "IN", "accept_terms": "1"}
OFFER = "Be first to know when jackpots roll over"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)


def _csrf(client) -> str:
    with client.session_transaction() as s:
        s["csrf_token"] = "tok"
    return "tok"


def _packs(cid: int = 1) -> list[dict]:
    packs = lo_packs.customer_packs(cid)
    return [p for p in packs["sealed"] + packs["opened"] if p.get("type") == "welcome_list"]


# ------------------------------------------------------------------ the order page
def test_the_order_page_offers_the_list(client, stub_crm):
    body = client.get("/orders/1").get_data(as_text=True)
    assert OFFER in body and "welcome gift pack" in body


def test_not_offered_to_someone_already_on_the_list(client, stub_crm):
    with client.session_transaction() as s:
        s["customer"] = {**TEST_CUSTOMER, "notification": {"is_allow_marketing_email": True}}
    assert OFFER not in client.get("/orders/1").get_data(as_text=True)


@pytest.mark.parametrize("country", ["AE", "SA", "DK"])
def test_not_offered_by_account_country(client, stub_crm, country):
    with client.session_transaction() as s:
        s["customer"] = {**TEST_CUSTOMER, "country": country}
    assert OFFER not in client.get("/orders/1").get_data(as_text=True)


@pytest.mark.parametrize("country", ["AE", "SA"])
def test_not_offered_where_the_visitor_is(client, stub_crm, country):
    assert OFFER not in client.get("/orders/1", headers={"X-Geo-Country": country}).get_data(as_text=True)


def test_joining_saves_consent_and_grants_one_gift(client, stub_crm, monkeypatch):
    from crm_api import CRMClient
    sent = []
    monkeypatch.setattr(CRMClient, "customer_update", lambda self, token, payload: sent.append(payload) or {})
    resp = client.post("/account/join-list", data={"csrf_token": _csrf(client), "back": "/orders/1"})
    assert resp.headers["Location"].endswith("/orders/1")
    assert sent and sent[0]["notification"]["is_allow_marketing_email"] is True
    assert lo_optin.get(1)["source"] == "order_page" and lo_optin.get(1)["wording"] == lo_optin.WORDING
    assert len(_packs()) == 1
    body = client.get("/orders/1").get_data(as_text=True)
    assert "Your welcome gift pack is waiting" in body and OFFER not in body
    # asking again changes nothing
    client.post("/account/join-list", data={"csrf_token": _csrf(client), "back": "/orders/1"})
    assert len(_packs()) == 1


def test_joining_needs_the_form_token(client, stub_crm):
    assert client.post("/account/join-list", data={"back": "/orders/1"}).status_code == 400
    assert lo_optin.get(1) is None


def test_no_gift_if_the_crm_did_not_save_consent(client, stub_crm, monkeypatch):
    from crm_api import CRMClient

    def boom(self, token, payload):
        raise RuntimeError("down")
    monkeypatch.setattr(CRMClient, "customer_update", boom)
    client.post("/account/join-list", data={"csrf_token": _csrf(client), "back": "/orders/1"})
    assert lo_optin.get(1) is None and _packs() == []


def test_joining_from_the_uae_is_refused(client, stub_crm):
    client.post("/account/join-list", data={"csrf_token": _csrf(client), "back": "/orders/1"},
                headers={"X-Geo-Country": "AE"})
    assert lo_optin.get(1) is None and _packs() == []


def test_back_must_stay_on_the_site(client, stub_crm):
    resp = client.post("/account/join-list", data={"csrf_token": _csrf(client), "back": "//evil.example/"})
    assert resp.headers["Location"].endswith("/account")


# ------------------------------------------------------------------ the sign-up box
def test_the_sign_up_box_has_the_new_wording(anon_client, stub_crm):
    body = anon_client.get("/create-account").get_data(as_text=True)
    assert "Yes, send me jackpot news and members' offers by email." in body
    assert "Reminders and Promotions" not in body


@pytest.mark.parametrize("country", ["AE", "SA"])
def test_the_sign_up_box_is_not_shown_in_the_uae_or_saudi_arabia(anon_client, stub_crm, country):
    body = anon_client.get("/create-account", headers={"X-Geo-Country": country}).get_data(as_text=True)
    assert 'name="marketing_opt_in"' not in body


def test_ticking_the_box_grants_the_gift_with_the_first_order_only(anon_client, stub_crm):
    anon_client.post("/create-account", data={**ACCOUNT_FORM, "marketing_opt_in": "on"})
    row = lo_optin.get(1)
    assert row and row["source"] == "signup" and not row["gift_granted_at"]
    assert _packs() == []                       # no order, no gift
    anon_client.post("/cart/add", data=VALID_ADD)
    anon_client.post("/checkout")
    assert len(_packs()) == 1 and lo_optin.get(1)["gift_granted_at"]
    anon_client.post("/cart/add", data=VALID_ADD)
    anon_client.post("/checkout")
    assert len(_packs()) == 1


def test_not_ticking_the_box_records_nothing(anon_client, stub_crm):
    anon_client.post("/create-account", data=ACCOUNT_FORM)
    assert lo_optin.get(1) is None


def test_on_order_never_gifts_denmark():
    lo_optin.record(5, "signup")
    assert lo_optin.on_order({"id": 5, "country": "DK"}) is None
