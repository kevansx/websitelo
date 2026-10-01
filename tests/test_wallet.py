"""
Pre-launch tests for wallet pages: add-funds rendering, top-up return pages
(success / failed / cancelled), and CRM-outage behavior. Real payment flows are
staging-only (see docs/PRELAUNCH_TEST_PLAN.md).
"""

from __future__ import annotations

import logging

import pytest

from app import app as flask_app
from crm_api import CRMClient, CRMError


def test_add_funds_renders_for_logged_in_customer(client, stub_crm):
    resp = client.get("/wallet/add-funds")
    assert resp.status_code == 200


def test_topup_success_page_renders(client, stub_crm):
    resp = client.get("/wallet/topup/success")
    assert resp.status_code == 200


def test_topup_failed_page_renders(client, stub_crm):
    resp = client.get("/wallet/topup/failed")
    assert resp.status_code == 200


def test_topup_cancelled_page_renders(client, stub_crm):
    resp = client.get("/wallet/topup/cancelled")
    assert resp.status_code == 200


# --- Hosted-payment-only processors (e.g. CCM): amount-only add-funds form ---

CCM_OPTIONS_INIT = {
    "mode": "options",
    "intent_id": "intent-ccm",
    "routing": {"session_id": "sess-ccm", "processor": "ccm", "attempt": 1},
    "options": {"hpp": {"start_url": "https://crm.example/api/v1/wallet/topup/intent-ccm/hpp/start"}},
}

ELTROVOX_OPTIONS_INIT = {
    "mode": "options",
    "intent_id": "intent-elt",
    "processor": "eltrovox",
    "options": {
        "hpp": {"start_url": "https://crm.example/api/v1/wallet/topup/intent-elt/hpp/start"},
        "direct_card": {
            "available": True,
            "charge_url": "https://crm.example/api/v1/wallet/topup/intent-elt/charge",
            "cards_url": "https://crm.example/api/v1/wallet/cards",
        },
    },
}


_UNSET = object()  # lets a test pass direct_card=None to mean "omit the block"


def _options_init(processor: str, intent_id: str = "intent-1") -> dict:
    """A routed init response offering both hosted and direct-card payment."""
    return {
        "mode": "options",
        "intent_id": intent_id,
        "routing": {"session_id": "sess-1", "processor": processor, "attempt": 1},
        "options": {
            "hpp": {"start_url": f"https://crm.example/api/v1/wallet/topup/{intent_id}/hpp/start"},
            "direct_card": {
                "available": True,
                "charge_url": f"https://crm.example/api/v1/wallet/topup/{intent_id}/charge",
                "cards_url": "https://crm.example/api/v1/wallet/cards",
            },
        },
    }


CARD_FORM = {
    "amount": "20.00",
    "card_number": "4111111111111111",
    "exp_month": "12",
    "exp_year": "2030",
    "cardholder_name": "Test User",
    "cvv": "123",
    "billing_street": "1 Main St",
    "billing_city": "Springfield",
    "billing_postcode": "12345",
    "billing_country": "US",
}


def test_the_add_funds_page_only_asks_for_an_amount(client, stub_crm, monkeypatch):
    """
    Which payment methods a customer gets is the CRM's decision, made when the
    intent is created. The page cannot know it yet and must not ask: asking
    meant a fabricated GBP 5.00 intent per visit, left pending forever.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda *a, **k: pytest.fail("the add-funds page created a payment intent"),
    )
    resp = client.get("/wallet/add-funds")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="amount"' in body
    assert 'name="card_number"' not in body
    assert 'name="billing_street"' not in body


def test_a_customer_with_no_country_on_file_is_asked_for_one(client, stub_crm, monkeypatch):
    """Processor Rules match on country and fall through to "No Match" when it
    is blank, so it is worth one field rather than a guess."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda *a, **k: pytest.fail("routed a payment without knowing the country"),
    )
    with client.session_transaction() as s:
        s["customer"] = {"id": 1, "email": "test@example.com"}

    assert 'name="country"' in client.get("/wallet/add-funds").get_data(as_text=True)

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})
    assert resp.status_code == 302
    assert "/wallet/add-funds" in resp.headers["Location"]


def test_a_country_we_cannot_read_never_blocks_the_payment_twice(client, stub_crm, monkeypatch):
    """
    The typed country is matched against the countries cache. If that is empty
    nothing parses, and bouncing every time would be a customer who can never
    top up. The CRM's "No Match" rule is there for this.
    """
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )
    monkeypatch.setattr(CRMClient, "customer_me", lambda self, token: {"customer": {"id": 1}})
    with client.session_transaction() as s:
        # No country, but an address: the country is what this is about.
        s["customer"] = {
            "id": 1,
            "email": "test@example.com",
            "street": "1 Main St",
            "city": "Springfield",
            "postal_code": "12345",
        }

    first = client.post("/wallet/add-funds", data={"amount": "20.00", "country": "Freedonia"})
    assert "/wallet/add-funds" in first.headers["Location"]
    assert inits == []

    second = client.post("/wallet/add-funds", data={"amount": "20.00", "country": "Freedonia"})
    assert second.headers["Location"] == "https://pay.example/hpp"
    assert len(inits) == 1
    assert "country" not in inits[0]


def test_the_country_on_file_is_sent_to_route_the_payment(client, stub_crm, monkeypatch):
    inits: list[dict] = []

    def recording_init(self, token, payload):
        inits.append(payload)
        return dict(CCM_OPTIONS_INIT)

    monkeypatch.setattr(CRMClient, "wallet_topup_init", recording_init)
    client.post("/wallet/add-funds", data={"amount": "20.00"})
    assert inits and inits[0].get("country") == "US"


def test_the_payment_step_shows_the_card_form_when_the_crm_offers_one(client, stub_crm, monkeypatch):
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(ELTROVOX_OPTIONS_INIT))

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/wallet/topup/intent-elt/pay"

    body = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert 'name="card_number"' in body
    assert 'name="billing_street"' in body
    assert "20.00" in body


def test_the_payment_step_belongs_to_the_session_that_started_it(client, stub_crm, monkeypatch):
    """The intent id is in the URL, so it is checked against the one this
    session started rather than trusted."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda *a, **k: pytest.fail("charged an intent this session never created"),
    )
    resp = client.post("/wallet/topup/someone-elses-intent/pay", data=dict(CARD_FORM))
    assert resp.status_code == 302
    assert "/wallet/add-funds" in resp.headers["Location"]


def test_add_funds_hpp_flow_needs_only_amount(client, stub_crm, monkeypatch):
    """A hosted-only processor needs nothing but the amount, and the customer
    must reach its page without being asked for details it collects itself."""
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(CCM_OPTIONS_INIT))

    def no_profile_update(self, *a, **k):
        raise AssertionError("customer_update must not be called in the HPP-only flow")

    monkeypatch.setattr(CRMClient, "customer_update", no_profile_update)

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/hpp"


def test_topup_success_captures_billing_from_payload(client, stub_crm, monkeypatch):
    """Billing address echoed in the completed-payment payload is captured into
    the customer profile (gap-filling only)."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_status",
        lambda self, token, intent_id: {
            "success": True,
            "intent": {"id": 1, "status": "completed"},
            "billing": {"line1": "9 High Street", "city": "Dublin", "postal_code": "D01 F5P2", "country": "IE"},
        },
    )
    updates = []

    def capture_update(self, token, payload):
        updates.append(payload)
        return {"customer": {}}

    monkeypatch.setattr(CRMClient, "customer_update", capture_update)
    with client.session_transaction() as s:
        # Gap-filling has to have a gap: this customer has a country on record
        # but no address, which is who the payload is filling in for.
        s["customer"] = {"id": 1, "email": "test@example.com", "country": "IE"}

    resp = client.get("/wallet/topup/return/success?intent_id=1")
    assert resp.status_code == 302
    assert "/wallet/topup/success" in resp.headers["Location"]
    assert updates and updates[0]["street"] == "9 High Street"
    assert updates[0]["city"] == "Dublin"
    # Gap-filling only: this customer already has a country on record, and the
    # CRM routes payments on it, so a hosted page must not quietly change it.
    assert "country" not in updates[0]


def test_topup_success_fills_a_missing_country_from_the_payload(client, stub_crm, monkeypatch):
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_status",
        lambda self, token, intent_id: {
            "success": True,
            "intent": {"id": 1, "status": "completed"},
            "billing": {"line1": "9 High Street", "city": "Dublin", "postal_code": "D01 F5P2", "country": "IE"},
        },
    )
    updates = []
    monkeypatch.setattr(
        CRMClient,
        "customer_update",
        lambda self, token, payload: updates.append(payload) or {"customer": {}},
    )
    with client.session_transaction() as s:
        s["customer"] = {"id": 1, "email": "test@example.com"}

    client.get("/wallet/topup/return/success?intent_id=1")
    assert updates and updates[0]["country"] == "IE"


# --- API 58: Website Processor Rules routing ---

def test_topup_return_advances_routing_on_failure(client, stub_crm, monkeypatch):
    """A failed intent with routing.can_advance=true must resume the routing
    session via topup init and follow the next processor's instructions."""
    status_payload = {
        "success": True,
        "intent": {"id": 456, "status": "failed", "processor": "traxx", "amount_cents": 5000},
        "routing": {
            "session_id": "sess-1",
            "attempt": 1,
            "outcome": "technical",
            "can_advance": True,
            "next_processor": "expefast",
            "resume_payload": {"routing_session_id": "sess-1"},
            "exhausted": False,
        },
    }
    monkeypatch.setattr(CRMClient, "wallet_topup_status", lambda self, token, intent_id: status_payload)
    init_calls = []

    def fake_init(self, token, payload):
        init_calls.append(payload)
        return {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/next-processor"}

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)

    resp = client.get("/wallet/topup/return/fail?intent_id=456")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/next-processor"
    # Resume must send only the CRM-supplied routing_session_id (amount is
    # retained by the CRM), never a client-made value or a plain retry.
    assert init_calls and init_calls[0]["routing_session_id"] == "sess-1"
    assert "amount_cents" not in init_calls[0]
    assert "processor" not in init_calls[0]


def test_topup_return_terminal_failure_when_routing_exhausted(client, stub_crm, monkeypatch):
    status_payload = {
        "success": True,
        "intent": {"id": 456, "status": "failed", "processor": "traxx"},
        "routing": {
            "session_id": "sess-1",
            "attempt": 2,
            "outcome": "technical",
            "can_advance": False,
            "next_processor": None,
            "resume_payload": None,
            "exhausted": True,
        },
    }
    monkeypatch.setattr(CRMClient, "wallet_topup_status", lambda self, token, intent_id: status_payload)

    def fail_init(self, token, payload):
        raise AssertionError("must not retry init when routing cannot advance")

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fail_init)

    resp = client.get("/wallet/topup/return/fail?intent_id=456")
    assert resp.status_code == 302
    assert "/wallet/topup/failed" in resp.headers["Location"]
    assert "providers" in resp.headers["Location"]


def test_topup_return_success_with_nested_intent_status(client, stub_crm, monkeypatch):
    """API 58 status responses nest the status under `intent`."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_status",
        lambda self, token, intent_id: {"success": True, "intent": {"id": 1, "status": "completed"}, "routing": None},
    )
    resp = client.get("/wallet/topup/return/pending?intent_id=1")
    assert resp.status_code == 302
    assert "/wallet/topup/success" in resp.headers["Location"]


def test_add_funds_init_failure_advances_to_next_processor(client, stub_crm, monkeypatch):
    """When init fails and the error payload says routing can advance, the site
    must re-post the routing_session_id instead of surfacing the failure."""
    init_calls = []

    def fake_init(self, token, payload):
        init_calls.append(payload)
        if len(init_calls) == 1:
            raise CRMError(
                "CRM HTTP 502: processor init failed",
                status_code=502,
                payload={
                    "success": False,
                    "error": "processor init failed",
                    "routing": {
                        "session_id": "sess-9",
                        "attempt": 1,
                        "can_advance": True,
                        "next_processor": "expefast",
                        "resume_payload": {"routing_session_id": "sess-9"},
                        "exhausted": False,
                    },
                },
            )
        return {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"}

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)

    resp = client.post(
        "/wallet/add-funds",
        data={
            "amount": "10.00",
            "billing_street": "1 Main St",
            "billing_city": "Springfield",
            "billing_postcode": "12345",
            "billing_country": "US",
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/second"
    assert len(init_calls) == 2
    assert init_calls[1]["routing_session_id"] == "sess-9"


# --- Direct-card processors: the CRM routes, the site must not veto ---


def _top_up(client, form: dict | None = None, amount: str = "20.00"):
    """
    Run a whole top-up: choose an amount, then pay however the CRM said to.

    Returns the response to the payment step, or to the amount step when the
    CRM sent the customer somewhere else (a hosted page) instead.
    """
    started = client.post("/wallet/add-funds", data={"amount": amount})
    location = started.headers.get("Location", "")
    if not location.endswith("/pay"):
        return started
    return client.post(location, data=dict(form if form is not None else CARD_FORM))


@pytest.mark.parametrize("processor", ["worldpay", "eltrovox", "emerchant", "testing"])
def test_a_routed_direct_card_processor_is_charged_directly(client, stub_crm, monkeypatch, processor):
    """
    The CRM picks the processor by country and says whether the intent takes a
    direct card charge. When it says yes, the site must charge it.

    Worldpay was missing from the site's own processor list, so its intents were
    pushed to a hosted page it is not configured for; the CRM rejected the
    hosted start and the intent was left pending with the customer's money
    uncollected.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init(processor))
    charges: list[tuple[str, dict]] = []

    def capture_charge(self, token, intent_id, payload):
        charges.append((intent_id, payload))
        return {"status": "completed"}

    def refuse_hpp(self, token, intent_id):
        raise AssertionError(f"{processor} intent was sent to the hosted page instead of being charged")

    monkeypatch.setattr(CRMClient, "wallet_topup_charge", capture_charge)
    monkeypatch.setattr(CRMClient, "wallet_topup_hpp_start", refuse_hpp)

    resp = _top_up(client)
    assert resp.status_code == 302
    assert charges, f"no direct card charge attempted for {processor}"
    assert charges[0][1]["card"]["card_number"] == CARD_FORM["card_number"]


def test_a_processor_the_crm_cannot_charge_directly_still_uses_the_hosted_page(client, stub_crm, monkeypatch):
    """
    The list is a guard, not a formality: a processor outside it keeps going to
    the hosted page even when the init response advertises direct card.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("someneWprocessor"))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", lambda *a, **k: pytest.fail("charged an unlisted processor"))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://pay.example/hosted"},
    )

    resp = _top_up(client)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/hosted"


def test_the_direct_card_processor_list_is_configurable(client, stub_crm, monkeypatch):
    """
    Adding a processor in the CRM must not need a website deploy. This is the
    knob that was missing when Worldpay was turned on.
    """
    monkeypatch.setenv("WALLET_DIRECT_CARD_PROCESSORS", "brandnewpsp")
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("brandnewpsp"))
    charges: list[str] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda self, token, intent_id, payload: charges.append(intent_id) or {"status": "completed"},
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda *a, **k: pytest.fail("hosted page used for a configured direct-card processor"),
    )

    resp = _top_up(client)
    assert resp.status_code == 302
    assert charges == ["intent-1"]


def test_a_rejected_direct_card_charge_falls_back_to_the_hosted_page(client, stub_crm, monkeypatch):
    """
    If the CRM disagrees and refuses the charge, the intent must still be paid
    rather than abandoned. The refusal names the processors it does allow, and
    that wording changes as processors are added, so the match cannot depend on
    the exact list in the message.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("worldpay"))

    def refuse(self, token, intent_id, payload):
        raise CRMError(
            "CRM HTTP 422: Direct card charging is only available for eltrovox/emerchant/worldpay intents",
            status_code=422,
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_charge", refuse)
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://pay.example/fallback"},
    )

    resp = _top_up(client)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/fallback"


def _config_refusal(routing=None):
    """The CRM declining to take a card at all, rather than the bank declining
    the card. API 60 attaches routing to this like any other charge failure."""

    def refuse(self, token, intent_id, payload):
        raise CRMError(
            "CRM HTTP 422: Direct card charging is only available for eltrovox/emerchant/worldpay intents",
            status_code=422,
            payload={"success": False, "routing": routing} if routing else None,
        )

    return refuse


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500, 502, 503])
def test_a_config_refusal_reaches_the_hosted_page_whatever_status_it_arrives_as(
    client, stub_crm, monkeypatch, status
):
    """
    The recovery must key on what the CRM said, not on the status code it
    chose to say it with.

    `_friendly_crm_error` exists to keep CRM wording away from customers, and
    on a 500 or any gateway status it replaces the message outright. Matching
    the customer-facing text meant this fallback worked on a 422 and silently
    did nothing on a 500 - and this CRM already answers 500 where a 422
    belongs, which is how a duplicate phone number at registration presents.
    The symptom would be a processor on which no payment ever completes.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("traxx"))

    def refuse(self, token, intent_id, payload):
        raise CRMError(
            f"CRM HTTP {status}: Direct card charging is only available for eltrovox/emerchant intents",
            status_code=status,
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_charge", refuse)
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://traxx.example/hosted"},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://traxx.example/hosted"


def test_a_config_refusal_is_recognised_from_the_payload_alone(client, stub_crm, monkeypatch):
    """
    The reason can arrive as JSON rather than in the exception text. Reading
    only one of the two makes the recovery depend on how the CRM chose to
    phrase its response envelope.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("traxx"))

    def refuse(self, token, intent_id, payload):
        raise CRMError(
            "CRM HTTP 500: Internal Server Error",
            status_code=500,
            payload={
                "success": False,
                "error": "Direct card charging is only available for eltrovox/emerchant intents",
            },
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_charge", refuse)
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://traxx.example/hosted"},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://traxx.example/hosted"


def test_a_refused_charge_names_its_processor_in_the_log(client, stub_crm, monkeypatch, caplog):
    """
    "Has anyone ever paid on TRAXX?" was not answerable from the log: charges
    were recorded only when they failed, and without naming the processor.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("traxx"))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda self, token, intent_id, payload: (_ for _ in ()).throw(
            CRMError("CRM HTTP 402: card declined", status_code=402)
        ),
    )

    with caplog.at_level(logging.INFO):
        _top_up(client)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "processor=traxx" in logged
    assert "http=402" in logged


def test_a_processor_that_will_not_take_a_card_uses_its_own_hosted_page_first(client, stub_crm, monkeypatch):
    """
    Nothing reached the bank, so this is configuration, not a decline. Spending
    a processor from the rule on it costs the customer a third card form — and
    the pending intents at the end of a cascade are the customers who stopped
    at one. The hosted page here takes the payment as things stand.
    """
    inits: list[dict] = []

    def fake_init(self, token, payload):
        inits.append(payload)
        return _options_init("traxx")

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _config_refusal(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": f"https://traxx.example/{intent_id}"},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://traxx.example/intent-1"
    assert not any(p.get("routing_session_id") for p in inits), "a config refusal must not spend a processor"


def test_a_processor_that_will_not_take_a_card_and_has_no_hosted_page_advances(client, stub_crm, monkeypatch):
    """Where there is no hosted page to fall back to, it is a routing matter
    after all — the alternative is a failure page on a live routing session."""

    def fake_init(self, token, payload):
        if payload.get("routing_session_id"):
            return {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/next"}
        return _direct_card_only_init("worldpay")

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _config_refusal(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: pytest.fail("worldpay has no hosted page to fall back to"),
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://pay.example/next"


def test_a_second_card_form_says_why_it_is_asking_again(client, stub_crm, monkeypatch):
    """
    Card details cannot be carried to another processor, so an advance onto one
    that takes cards has to ask again. Unexplained, that reads as the site
    having lost the payment, and the customer stops — which is what a pending
    intent at the end of a cascade is.
    """
    _init_then_resume(monkeypatch, _options_init("emerchant", intent_id="intent-2"))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    resp = _top_up(client)
    assert resp.headers["Location"].endswith("/wallet/topup/intent-2/pay")

    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "declined by the provider" in page
    assert "switched to another one" in page


# --- API 60: a routed direct-card failure advances to the next processor ---
#
# The charge response now carries the routing state, so a decline can start the
# next processor immediately instead of waiting for the customer to be bounced
# back through a return URL. The CRM decides whether a given failure is allowed
# to advance; the site only carries out the instruction.

ADVANCE = {
    "session_id": "sess-7",
    "attempt": 1,
    "outcome": "soft_decline",
    "can_advance": True,
    "next_processor": "eltrovox",
    "resume_payload": {"routing_session_id": "sess-7"},
    "exhausted": False,
}

NO_ADVANCE = {
    "session_id": "sess-7",
    "attempt": 3,
    "outcome": "hard_decline",
    "can_advance": False,
    "next_processor": None,
    "resume_payload": None,
    "exhausted": True,
}


def _declining_charge(routing, *, charges: list | None = None):
    """A 402 decline, the shape API 60 documents for a routed direct card."""

    def fake_charge(self, token, intent_id, payload):
        if charges is not None:
            charges.append(intent_id)
        raise CRMError(
            "CRM HTTP 402: card declined",
            status_code=402,
            payload={
                "success": False,
                "error": "card declined",
                "decline_code": "51",
                "decline_message": "Insufficient funds",
                "routing": routing,
            },
        )

    return fake_charge


def _init_then_resume(monkeypatch, resume_response, inits: list | None = None):
    """Route the first top-up to worldpay; answer the resume with the next one."""

    def fake_init(self, token, payload):
        if inits is not None:
            inits.append(payload)
        if payload.get("routing_session_id"):
            if isinstance(resume_response, BaseException):
                raise resume_response
            return resume_response
        return _options_init("worldpay")

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)


def test_a_declined_routed_card_starts_the_next_processor(client, stub_crm, monkeypatch):
    inits: list[dict] = []
    _init_then_resume(
        monkeypatch,
        {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"},
        inits,
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    resp = _top_up(client)

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://pay.example/second"
    # Resume carries only the CRM's own session id: the amount and currency are
    # held by the routing session, and a client-made value must never be sent.
    assert len(inits) == 2
    assert inits[1]["routing_session_id"] == "sess-7"
    assert "amount_cents" not in inits[1]
    assert "processor" not in inits[1]


def test_the_declined_intent_is_never_charged_again(client, stub_crm, monkeypatch):
    """Advancing creates the next attempt. It does not retry the failed one."""
    charges: list[str] = []
    _init_then_resume(
        monkeypatch,
        {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"},
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE, charges=charges))

    _top_up(client)

    assert charges == ["intent-1"]


def test_the_next_processor_asks_for_the_card_rather_than_replaying_it(client, stub_crm, monkeypatch):
    """
    The customer gave their card to one processor. Handing it to a different one
    behind their back is not ours to do, so a next processor that takes cards
    directly gets its own trip through the payment step.
    """
    charges: list[str] = []
    _init_then_resume(monkeypatch, _options_init("eltrovox", intent_id="intent-2"))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE, charges=charges))

    resp = _top_up(client)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/wallet/topup/intent-2/pay")
    assert charges == ["intent-1"]


def test_a_decline_that_cannot_advance_is_terminal(client, stub_crm, monkeypatch):
    _init_then_resume(monkeypatch, AssertionError("must not resume a routing session that cannot advance"))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(NO_ADVANCE))

    resp = _top_up(client)

    assert resp.status_code == 302
    assert "/wallet/topup/failed" in resp.headers["Location"]


def test_the_customer_is_not_stranded_when_the_next_processor_will_not_start(client, stub_crm, monkeypatch):
    _init_then_resume(monkeypatch, CRMError("CRM HTTP 502: next processor unavailable", status_code=502))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    resp = _top_up(client)

    assert resp.status_code == 302
    assert "/wallet/topup/failed" in resp.headers["Location"]


def test_a_next_processor_with_nowhere_to_send_us_is_not_a_silent_dead_end(client, stub_crm, monkeypatch):
    """An init that names no redirect, no card form and no options leaves the
    customer nothing to do, so it has to surface as a failure rather than a
    blank page."""
    _init_then_resume(monkeypatch, {"mode": "options", "intent_id": "intent-2"})
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    resp = _top_up(client)

    assert resp.status_code == 302
    assert "/wallet/topup/failed" in resp.headers["Location"]


def _traxx_init(intent_id: str = "intent-2", direct_card: dict | None = _UNSET) -> dict:
    """
    TRAXX's real init shape, confirmed by the CRM team 2026-09-02.

    It matches nothing else: direct card is `allowed`/`status` with no
    `charge_url` or `cards_url`, and hosted is `hosted_checkout`, not `hpp`.
    """
    options: dict = {
        "hosted_checkout": {
            "start_url": f"https://crm.example/api/v1/wallet/topup/{intent_id}/hpp/start",
            "return_urls": {"success": "s", "fail": "f", "cancel": "c"},
        }
    }
    if direct_card is _UNSET:
        direct_card = {"allowed": True, "status": "available"}
    if direct_card is not None:
        options["direct_card"] = direct_card
    return {
        "mode": "options",
        "intent_id": intent_id,
        "routing": {"session_id": "sess-7", "processor": "traxx", "attempt": 2},
        "options": options,
    }


def test_an_advance_onto_traxx_collects_the_card(client, stub_crm, monkeypatch):
    """
    TRAXX says `allowed: true` / `status: "available"` and gives no charge_url,
    where every other processor says `available: true` and does. Reading only
    the documented shape left five Colombian intents stranded pending: the site
    judged a processor that was ready to take a card as unusable.
    """
    _init_then_resume(monkeypatch, _traxx_init())
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: pytest.fail("TRAXX takes a card directly; do not start its hosted page"),
    )

    resp = _top_up(client)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/wallet/topup/intent-2/pay")


def test_traxx_is_charged_even_where_the_allowlist_omits_it(client, stub_crm, monkeypatch):
    """
    The allowlist second-guesses `available`, a flag the CRM once returned true
    for processors that then refused the charge. It was written before any
    processor answered `allowed`/`status`, and a live server carrying its own
    value for the list is where a veto there would go unnoticed longest.
    """
    monkeypatch.setenv("WALLET_DIRECT_CARD_PROCESSORS", "eltrovox,emerchant,worldpay,testing")
    _init_then_resume(monkeypatch, _traxx_init())
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: pytest.fail("the allowlist must not veto a shape it was not written for"),
    )

    resp = _top_up(client)

    assert resp.headers["Location"].endswith("/wallet/topup/intent-2/pay")


def test_traxx_is_charged_at_the_intent_not_an_advertised_url(client, stub_crm, monkeypatch):
    """The charge and hosted-start endpoints are addressed by intent id, so a
    processor that advertises no URLs is not thereby refusing the flow."""
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _traxx_init("intent-9"))
    charged: list[str] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda self, token, intent_id, payload: charged.append(intent_id) or {"status": "completed"},
    )

    _top_up(client)

    assert charged == ["intent-9"]


def test_traxx_falls_back_to_hosted_checkout_when_the_card_is_not_allowed(client, stub_crm, monkeypatch):
    """`hosted_checkout`, not `hpp` — the other half of TRAXX's odd shape."""
    _init_then_resume(monkeypatch, _traxx_init(direct_card={"allowed": False, "status": "disabled"}))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://traxx.example/hosted"},
    )

    resp = _top_up(client)

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://traxx.example/hosted"


def test_an_omitted_direct_card_block_is_not_charged(client, stub_crm, monkeypatch):
    """The CRM's instruction is explicit: if `direct_card` is absent, do not
    charge. Absence is a refusal, unlike a missing URL within it."""
    _init_then_resume(monkeypatch, _traxx_init(direct_card=None))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://traxx.example/hosted"},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://traxx.example/hosted"


def test_a_direct_card_block_that_is_allowed_but_not_available_is_not_charged(client, stub_crm, monkeypatch):
    """Both halves of TRAXX's answer have to agree before a card is taken."""
    _init_then_resume(monkeypatch, _traxx_init(direct_card={"allowed": True, "status": "pending_review"}))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://traxx.example/hosted"},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://traxx.example/hosted"


def test_a_refused_hosted_start_is_logged_rather_than_swallowed(client, stub_crm, monkeypatch, caplog):
    """
    The hosted start was the one call in the advance that could fail without
    leaving a trace, which made "the site never tried" and "the CRM said no"
    look identical from either side of the API.
    """
    _init_then_resume(monkeypatch, _traxx_init(direct_card=None))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    def refuse(self, token, intent_id):
        raise CRMError("CRM HTTP 400: hosted checkout not configured", status_code=400)

    monkeypatch.setattr(CRMClient, "wallet_topup_hpp_start", refuse)

    with caplog.at_level(logging.WARNING):
        resp = _top_up(client)

    assert "/wallet/topup/failed" in resp.headers["Location"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "wallet_topup_hpp_start failed for intent intent-2" in logged
    assert "hosted checkout not configured" in logged


def test_a_dead_end_records_what_the_processor_actually_offered(client, stub_crm, monkeypatch, caplog):
    """
    Which flow a processor advertises is the whole reason an advance dead-ends,
    and it is not always documented, so the log has to say what came back and
    not merely that nothing was usable. URLs are left out: they carry tokens.
    """
    _init_then_resume(
        monkeypatch,
        {
            "mode": "options",
            "intent_id": "intent-2",
            "routing": {"processor": "traxx"},
            "options": {
                "direct_card": {
                    "allowed": True,
                    "status": "enabled",
                    "charge_url": "https://crm.example/secret-token",
                }
            },
        },
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    with caplog.at_level(logging.WARNING):
        resp = _top_up(client)

    assert "/wallet/topup/failed" in resp.headers["Location"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "traxx" in logged
    assert "'allowed': True" in logged
    assert "'status': 'enabled'" in logged
    assert "charge_url" in logged
    assert "secret-token" not in logged


def test_routing_is_read_off_the_intent_when_the_error_omits_it(client, stub_crm, monkeypatch):
    """Compatibility while CRM deployments are staggered: an older build answers
    the charge without routing but still carries it on the intent."""
    inits: list[dict] = []
    _init_then_resume(
        monkeypatch,
        {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"},
        inits,
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(None))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_status",
        lambda self, token, intent_id: {"intent": {"id": intent_id, "status": "failed"}, "routing": ADVANCE},
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://pay.example/second"
    assert len(inits) == 2


def test_advancing_stops_after_five_attempts(client, stub_crm, monkeypatch):
    """The CRM decides when a session is exhausted, but a CRM that keeps saying
    'advance' must not spin the customer round forever."""
    inits: list[dict] = []
    _init_then_resume(
        monkeypatch,
        {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"},
        inits,
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))

    started = client.post("/wallet/add-funds", data={"amount": "20.00"})
    pay_url = started.headers["Location"]
    with client.session_transaction() as s:
        s["topup_routing_advances"] = 5

    resp = client.post(pay_url, data=dict(CARD_FORM))

    assert "/wallet/topup/failed" in resp.headers["Location"]
    # Only the opening init ran; the guard stopped the resume.
    assert len(inits) == 1


def test_a_decline_returned_as_a_200_also_advances(client, stub_crm, monkeypatch):
    """Not every decline arrives as a 402."""
    _init_then_resume(
        monkeypatch,
        {"mode": "hpp_redirect", "intent_id": "intent-2", "redirect_url": "https://pay.example/second"},
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        lambda self, token, intent_id, payload: {
            "success": False,
            "status": "failed",
            "error": "card declined",
            "routing": ADVANCE,
        },
    )

    resp = _top_up(client)

    assert resp.headers["Location"] == "https://pay.example/second"


# --- Processors that have no hosted page ---
#
# Worldpay and Z1 are direct-card only: there is no `/hpp/start` for them. The
# site used to answer "no direct card" with "then use the hosted page", which
# for those two is a route the CRM does not have. The customer got a failure
# page for a processor that was sitting there ready to take a card.


def _direct_card_only_init(processor: str, intent_id: str = "intent-dco") -> dict:
    """Worldpay's shape: options carrying direct card and nothing else."""
    return {
        "mode": "options",
        "intent_id": intent_id,
        "routing": {"session_id": "sess-1", "processor": processor, "attempt": 1},
        "options": {
            "direct_card": {
                "available": True,
                "charge_url": f"https://crm.example/api/v1/wallet/topup/{intent_id}/charge",
            },
        },
    }


def test_a_processor_with_no_hosted_page_is_never_sent_to_one(client, stub_crm, monkeypatch):
    monkeypatch.setattr(
        CRMClient, "wallet_topup_init", lambda self, token, payload: _direct_card_only_init("worldpay")
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda *a, **k: pytest.fail("started a hosted page for a direct-card-only processor"),
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/wallet/topup/intent-dco/pay")


def test_the_allowlist_does_not_veto_a_processor_with_nowhere_else_to_go(client, stub_crm, monkeypatch):
    """
    The allowlist is a guard over the CRM's answer, not a veto. Applying it to a
    processor with no hosted page guarantees a dead end, where trusting the CRM
    at worst ends at the same failure and at best takes the payment.
    """
    monkeypatch.setenv("WALLET_DIRECT_CARD_PROCESSORS", "somethingelse")
    monkeypatch.setattr(
        CRMClient, "wallet_topup_init", lambda self, token, payload: _direct_card_only_init("z1")
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda *a, **k: pytest.fail("started a hosted page for a direct-card-only processor"),
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.headers["Location"].endswith("/wallet/topup/intent-dco/pay")


def test_the_allowlist_still_vetoes_when_a_hosted_page_exists(client, stub_crm, monkeypatch):
    """Where there is a fallback, the guard still applies."""
    monkeypatch.setenv("WALLET_DIRECT_CARD_PROCESSORS", "somethingelse")
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("traxx"))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://pay.example/hosted"},
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.headers["Location"] == "https://pay.example/hosted"


def test_a_hosted_only_processor_still_goes_straight_to_its_page(client, stub_crm, monkeypatch):
    """CCM advertises `hosted_checkout` rather than `hpp`, and no direct card."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: {
            "mode": "options",
            "intent_id": "intent-ccm",
            "routing": {"session_id": "sess-1", "processor": "ccm", "attempt": 1},
            "options": {"hosted_checkout": {"start_url": "https://crm.example/hosted/start"}},
        },
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"mode": "hpp_redirect", "redirect_url": "https://pay.example/ccm"},
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.headers["Location"] == "https://pay.example/ccm"


def test_an_advance_onto_a_direct_card_only_processor_asks_for_the_card(client, stub_crm, monkeypatch):
    """The Colombia cascade can advance onto Worldpay, which has no hosted page.
    Before this, that advance ended on the failure page."""

    def fake_init(self, token, payload):
        if payload.get("routing_session_id"):
            return _direct_card_only_init("worldpay", intent_id="intent-2")
        return _options_init("emerchant")

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(ADVANCE))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda *a, **k: pytest.fail("started a hosted page for a direct-card-only processor"),
    )

    resp = _top_up(client)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/wallet/topup/intent-2/pay")


def test_the_hosted_page_button_is_hidden_when_there_is_no_hosted_page(client, stub_crm, monkeypatch):
    monkeypatch.setattr(
        CRMClient, "wallet_topup_init", lambda self, token, payload: _direct_card_only_init("worldpay")
    )

    pay_url = client.post("/wallet/add-funds", data={"amount": "20.00"}).headers["Location"]
    body = client.get(pay_url).get_data(as_text=True)

    assert "secure page instead" not in body


def test_the_hosted_page_button_is_offered_when_there_is_one(client, stub_crm, monkeypatch):
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("worldpay"))

    pay_url = client.post("/wallet/add-funds", data={"amount": "20.00"}).headers["Location"]
    body = client.get(pay_url).get_data(as_text=True)

    assert "secure page instead" in body


# --- One intent per top-up ---
#
# `topup/init` creates a payment intent, and the CRM keeps it whether or not
# anyone pays it. The site used to call it once on page load with a made-up
# GBP 5.00 amount, purely to find out which processor the country routed to, so
# every visit to Add Funds left a pending top-up nobody had asked for. API 58
# offers no way to ask that question, and its own recommended flow never needs
# to: take the amount, create one intent, then do what the response says.


def _customer_in(country: str):
    """A fresh logged-in client, as a new login from `country` would be."""
    from app import app as flask_app

    c = flask_app.test_client()
    with c.session_transaction() as s:
        s["crm_token"] = "test-token"
        s["customer"] = {
            "id": 1,
            "email": "test@example.com",
            "country": country,
            # An address on file, so these tests route and count intents rather
            # than stopping at the form a customer without one is shown.
            "street": "1 Main St",
            "city": "Springfield",
            "postal_code": "12345",
        }
    return c


def test_browsing_the_add_funds_page_creates_nothing(stub_crm, monkeypatch):
    """Ten customers looking at the page must leave no trace in the CRM."""
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or _options_init("worldpay"),
    )

    for _ in range(10):
        assert _customer_in("IE").get("/wallet/add-funds").status_code == 200

    assert inits == []


def test_paying_by_card_creates_exactly_one_intent(stub_crm, monkeypatch):
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or _options_init("worldpay"),
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", lambda *a, **k: {"status": "completed"})

    payer = _customer_in("IE")
    payer.get("/wallet/add-funds")
    _top_up(payer)

    assert len(inits) == 1
    assert inits[0]["amount_cents"] == 2000, "the amount the customer asked for, not a placeholder"


def test_the_hosted_page_route_also_creates_exactly_one_intent(stub_crm, monkeypatch):
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )

    payer = _customer_in("DE")
    payer.get("/wallet/add-funds")
    resp = payer.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.headers["Location"] == "https://pay.example/hpp"
    assert len(inits) == 1


def test_a_customer_can_change_their_mind_and_use_the_hosted_page(stub_crm, monkeypatch):
    """
    The choice UI `start_hpp: false` exists for: both flows are offered on the
    intent that already exists, so switching does not start another one.
    """
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or _options_init("worldpay"),
    )
    started: list[str] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: started.append(intent_id)
        or {"mode": "hpp_redirect", "redirect_url": "https://pay.example/hosted"},
    )

    payer = _customer_in("IE")
    payer.post("/wallet/add-funds", data={"amount": "20.00"})
    resp = payer.post("/wallet/topup/intent-1/hosted")

    assert resp.headers["Location"] == "https://pay.example/hosted"
    assert started == ["intent-1"]
    assert len(inits) == 1


def test_the_country_used_for_routing_is_the_one_on_the_customer_record(stub_crm, monkeypatch):
    """Processor Rules match on country, so each customer routes on their own."""
    seen: list[str] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: seen.append(str(payload.get("country") or "")) or dict(CCM_OPTIONS_INIT),
    )

    _customer_in("IE").post("/wallet/add-funds", data={"amount": "20.00"})
    _customer_in("DE").post("/wallet/add-funds", data={"amount": "20.00"})

    assert seen == ["IE", "DE"]


def test_account_renders_when_crm_down(client, stub_crm, monkeypatch):
    def down(self, *a, **k):
        raise CRMError("CRM HTTP 503: down", status_code=503)

    for m in ("customer_me", "wallet", "wallet_transactions", "orders", "winnings_tickets"):
        monkeypatch.setattr(CRMClient, m, down)
    resp = client.get("/account")
    # Friendly degraded page, not a stack trace.
    assert resp.status_code == 200


# --- the hosted start response itself ---


def test_a_hosted_start_that_omits_its_mode_still_sends_the_customer_to_pay(client, stub_crm, monkeypatch):
    """
    Reported live 2026-09-09: "Hosted payment page unavailable" on every attempt
    from the campaign emails, with a working payment URL in the response that
    produced it. `/hpp/start` has answered with `mode: "hpp_redirect"`, with
    `mode: "hosted_redirect"` and with no mode at all, and the instruction is
    the URL rather than the label on it.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(CCM_OPTIONS_INIT))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"redirect_url": "https://ccm.example/hosted/abc"},
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.headers["Location"] == "https://ccm.example/hosted/abc"


def test_a_hosted_start_posting_a_form_is_followed_whatever_it_calls_its_mode(client, stub_crm, monkeypatch):
    """The self-submitting form shape, unlabelled."""
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(CCM_OPTIONS_INIT))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {
            "redirect": {"method": "POST", "action_url": "https://ccm.example/3ds", "form_fields": {"MD": "1"}},
        },
    )

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.status_code == 200
    assert "https://ccm.example/3ds" in resp.get_data(as_text=True)


def test_a_hosted_start_with_nothing_usable_says_what_came_back(client, stub_crm, monkeypatch, caplog):
    """
    The one failure on this path that logged no evidence: the customer saw
    "Hosted payment page unavailable" and the log recorded only that they had.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(CCM_OPTIONS_INIT))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_hpp_start",
        lambda self, token, intent_id: {"status": "pending", "intent_id": intent_id},
    )

    with caplog.at_level(logging.WARNING):
        resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert "/wallet/topup/failed" in resp.headers["Location"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "intent-ccm" in logged
    assert "top_level=['intent_id', 'status']" in logged


def test_a_pinned_processor_says_so_in_the_log(client, stub_crm, monkeypatch, caplog):
    """
    `WALLET_TOPUP_PROCESSOR` skips Processor Rules entirely and pins every
    customer to one processor. Set on a live server and forgotten, it presents
    as "payments are broken" with nothing in the log connecting the two.
    """
    monkeypatch.setitem(flask_app.config, "WALLET_TOPUP_PROCESSOR_OVERRIDE", "ccm")
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )

    with caplog.at_level(logging.WARNING):
        client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert inits[0]["processor"] == "ccm"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "WALLET_TOPUP_PROCESSOR=ccm is overriding CRM payment routing" in logged


def test_routing_is_left_to_the_crm_when_nothing_is_pinned(client, stub_crm, monkeypatch, caplog):
    """The default has to be silence and no `processor` field, or the warning
    above becomes noise and stops meaning anything."""
    monkeypatch.setitem(flask_app.config, "WALLET_TOPUP_PROCESSOR_OVERRIDE", "")
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )

    with caplog.at_level(logging.WARNING):
        client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert "processor" not in inits[0]
    assert "overriding CRM payment routing" not in "\n".join(r.getMessage() for r in caplog.records)


def test_the_processors_own_reason_reaches_the_customer(client, stub_crm, monkeypatch):
    """
    CRM will start answering /hpp/start with 400 and the gateway's text (live
    intent 3282: CCM refused with "Ship address can not be empty" while CRM
    still answered 200). A customer can act on that; "Hosted payment page
    unavailable" tells them only to try again and fail again.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: dict(CCM_OPTIONS_INIT))

    def refuse(self, token, intent_id):
        raise CRMError("CRM HTTP 400: Ship address can not be empty", status_code=400)

    monkeypatch.setattr(CRMClient, "wallet_topup_hpp_start", refuse)

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert "Ship+address+can+not+be+empty" in resp.headers["Location"]


def test_a_hosted_fallback_does_not_bury_why_the_hosted_page_refused(client, stub_crm, monkeypatch):
    """
    Falling back from a refused card charge sets its own failure wording, to
    explain why the customer was moved to the hosted page. Once that page gives
    a reason of its own, that reason is the one worth showing.
    """
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, token, payload: _options_init("worldpay"))

    def refuse_charge(self, token, intent_id, payload):
        raise CRMError(
            "CRM HTTP 422: Direct card charging is only available for eltrovox/emerchant/worldpay intents",
            status_code=422,
        )

    def refuse_hosted(self, token, intent_id):
        raise CRMError("CRM HTTP 400: Ship address can not be empty", status_code=400)

    monkeypatch.setattr(CRMClient, "wallet_topup_charge", refuse_charge)
    monkeypatch.setattr(CRMClient, "wallet_topup_hpp_start", refuse_hosted)

    resp = _top_up(client)

    assert "Ship+address+can+not+be+empty" in resp.headers["Location"]
    assert "Direct+card+is+unavailable" not in resp.headers["Location"]


# --- an address for a hosted page that will ask for one ---


def _customer_without_an_address():
    """A logged-in customer the CRM holds no address for."""
    c = flask_app.test_client()
    with c.session_transaction() as s:
        s["crm_token"] = "test-token"
        s["customer"] = {"id": 1, "email": "test@example.com", "country": "GB"}
    return c


def test_a_customer_with_no_address_is_asked_for_one_before_the_intent_exists(stub_crm, monkeypatch):
    """
    CCM refused live intent 3282 with "Ship address can not be empty". Our card
    form is the only place the site asks for an address and a hosted-only
    processor never shows it, so without this the customer had no screen on
    which to fix the one thing standing between them and paying.
    """
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda *a, **k: pytest.fail("created an intent a processor would refuse for want of an address"),
    )
    payer = _customer_without_an_address()

    assert 'name="billing_street"' in payer.get("/wallet/add-funds").get_data(as_text=True)

    resp = payer.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.status_code == 302
    assert "/wallet/add-funds" in resp.headers["Location"]


def test_the_address_is_sent_with_the_top_up_so_the_processor_can_have_it(stub_crm, monkeypatch):
    """
    API 62 persists these fields before it routes, which is the only moment an
    address can still reach a processor we will never show a card form to.
    """
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )
    payer = _customer_without_an_address()

    resp = payer.post(
        "/wallet/add-funds",
        data={
            "amount": "20.00",
            "billing_street": "13056 21 Avenue",
            "billing_city": "Surrey",
            "billing_state": "BC",
            "billing_postcode": "V4A 8M2",
        },
    )

    assert resp.headers["Location"] == "https://pay.example/hpp"
    sent = inits[0]
    assert sent["street"] == "13056 21 Avenue"
    assert sent["city"] == "Surrey"
    assert sent["postal_code"] == "V4A 8M2"
    assert sent["country"] == "GB"
    assert sent["mailing_address"]["state"] == "BC"


def test_half_an_address_is_not_an_address(stub_crm, monkeypatch):
    """A street with no postcode fails at the gateway exactly as none would."""
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda *a, **k: pytest.fail("sent a partial address to a processor"),
    )
    payer = _customer_without_an_address()

    resp = payer.post(
        "/wallet/add-funds",
        data={"amount": "20.00", "billing_street": "13056 21 Avenue", "billing_city": "Surrey"},
    )

    assert "/wallet/add-funds" in resp.headers["Location"]


def test_an_address_once_given_is_not_asked_for_again(stub_crm, monkeypatch):
    """
    The CRM only commits it when init reaches it, so a customer whose first
    attempt fails still has one as far as this journey is concerned. Asking
    again would read as the site having lost it.
    """
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )
    payer = _customer_without_an_address()
    payer.post(
        "/wallet/add-funds",
        data={
            "amount": "20.00",
            "billing_street": "13056 21 Avenue",
            "billing_city": "Surrey",
            "billing_postcode": "V4A 8M2",
        },
    )

    assert 'name="billing_street"' not in payer.get("/wallet/add-funds").get_data(as_text=True)
    payer.post("/wallet/add-funds", data={"amount": "20.00"})

    assert len(inits) == 2
    assert inits[1]["street"] == "13056 21 Avenue"


def test_a_customer_who_already_has_an_address_is_not_asked_for_it(client, stub_crm, monkeypatch):
    """The common case stays one field. Re-sending what the CRM already holds
    would also risk overwriting a fuller record with a thinner one."""
    inits: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_init",
        lambda self, token, payload: inits.append(payload) or dict(CCM_OPTIONS_INIT),
    )

    assert 'name="billing_street"' not in client.get("/wallet/add-funds").get_data(as_text=True)
    client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert "street" not in inits[0]
    assert "mailing_address" not in inits[0]


# --- The same processor is never charged twice in one top-up ---
#
# Reported as "charges retried on the same processor three times in a row".
# Three separate holes led there: a second press of Pay while the first charge
# was running, a routing "advance" that named the processor that had just
# failed, and a resume that quietly landed back on it.


def test_a_second_press_of_pay_does_not_charge_the_intent_again(client, stub_crm, monkeypatch):
    """
    A processor that settles by webhook leaves the intent pending, which is
    also what a second press sees while the first charge is still running.
    Each press was its own charge on the same card.
    """
    charges: list[str] = []

    def fake_charge(self, token, intent_id, payload):
        charges.append(intent_id)
        return {"status": "pending"}

    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, t, p: _options_init("worldpay"))
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", fake_charge)

    started = client.post("/wallet/add-funds", data={"amount": "20.00"})
    pay_url = started.headers["Location"]
    first = client.post(pay_url, data=dict(CARD_FORM))
    second = client.post(pay_url, data=dict(CARD_FORM))
    third = client.post(pay_url, data=dict(CARD_FORM))

    assert charges == ["intent-1"]
    # The browser shows the answer to the last press, so it has to be the page
    # that asks the CRM how the first one went, not a failure.
    for resp in (first, second, third):
        assert "/wallet/topup/return/pending" in resp.headers["Location"]


def test_routing_that_names_the_failed_processor_again_is_not_followed(client, stub_crm, monkeypatch, caplog):
    inits: list[dict] = []
    charges: list[str] = []
    _init_then_resume(monkeypatch, _options_init("worldpay", "intent-2"), inits)
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        _declining_charge({**ADVANCE, "processor": "worldpay", "next_processor": "worldpay"}, charges=charges),
    )

    with caplog.at_level("ERROR"):
        resp = _top_up(client)

    assert "/wallet/topup/failed" in resp.headers["Location"]
    assert len(inits) == 1, "the routing session was resumed onto the processor that just failed"
    assert charges == ["intent-1"]
    assert "offered worldpay again" in caplog.text


def test_a_resume_that_lands_back_on_the_failed_processor_is_not_followed(client, stub_crm, monkeypatch, caplog):
    """Routing need not say where it is going. When it goes back, the customer
    must not be handed a card form for the processor that just declined them,
    under a message saying we switched provider."""
    _init_then_resume(monkeypatch, _options_init("worldpay", "intent-2"))
    monkeypatch.setattr(
        CRMClient,
        "wallet_topup_charge",
        _declining_charge({**ADVANCE, "processor": "worldpay", "next_processor": None}),
    )

    with caplog.at_level("ERROR"):
        resp = _top_up(client)

    assert "/wallet/topup/failed" in resp.headers["Location"]
    assert "intent-2" not in resp.headers["Location"]
    assert "resumed onto worldpay again as intent intent-2" in caplog.text


def test_an_init_failure_is_not_retried_on_the_same_processor(client, stub_crm, monkeypatch):
    inits: list[dict] = []

    def fake_init(self, token, payload):
        inits.append(payload)
        raise CRMError(
            "CRM HTTP 502: processor unavailable",
            status_code=502,
            payload={
                "routing": {
                    "session_id": "sess-1",
                    "processor": "worldpay",
                    "can_advance": True,
                    "next_processor": "worldpay",
                    "resume_payload": {"routing_session_id": "sess-1"},
                }
            },
        )

    monkeypatch.setattr(CRMClient, "wallet_topup_init", fake_init)

    resp = client.post("/wallet/add-funds", data={"amount": "20.00"})

    assert resp.status_code == 302
    assert len(inits) == 1


def test_a_new_top_up_may_use_a_processor_an_earlier_one_tried(client, stub_crm, monkeypatch):
    """The rule is per top-up. A customer who comes back later is routed
    afresh, and the processor that failed then may well be the right one now."""
    counter = iter(range(1, 10))
    charges: list[str] = []
    monkeypatch.setattr(
        CRMClient, "wallet_topup_init", lambda self, t, p: _options_init("worldpay", f"intent-{next(counter)}")
    )
    monkeypatch.setattr(CRMClient, "wallet_topup_charge", _declining_charge(NO_ADVANCE, charges=charges))

    _top_up(client)
    _top_up(client)

    assert charges == ["intent-1", "intent-2"]


def test_the_pay_button_cannot_be_pressed_twice(client, stub_crm, monkeypatch):
    monkeypatch.setattr(CRMClient, "wallet_topup_init", lambda self, t, p: _options_init("worldpay"))
    started = client.post("/wallet/add-funds", data={"amount": "20.00"})

    body = client.get(started.headers["Location"]).get_data(as_text=True)

    assert "payBtn.disabled = true" in body
    assert "if (sent) { e.preventDefault(); return; }" in body
