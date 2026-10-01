"""
The set-password shortcut.

The Marketing Module creates customers who have never had a password and mails
them a campaign link carrying `spt`. This lets them choose one on the way to
paying instead of registering from scratch.

It is a shortcut, not a gate. Every failure in here has to end with the customer
still able to buy, because they arrive holding a full cart.
"""

from __future__ import annotations

import json

import pytest

from crm_api import CRMClient, CRMError

from test_offers import _bundle, catalog, serve_bundle  # noqa: F401 - fixtures


TOKEN = "spt_abcdefghijklmnop1234567890"
ONE_LINE = json.dumps([{"main": "1,2,3,4,5", "power": 6}])


@pytest.fixture
def welcome_offer(serve_bundle):  # noqa: F811
    serve_bundle(_bundle("PB_Welcome2", [{"product_code": "PSX-W", "quantity": 1}]))


@pytest.fixture
def token_is(monkeypatch):
    def install(valid: bool):
        monkeypatch.setattr(CRMClient, "auth_set_password_check", lambda self, token: {"valid": valid})

    return install


def _start(client, spt: str | None = TOKEN):
    """Land on the offer with a token, choose numbers, and press buy."""
    client.get("/offer/PB_Welcome2" + (f"?spt={spt}" if spt else ""))
    return client.post("/offer/PB_Welcome2/start", data={"lines_json": ONE_LINE})


def test_a_valid_token_offers_the_shortcut_on_the_way_to_paying(anon_client, welcome_offer, token_is):
    token_is(True)

    resp = _start(anon_client)

    assert "/set-password" in resp.headers["Location"]
    assert "next=/cart" in resp.headers["Location"]


def test_a_dead_token_leaves_the_ordinary_journey_alone(anon_client, welcome_offer, token_is):
    """A shortcut that fails must never cost the sale."""
    token_is(False)

    resp = _start(anon_client)

    assert resp.headers["Location"].endswith("/cart")


def test_a_declined_token_says_why_in_the_log(anon_client, welcome_offer, monkeypatch, caplog):
    """
    The customer is told nothing, by design. So a campaign having every token
    refused looks exactly like a campaign nobody clicked unless the reason is
    written down somewhere.
    """
    monkeypatch.setattr(
        CRMClient, "auth_set_password_check", lambda self, token: {"valid": False, "reason": "has_password"}
    )

    with caplog.at_level("INFO"):
        _start(anon_client)

    assert "has_password" in caplog.text
    assert TOKEN not in caplog.text


def test_the_check_failing_outright_does_not_block_the_purchase(anon_client, welcome_offer, monkeypatch):
    monkeypatch.setattr(
        CRMClient,
        "auth_set_password_check",
        lambda self, token: (_ for _ in ()).throw(CRMError("CRM HTTP 500", status_code=500)),
    )

    resp = _start(anon_client)

    assert resp.headers["Location"].endswith("/cart")


def test_a_link_with_no_token_behaves_exactly_as_before(anon_client, welcome_offer, stub_crm, caplog):
    with caplog.at_level("INFO"):
        resp = _start(anon_client, spt=None)

    assert resp.headers["Location"].endswith("/cart")
    # Both failures land an anonymous customer on the cart, so the log has to
    # separate "no token arrived" from "the token was refused".
    assert "no token on this journey" in caplog.text


def test_a_signed_in_customer_is_never_sent_to_set_a_password(client, welcome_offer, token_is):
    token_is(True)

    resp = _start(client)

    assert resp.headers["Location"].endswith("/cart")


def test_the_token_does_not_stay_in_the_address_bar(anon_client, stub_crm):
    """It rides in on the URL. Leaving it there puts a credential in the browser
    history and in the referrer of every asset the page loads."""
    resp = anon_client.get(f"/set-password?spt={TOKEN}&next=/cart")

    assert resp.status_code == 302
    assert "spt" not in resp.headers["Location"]

    landed = anon_client.get(resp.headers["Location"])
    assert landed.status_code == 200
    assert TOKEN not in landed.get_data(as_text=True)


def test_the_page_refuses_to_leak_the_token_or_be_indexed(anon_client, stub_crm):
    anon_client.get(f"/set-password?spt={TOKEN}")

    resp = anon_client.get("/set-password")

    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"
    assert 'content="noindex, nofollow"' in resp.get_data(as_text=True)


def test_the_page_says_set_and_never_reset(anon_client, stub_crm):
    """These customers have never had a password, and "reset" reads as an error
    message about an account they do not know they have."""
    anon_client.get(f"/set-password?spt={TOKEN}")

    body = anon_client.get("/set-password").get_data(as_text=True)

    assert "Create your password to finish your order." in body
    assert "reset" not in body.lower()


def test_the_rules_are_shown_before_they_type(anon_client, stub_crm):
    anon_client.get(f"/set-password?spt={TOKEN}")

    body = anon_client.get("/set-password").get_data(as_text=True)

    assert "at least 8 characters" in body


def test_only_the_campaign_page_answers_on_the_set_password_url(anon_client):
    """
    The legacy PHP shim used to claim bare `/set-password` as well, so two
    endpoints sat on one rule and the campaign's page won only on registration
    order. The losing outcome was silent and was precisely the dead end this
    flow exists to remove: a 301 to `/reset-password`, telling someone to reset
    a password they have never had.
    """
    from app import app as flask_app

    claimants = [
        rule.endpoint
        for rule in flask_app.url_map.iter_rules()
        if str(rule.rule) == "/set-password" and "GET" in rule.methods
    ]

    assert claimants == ["set_password"]
    # The .php spelling is a genuine legacy URL and still redirects.
    assert anon_client.get("/set-password.php").status_code == 301


def test_arriving_without_a_token_goes_to_the_normal_sign_in(anon_client, stub_crm):
    resp = anon_client.get("/set-password?next=/cart")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    assert "next=/cart" in resp.headers["Location"]


def test_setting_a_password_signs_them_in_and_lands_them_on_payment(anon_client, stub_crm, monkeypatch):
    """No interstitial. The point of the shortcut is that they land on payment."""
    sent: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "auth_set_password",
        lambda self, **kw: sent.append(kw) or {"ok": True, "token": "bearer-xyz", "customer_id": 7},
    )

    anon_client.get(f"/set-password?spt={TOKEN}")
    resp = anon_client.post(
        "/set-password",
        data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"},
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/cart")
    assert sent == [{"token": TOKEN, "password": "Passw0rd!", "password_confirm": "Passw0rd!"}]
    with anon_client.session_transaction() as s:
        assert s["crm_token"] == "bearer-xyz"
        assert s["customer"]
        assert "set_password_token" not in s


def test_a_bearer_without_a_readable_profile_still_signs_them_in(anon_client, stub_crm, monkeypatch):
    """Losing the order over a follow-up profile call would defeat the shortcut."""
    monkeypatch.setattr(
        CRMClient, "auth_set_password", lambda self, **kw: {"ok": True, "token": "bearer-xyz", "customer_id": 7}
    )
    monkeypatch.setattr(
        CRMClient, "auth_me", lambda self, token: (_ for _ in ()).throw(CRMError("CRM HTTP 500", status_code=500))
    )

    anon_client.get(f"/set-password?spt={TOKEN}")
    anon_client.post("/set-password", data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"})

    with anon_client.session_transaction() as s:
        assert s["crm_token"] == "bearer-xyz"
        assert s["customer"] == {"id": 7}


def test_passwords_that_do_not_match_are_caught_on_the_server_too(anon_client, stub_crm, monkeypatch):
    called: list[dict] = []
    monkeypatch.setattr(CRMClient, "auth_set_password", lambda self, **kw: called.append(kw))

    anon_client.get(f"/set-password?spt={TOKEN}")
    resp = anon_client.post(
        "/set-password", data={"password": "Passw0rd!", "password_confirm": "Different1!", "next": "/cart"}
    )

    assert "/set-password" in resp.headers["Location"]
    assert not called


def _refuse(reason: str):
    def fake(self, **kw):
        raise CRMError("refused", status_code=400, payload={"ok": False, "reason": reason})

    return fake


@pytest.mark.parametrize("reason", ["weak", "mismatch"])
def test_a_password_the_crm_rejects_gets_another_go_at_the_form(anon_client, stub_crm, monkeypatch, reason):
    monkeypatch.setattr(CRMClient, "auth_set_password", _refuse(reason))

    anon_client.get(f"/set-password?spt={TOKEN}")
    resp = anon_client.post(
        "/set-password", data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"}
    )

    assert "/set-password" in resp.headers["Location"]
    with anon_client.session_transaction() as s:
        assert s.get("set_password_token") == TOKEN, "the token was thrown away over a fixable mistake"


@pytest.mark.parametrize("reason", ["used", "expired", "has_password", "unknown", ""])
def test_a_token_that_cannot_work_hands_them_to_the_normal_sign_in(anon_client, stub_crm, monkeypatch, reason):
    """Never leave them on a dead page with a live cart."""
    monkeypatch.setattr(CRMClient, "auth_set_password", _refuse(reason))

    anon_client.get(f"/set-password?spt={TOKEN}")
    resp = anon_client.post(
        "/set-password", data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"}
    )

    assert "/login" in resp.headers["Location"]
    assert "next=/cart" in resp.headers["Location"]
    with anon_client.session_transaction() as s:
        assert "set_password_token" not in s


def test_the_campaign_survives_the_set_password_detour(anon_client, welcome_offer, token_is, monkeypatch):
    """
    The likeliest thing to break. Set-password is a redirect in the middle of the
    journey, and marketing context held only in the URL is dropped there — which
    would make the campaign unmeasurable while looking like it worked.
    """
    token_is(True)
    monkeypatch.setattr(
        CRMClient, "auth_set_password", lambda self, **kw: {"ok": True, "token": "bearer-xyz", "customer_id": 7}
    )
    quotes: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "checkout_quote",
        lambda self, payload, *a, **k: quotes.append(payload) or {"quote": {"currency": "GBP", "items": []}},
    )

    anon_client.get(f"/offer/PB_Welcome2?src=cbm&cmp=CB-Meta-0426&tid=c3_ut4g5&intent=acquisition&spt={TOKEN}")
    anon_client.post("/offer/PB_Welcome2/start", data={"lines_json": ONE_LINE})
    anon_client.get("/set-password")
    anon_client.post("/set-password", data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"})
    anon_client.get("/cart")

    assert quotes, "the cart never quoted"
    payload = quotes[-1]
    assert (payload["src"], payload["cmp"], payload["tid"]) == ("cbm", "CB-Meta-0426", "c3_ut4g5")
    assert payload["bundle_slug"] == "PB_Welcome2"


def test_the_token_is_never_written_to_the_log(anon_client, stub_crm, monkeypatch, caplog):
    monkeypatch.setattr(CRMClient, "auth_set_password", _refuse("expired"))

    with caplog.at_level("DEBUG"):
        anon_client.get(f"/set-password?spt={TOKEN}")
        anon_client.post(
            "/set-password", data={"password": "Passw0rd!", "password_confirm": "Passw0rd!", "next": "/cart"}
        )

    assert TOKEN not in caplog.text
    assert "expired" in caplog.text, "the reason should be logged even though the token is not"
