"""
One log line with the CRM's reason when an emailed payment link fails.

When the CRM refused a payment-link call, the customer saw a generic page and
the CRM's reason was lost, because production has no debug routes. Each
refusal of the context or hosted-start call now writes one
`email_link_crm_error` warning. It gives the step, the CRM's status and
message, and the IP the site saw. `client_ipv4` reads `-` because this site
does not send `client_ip` yet. The 4 Nov API requires it, and its absence was
the suspected cause of the same failures on Winnow (Nov 2026).

The link token and anything the customer typed must never reach that line.
"""

from __future__ import annotations

import logging

from crm_api import CRMClient, CRMError
from tests.test_payment_link import CURP, PAY_URL, RFC, TOKEN, calls, link  # noqa: F401


def _lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("email_link_crm_error")]


def _refuse(status: int, error: str):
    def refuse(self, *args, **kwargs):
        raise CRMError(f"CRM HTTP {status}: {error}", status_code=status, payload={"success": False, "error": error})

    return refuse


def test_a_link_the_crm_will_not_open_is_logged(anon_client, stub_crm, monkeypatch, caplog):
    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_context", _refuse(422, "client_ip is required"))

    with caplog.at_level(logging.WARNING):
        anon_client.get(f"{PAY_URL}?token={TOKEN}", follow_redirects=True, headers={"X-Forwarded-For": "2001:db8::1"})

    assert _lines(caplog) == [
        "email_link_crm_error step=context status=422 client_ipv4=- ip_seen=v6 err=client_ip is required"
    ]


def test_a_refused_hosted_start_is_logged(link, calls, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_hpp_start", _refuse(403, "hosted checkout is not allowed"))

    with caplog.at_level(logging.WARNING):
        link.post(PAY_URL, data={"rfc": RFC, "curp": CURP}, headers={"X-Forwarded-For": "86.48.8.213"})

    assert _lines(caplog) == [
        "email_link_crm_error step=hpp_start status=403 client_ipv4=- ip_seen=86.48.8.213 "
        "err=hosted checkout is not allowed"
    ]


def test_a_refusal_quoting_what_was_typed_logs_none_of_it(link, calls, monkeypatch, caplog):  # noqa: F811
    quoted = f"bad rfc {RFC} curp {CURP} card 4111111111111111 token {TOKEN}\nsecond line"
    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_hpp_start", _refuse(422, quoted))

    with caplog.at_level(logging.WARNING):
        link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    (line,) = _lines(caplog)
    for secret in (RFC, CURP, TOKEN, "4111111111111111"):
        assert secret not in line
    assert "\n" not in line


def test_a_long_reason_is_cut_to_300_characters(link, calls, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_hpp_start", _refuse(500, "x" * 1000))

    with caplog.at_level(logging.WARNING):
        link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    (line,) = _lines(caplog)
    assert line.endswith("err=" + "x" * 300)


def test_logging_changes_nothing_the_customer_sees(link, calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_hpp_start", _refuse(422, "client_ip is required"))

    resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    assert resp.status_code == 200
    assert "email_link_crm_error" not in resp.get_data(as_text=True)
