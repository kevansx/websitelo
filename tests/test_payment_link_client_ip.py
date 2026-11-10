"""
Payment-link calls carry the payer's public IPv4 as `client_ip`.

The CRM's API of 4 Nov 2026 requires `client_ip` on the email-link context and
hosted-start calls. Lottos Online sent none, the suspected cause of the same
failures on Winnow (Nov 2026). Only a public IPv4 is sent. For an IPv6 customer
or a private address, the field is left out and the CRM falls back to the
brand's configured address.
"""

from __future__ import annotations

import pytest

from crm_api import CRMClient
from tests.test_payment_link import CURP, PAY_URL, RFC, TOKEN, calls  # noqa: F401


@pytest.fixture
def contexts(monkeypatch, stub_crm):
    seen: list[str | None] = []
    answer = {
        "success": True,
        "intent": {"id": 456, "status": "pending", "processor": "bitolo", "amount_cents": 5000, "currency": "USD"},
    }

    def context(self, link_token, client_ip=None):
        seen.append(client_ip)
        return answer

    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_context", context)
    return seen


@pytest.mark.parametrize(
    "headers, environ, want",
    [
        ({"X-Forwarded-For": "86.48.8.213, 10.0.0.1"}, {}, "86.48.8.213"),
        ({"X-Forwarded-For": "2001:db8::1"}, {}, None),
        ({}, {"REMOTE_ADDR": "10.0.0.4"}, None),
    ],
)
def test_opening_the_link_sends_only_a_public_ipv4(anon_client, contexts, calls, headers, environ, want):  # noqa: F811
    anon_client.get(f"{PAY_URL}?token={TOKEN}", headers=headers, environ_base=environ, follow_redirects=True)

    assert contexts and contexts[-1] == want


def test_pay_now_sends_the_public_ipv4(anon_client, contexts, calls):  # noqa: F811
    anon_client.get(f"{PAY_URL}?token={TOKEN}&mode=bitolo")

    anon_client.post(PAY_URL, data={"rfc": RFC, "curp": CURP}, headers={"X-Forwarded-For": "86.48.8.213"})

    assert calls["start"][0]["client_ip"] == "86.48.8.213"


def test_pay_now_from_ipv6_leaves_the_field_out(anon_client, contexts, calls):  # noqa: F811
    anon_client.get(f"{PAY_URL}?token={TOKEN}&mode=bitolo")

    anon_client.post(PAY_URL, data={"rfc": RFC, "curp": CURP}, headers={"X-Forwarded-For": "2001:db8::1"})

    assert "client_ip" not in calls["start"][0]


def test_the_crm_client_puts_it_in_the_context_request(monkeypatch):
    sent: dict = {}
    monkeypatch.setattr(CRMClient, "_request", lambda self, method, path, **kw: sent.update(kw) or {})
    client = CRMClient.__new__(CRMClient)

    client.wallet_topup_email_link_context("tok", "86.48.8.213")
    assert sent["json"] == {"token": "tok", "client_ip": "86.48.8.213"}

    client.wallet_topup_email_link_context("tok")
    assert sent["json"] == {"token": "tok"}
