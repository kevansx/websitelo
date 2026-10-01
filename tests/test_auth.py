"""
Pre-launch tests for authentication: login (success, bad credentials, missing
fields), logout, registration, forgot password, and the auth gates protecting
customer pages.
"""

from __future__ import annotations

import pytest

from crm_api import CRMClient, CRMError


def test_login_success_sets_session_and_redirects(anon_client, stub_crm):
    resp = anon_client.post("/login", data={"email": "test@example.com", "password": "pw"})
    assert resp.status_code == 302
    with anon_client.session_transaction() as s:
        assert s.get("crm_token") == "test-token"
        assert isinstance(s.get("customer"), dict)


def test_login_bad_credentials_shows_error(anon_client, stub_crm, monkeypatch):
    def bad_login(self, payload):
        raise CRMError("CRM HTTP 401: invalid credentials", status_code=401)

    monkeypatch.setattr(CRMClient, "auth_login", bad_login)
    resp = anon_client.post(
        "/login", data={"email": "test@example.com", "password": "wrong"}, follow_redirects=True
    )
    assert resp.status_code == 200
    with anon_client.session_transaction() as s:
        assert not s.get("crm_token")


def test_login_missing_fields_rejected(anon_client, stub_crm):
    resp = anon_client.post("/login", data={"email": "", "password": ""})
    assert resp.status_code == 302
    with anon_client.session_transaction() as s:
        assert not s.get("crm_token")


def test_logout_clears_session(client, stub_crm):
    resp = client.get("/logout")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert not s.get("crm_token")


def test_register_success_sets_session(anon_client, stub_crm):
    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "new@example.com",
            "password": "Str0ngPassw0rd!",
            "currency": "USD",
            "accept_terms": "1",
        },
    )
    assert resp.status_code == 302
    with anon_client.session_transaction() as s:
        assert s.get("crm_token") == "test-token"


def test_register_crm_failure_redirects_back(anon_client, stub_crm, monkeypatch):
    def bad_register(self, payload):
        raise CRMError("CRM HTTP 409: email exists", status_code=409)

    monkeypatch.setattr(CRMClient, "auth_register", bad_register)
    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "dupe@example.com",
            "password": "Str0ngPassw0rd!",
            "currency": "USD",
            "accept_terms": "1",
        },
    )
    assert resp.status_code == 302
    with anon_client.session_transaction() as s:
        assert not s.get("crm_token")


def test_register_crm_500_shows_friendly_error(anon_client, stub_crm, monkeypatch):
    # The CRM must never leak a raw "Internal Server Error" to the customer.
    def crash(self, payload):
        raise CRMError("CRM HTTP 500: Internal Server Error", status_code=500)

    monkeypatch.setattr(CRMClient, "auth_register", crash)
    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "crash@example.com",
            "password": "Str0ngPassw0rd!",
            "currency": "USD",
            "accept_terms": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Internal Server Error" not in html
    assert "something went wrong on our side" in html


def test_register_crm_500_with_phone_hints_duplicate_phone(anon_client, stub_crm, monkeypatch):
    # Known CRM bug: duplicate phone number crashes register with a 500.
    def crash(self, payload):
        raise CRMError("CRM HTTP 500: Internal Server Error", status_code=500)

    monkeypatch.setattr(CRMClient, "auth_register", crash)
    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "crash2@example.com",
            "password": "Str0ngPassw0rd!",
            "currency": "USD",
            "accept_terms": "1",
            "phone": "+14165550100",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Internal Server Error" not in html
    assert "different phone number" in html


def test_forgot_password_post_accepts_email(anon_client, stub_crm):
    resp = anon_client.post("/forgot-password", data={"email": "test@example.com"})
    assert resp.status_code in (200, 302)


@pytest.mark.parametrize(
    "path",
    ["/account", "/orders", "/orders/1", "/wallet/add-funds", "/legacy-orders"],
)
def test_protected_pages_redirect_anonymous_to_login(anon_client, stub_crm, path):
    resp = anon_client.get(path)
    assert resp.status_code == 302, f"{path} returned {resp.status_code}"
    assert "/login" in resp.headers.get("Location", "")
