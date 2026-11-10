"""
Card expiry dates go to the CRM as `MM` and `YYYY`.

The card form sent the expiry exactly as typed or autofilled, so "2" and "27"
could reach the CRM. On Lotto Express, which runs the same engine, Worldpay
refused those charges with "Invalid year : 30 Usage: yyyy" (Nov 2026, nine
customers). The form looked like a dropdown but was a text box with
suggestions. It is now a real dropdown, whatever arrives is corrected before it
is sent, and an expired card is caught on the page.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crm_api import CRMClient
from tests.test_wallet import CARD_FORM, _options_init, _top_up

NEXT_YEAR = datetime.now(timezone.utc).year + 1
SHORT_NEXT_YEAR = str(NEXT_YEAR)[2:]


@pytest.fixture
def charges(monkeypatch, stub_crm):
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("worldpay"))
    sent: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda self, token, intent_id, payload: sent.append(payload) or {"status": "completed"},
    )
    return sent


@pytest.mark.parametrize(
    "month, year, want_month",
    [
        ("2", SHORT_NEXT_YEAR, "02"),
        ("02", SHORT_NEXT_YEAR, "02"),
        ("2", str(NEXT_YEAR), "02"),
        ("12", str(NEXT_YEAR), "12"),
    ],
)
def test_a_card_is_sent_with_a_two_digit_month_and_four_digit_year(client, charges, month, year, want_month):
    _top_up(client, {**CARD_FORM, "exp_month": month, "exp_year": year})

    assert charges, "the card was not charged"
    assert charges[0]["card"]["exp_month"] == want_month
    assert charges[0]["card"]["exp_year"] == str(NEXT_YEAR)


@pytest.mark.parametrize("month, year", [("13", str(NEXT_YEAR)), ("0", str(NEXT_YEAR)), ("2", "7"), ("2", "20277")])
def test_an_impossible_expiry_is_not_sent(client, charges, month, year):
    resp = _top_up(client, {**CARD_FORM, "exp_month": month, "exp_year": year})

    assert charges == []
    assert resp.status_code == 302


def test_an_expired_card_is_caught_before_the_bank_sees_it(client, charges):
    last_year = datetime.now(timezone.utc).year - 1

    _top_up(client, {**CARD_FORM, "exp_month": "12", "exp_year": str(last_year)})
    page = client.get("/wallet/add-funds", follow_redirects=True).get_data(as_text=True)

    assert charges == []
    assert "This card has expired" in page


def test_the_form_offers_dropdowns_not_text_boxes(client, charges):
    started = client.post("/wallet/add-funds", data={"amount": "20.00"})
    body = client.get(started.headers["Location"]).get_data(as_text=True)

    assert '<select name="exp_month"' in body
    assert '<select name="exp_year"' in body
    assert f'<option value="{NEXT_YEAR}">' in body
    assert '<option value="02">' in body
