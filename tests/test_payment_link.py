"""
Paying a top-up from a link in an email.

An agent raises the top-up in the CRM and the customer is emailed a link to it.
They arrive signed out, often on a phone, and this page is the only route they
have to pay - so a mistake here is not a degraded experience, it is a customer
who cannot give us money.

Two rules run through the whole file. The provider is contacted when Pay Now is
pressed and never before, because provider sessions expire long before an email
is read. And the payer's tax and identity numbers pass through this request and
are kept nowhere: not in a log, not in the session, not in the URL.
"""

from __future__ import annotations

import logging

import pytest

from crm_api import CRMClient, CRMError


TOKEN = "eyJicmFuZF9pZCI6MSwiaW50ZW50X2lkIjo0NTZ9.abc123signature"
RFC = "GOMJ850215AB3"
CURP = "GOLM900512MCJCRS08"
PAY_URL = "/wallet/topup/pay"


@pytest.fixture
def link(anon_client, stub_crm):
    """A customer who has just followed the link in their email."""
    anon_client.get(f"{PAY_URL}?token={TOKEN}&intent_id=456&mode=bitolo")
    return anon_client


@pytest.fixture
def calls(monkeypatch):
    """Records what the CRM was asked, so a test can prove what was not asked."""
    seen: dict[str, list] = {"context": [], "start": [], "status": []}

    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: seen["start"].append(payload)
        or {"mode": "bitolo_spei_deposit", "redirect_url": "https://mxnpay.example/v1/spei.php?enc=abc"},
    )
    return seen


# --- opening the email ---


def test_opening_the_link_does_not_start_the_payment(anon_client, stub_crm, calls):
    """
    The provider issues a session that dies in minutes; email is read in hours.
    Contacting it here is how a customer arrives at an expired payment.
    """
    resp = anon_client.get(f"{PAY_URL}?token={TOKEN}&mode=bitolo", follow_redirects=True)

    assert resp.status_code == 200
    assert calls["start"] == []


def test_the_token_is_taken_out_of_the_address_bar(anon_client, stub_crm):
    """
    Left in the URL it reaches every asset host in a `Referer`, stays in the
    browser history, and sits in the back button of a shared machine.
    """
    resp = anon_client.get(f"{PAY_URL}?token={TOKEN}")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(PAY_URL)
    assert TOKEN not in resp.headers["Location"]


def test_the_page_is_kept_out_of_indexes_and_caches(link):
    resp = link.get(PAY_URL)

    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"
    assert "noindex" in resp.get_data(as_text=True)


def test_the_page_shows_the_wallet_credit_and_the_transfer_amount(link):
    """
    Two different figures: the bank shows the transfer, the wallet shows the
    credit. Naming only one makes the other look like a mistake.
    """
    body = link.get(PAY_URL).get_data(as_text=True)

    assert "50.00" in body
    assert "MXN 925.00" in body


def test_the_page_asks_for_what_the_crm_says_the_provider_needs(link):
    """The fields are the CRM's to specify, not ours to hardcode."""
    body = link.get(PAY_URL).get_data(as_text=True)

    assert 'name="rfc"' in body
    assert 'name="curp"' in body
    assert "Mexican RFC" in body
    assert "Mexican CURP" in body


def test_a_provider_that_asks_for_nothing_gets_no_form(anon_client, stub_crm, monkeypatch):
    """
    Driven off `payment_requirements`, so a processor with no identity demands
    does not need a deploy here to be payable.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_context",
        lambda self, t: {"intent": {"id": 7, "status": "pending", "amount_cents": 5000, "currency": "USD"}},
    )
    anon_client.get(f"{PAY_URL}?token={TOKEN}")

    body = anon_client.get(PAY_URL).get_data(as_text=True)

    assert 'name="rfc"' not in body
    assert "Pay Now" in body


def test_a_dead_link_says_so_where_it_was_clicked(anon_client, stub_crm, monkeypatch, calls):
    """
    A customer who clicked a link in their mail has to be told at the address
    they clicked. Bouncing them to a login form reads as the site being broken.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_context",
        lambda self, t: (_ for _ in ()).throw(CRMError("CRM HTTP 404: not found", status_code=404)),
    )

    resp = anon_client.get(f"{PAY_URL}?token={TOKEN}", follow_redirects=True)
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "no longer valid" in body
    assert calls["start"] == []


def test_the_email_link_page_is_not_shadowed_by_the_card_form(anon_client, stub_crm):
    """
    `/wallet/topup/<intent_id>/pay` is the signed-in card form. A rule that
    also matched this URL would send a campaign to a login wall - which is
    exactly how the set-password page was lost once already.
    """
    resp = anon_client.get(f"{PAY_URL}?token={TOKEN}", follow_redirects=True)

    assert "Complete Your Payment" in resp.get_data(as_text=True)


# --- pressing Pay Now ---


def test_pay_now_sends_the_token_the_numbers_and_the_return_urls(link, calls):
    link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    assert len(calls["start"]) == 1
    payload = calls["start"][0]
    assert payload["token"] == TOKEN
    assert payload["rfc"] == RFC
    assert payload["curp"] == CURP
    for outcome in ("success", "fail", "cancel"):
        assert payload["return_urls"][outcome].startswith("http")


def test_pay_now_follows_the_provider_url(link, calls):
    resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://mxnpay.example/v1/spei.php?enc=abc"


def test_numbers_are_tidied_the_way_they_are_written_down(link, calls):
    """These are printed in groups on a card, and get typed in the same way."""
    link.post(PAY_URL, data={"rfc": " gomj 850215-ab3 ", "curp": CURP.lower()})

    assert calls["start"][0]["rfc"] == RFC
    assert calls["start"][0]["curp"] == CURP


def test_a_number_of_the_wrong_length_never_reaches_the_provider(link, calls):
    """
    Caught here so the customer gets a sentence they can act on, rather than a
    provider refusal - and so a failed attempt is not spent on a typo.
    """
    resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP[:-1]})
    body = resp.get_data(as_text=True)

    assert calls["start"] == []
    assert "18 characters" in body
    assert "17" in body


def test_a_missing_number_is_asked_for_by_name(link, calls):
    resp = link.post(PAY_URL, data={"rfc": RFC, "curp": ""})

    assert calls["start"] == []
    assert "Please enter your Mexican CURP" in resp.get_data(as_text=True)


def test_a_rejected_form_does_not_make_the_customer_retype_the_rest(link):
    """Eighteen characters is too many to ask for twice over someone else's typo."""
    body = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP[:-1]}).get_data(as_text=True)

    assert RFC in body


def test_an_rfc_may_contain_the_characters_an_rfc_contains(link, calls):
    """
    N-tilde and ampersand are both legal in an RFC. A tidier rule here would
    refuse real numbers, and this page is the customer's only way to pay.
    """
    link.post(PAY_URL, data={"rfc": "A&EÑ850215AB", "curp": CURP})

    assert calls["start"][0]["rfc"] == "A&EÑ850215AB"


# --- what must not be kept ---


def test_the_numbers_are_kept_nowhere_after_the_payment_starts(link, calls):
    """
    They identify a person to their tax authority. They are needed for the one
    call to the provider and must not outlive it.
    """
    link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    with link.session_transaction() as s:
        assert RFC not in str(dict(s))
        assert CURP not in str(dict(s))


def test_a_provider_refusal_quoting_the_numbers_does_not_log_them(link, monkeypatch, caplog):
    """
    A provider's own words are the only reason a customer can act on, so the
    message is worth logging - but it arrives with the numbers inside it.
    """
    def refuse(self, payload):
        raise CRMError(
            f"CRM HTTP 400: rfc {payload['rfc']} does not match curp {payload['curp']}",
            status_code=400,
            payload={"success": False, "error": f"invalid rfc {payload['rfc']} / curp {payload['curp']}"},
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_email_link_hpp_start", refuse)

    with caplog.at_level(logging.WARNING):
        resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert RFC not in logged
    assert CURP not in logged
    # The diagnosis still has to be possible: status and the shape of the
    # refusal survive, only the values are taken out.
    assert "status=400" in logged
    assert "[redacted]" in logged
    assert resp.status_code == 200


def test_the_token_is_not_logged_either(anon_client, stub_crm, monkeypatch, caplog):
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_context",
        lambda self, t: (_ for _ in ()).throw(
            CRMError(f"CRM HTTP 401: bad token {t}", status_code=401, payload={"error": f"bad token {t}"})
        ),
    )

    with caplog.at_level(logging.WARNING):
        anon_client.get(f"{PAY_URL}?token={TOKEN}", follow_redirects=True)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in logged
    assert "status=401" in logged


# --- a transfer the customer makes themselves ---


def test_spei_details_are_shown_when_there_is_nowhere_to_send_the_customer(link, monkeypatch):
    """
    A SPEI deposit is made by the customer from their own bank. With no
    provider page to redirect to, these details are the payment.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {
            "mode": "bitolo_spei_deposit",
            "status": "pending",
            "order_id": "pi00000456",
            "instructions": {
                "clabe": "646180157034181806",
                "bank_name": "STP",
                "beneficiary": "Example SA",
                "reference": "pi00000456",
                "amount": "925.00",
                "currency": "MXN",
            },
        },
    )

    body = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP}).get_data(as_text=True)

    assert "646180157034181806" in body
    assert "STP" in body
    assert "Example SA" in body
    assert "pi00000456" in body
    assert "MXN 925.00" in body


@pytest.mark.parametrize("url_key", ["redirect_url", "hosted_url", "next_action_url", "crm_card_form_url"])
def test_a_payment_url_is_followed_whatever_the_crm_called_it(link, monkeypatch, url_key):
    """
    This endpoint has named the same thing four ways across processors. The
    payment instruction is the URL; the key beside it is a label, and insisting
    on one of them is how a customer was last shown a failure while we were
    holding a working URL.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {"success": True, "mode": "bitolo_spei_deposit", url_key: "https://mxnpay.example/pay/1"},
    )

    resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://mxnpay.example/pay/1"


def test_a_refusal_that_arrives_as_a_success_still_says_why(link, monkeypatch):
    """
    A 200 carrying `success: false` still carries the reason. API 67: `error`
    is the processor's or the CRM's own words, and is what the customer should
    see in place of a generic refusal - usually the only thing anyone can act on.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {"success": False, "error": "Bitolo rejected the RFC checksum", "mode": "bitolo_spei_deposit"},
    )

    body = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP}).get_data(as_text=True)

    assert "Bitolo rejected the RFC checksum" in body


def test_an_unstartable_payment_records_the_fields_needed_to_place_the_fault(link, monkeypatch, caplog):
    """
    Whether the CRM withheld a payment URL or one came back under a name we did
    not read cannot be told apart from the outside - and `keys` is what tells
    them apart. The token and the identity numbers stay out of it.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {
            "success": True,
            "mode": "bitolo_spei_deposit",
            "order_id": "pi00003379",
            "bitolo_payment_url": "https://mxnpay.example/v1/spei.php?enc=xyz",
        },
    )

    with caplog.at_level(logging.ERROR):
        link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "http=200" in logged
    assert "success=True" in logged
    assert "mode='bitolo_spei_deposit'" in logged
    assert "redirect_url=-" in logged
    assert "hosted_url=-" in logged
    # The URL under an unexpected name is only visible through the key list,
    # which is the whole point of recording it.
    assert "bitolo_payment_url" in logged
    assert RFC not in logged
    assert CURP not in logged
    assert TOKEN not in logged


def test_a_start_with_nothing_payable_in_it_says_what_came_back(link, monkeypatch, caplog):
    """No URL and no instructions is not a payment, and must not look like one."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {"success": True, "mode": "bitolo_spei_deposit"},
    )

    with caplog.at_level(logging.ERROR):
        resp = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP})

    assert resp.status_code == 200
    assert "mode='bitolo_spei_deposit'" in "\n".join(r.getMessage() for r in caplog.records)


def test_the_status_check_reports_a_transfer_that_has_landed(link, monkeypatch):
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_status",
        lambda self, t: {"intent": {"status": "completed"}},
    )

    assert link.get("/wallet/topup/pay/status").get_json()["status"] == "success"


@pytest.mark.parametrize(
    ("crm_status", "reported"),
    [("pending", "pending"), ("completed", "success"), ("failed", "failed"), ("cancelled", "cancelled")],
)
def test_each_documented_outcome_is_reported_as_itself(link, monkeypatch, crm_status, reported):
    """
    A pending SPEI transfer is not a failure and a failed one is not something
    to keep waiting on, so the page cannot treat "not yet paid" as one state.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_status",
        lambda self, t: {"success": True, "intent": {"id": 456, "status": crm_status, "processor": "bitolo"}},
    )

    assert link.get("/wallet/topup/pay/status").get_json()["status"] == reported


def test_a_payment_that_cannot_complete_takes_the_bank_details_off_the_screen(link, monkeypatch):
    """
    A CLABE left in front of someone whose payment has failed invites a
    transfer we would have nothing to match to them.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_hpp_start",
        lambda self, payload: {"mode": "bitolo_spei_deposit", "instructions": {"clabe": "646180157034181806"}},
    )

    body = link.post(PAY_URL, data={"rfc": RFC, "curp": CURP}).get_data(as_text=True)

    # The details and the terminal states share a page; which one is on screen
    # is decided by the status the poll comes back with.
    assert 'id="paymentLinkPending"' in body
    assert 'id="paymentLinkFailed"' in body
    assert "Please do not make the transfer" in body


def test_an_expired_link_stops_the_page_asking_without_calling_it_a_failure(link, monkeypatch, caplog):
    """
    401 is the signed link expiring, not the payment failing, and says nothing
    about a transfer that may already be on its way.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_status",
        lambda self, t: (_ for _ in ()).throw(CRMError("CRM HTTP 401", status_code=401)),
    )

    with caplog.at_level(logging.WARNING):
        resp = link.get("/wallet/topup/pay/status")

    assert resp.get_json()["status"] == "expired"
    assert "failed" not in resp.get_data(as_text=True)


def test_a_settled_payment_records_what_the_crm_said_it_was(link, monkeypatch, caplog):
    """
    The website never tells the CRM how a payment went - there is no endpoint
    for it, and every processor is finalised by a signed webhook so that a
    browser cannot be the source of that truth. When the CRM shows no failed
    payment and a customer was shown one, this line is the only evidence of
    which of the two of us said so.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_status",
        lambda self, t: {"success": True, "intent": {"id": 3396, "status": "failed", "processor": "bitolo"}},
    )

    with caplog.at_level(logging.INFO):
        link.get("/wallet/topup/pay/status")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "bucket=failed" in logged
    assert "crm_status='failed'" in logged
    assert "intent=3396" in logged


def test_a_payment_still_waiting_is_not_worth_a_line_every_fifteen_seconds(link, caplog):
    with caplog.at_level(logging.INFO):
        link.get("/wallet/topup/pay/status")

    assert "status settled" not in "\n".join(r.getMessage() for r in caplog.records)


def test_a_status_endpoint_that_is_not_there_leaves_the_instructions_alone(link, monkeypatch, caplog):
    """
    API 66 documents only `context` and `hpp/start` for emailed links. A
    transfer nobody has made yet is not a failure, so an endpoint we cannot
    reach must not tell the customer their payment went wrong.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_email_link_status",
        lambda self, t: (_ for _ in ()).throw(CRMError("CRM HTTP 404", status_code=404)),
    )

    with caplog.at_level(logging.WARNING):
        resp = link.get("/wallet/topup/pay/status")

    assert resp.get_json()["status"] == "unknown"
    assert "payment link status" not in "\n".join(r.getMessage() for r in caplog.records)
