"""
Prefilled sign-up for reactivation links.

325,938 former customers from the old AS400 database are being invited back.
They have no account, so unlike the `/set-password` campaign they have to
register - and the median age on the list is 71, so the link carries a token
the website exchanges for their name, email and date of birth rather than
asking them to retype twenty-year-old details.

Two rules run through every test here.

The token is a lookup key for someone's name and date of birth, so it must
never reach a log line or an analytics payload, and the details it maps to must
never reach the URL or the session cookie.

And it is a shortcut, not a gate. An expired token, a Module that is down and a
Module that is slow all have the same answer - an ordinary empty form - because
no failure of ours is worth stopping a third of a million people registering.
"""

from __future__ import annotations

import json
import logging

import pytest

from crm_api import CRMClient, CRMError

from test_offers import _bundle, catalog, serve_bundle  # noqa: F401 - fixtures


SLUG = "PB_WelcomeDB"
ONE_LINE = json.dumps([{"main": "1,2,3,4,5", "power": 6}])
TOKEN = "rt_9f3c1a8e44b27d5061fe8a"
LINK = f"/offer/{SLUG}?src=reactivation&cmp=01-probe-priority&intent=lifecycle&rt={TOKEN}"

# What a completed form sends. Their own password, their own confirmation, and
# whatever they corrected on the way through.
FORM = {
    "email": "lenp14@hotmail.co.uk",
    "password": "Sixpence!9",
    "title": "Mr",
    "first_name": "Len",
    "last_name": "Pantlin",
    "birthdate": "1969-07-14",
    "currency": "GBP",
    "accept_terms": "on",
}


@pytest.fixture
def promo_offer(serve_bundle):  # noqa: F811
    serve_bundle(_bundle(SLUG, [{"product_code": "PSX-W", "quantity": 1}], base_currency="GBP"))


def _arrive_and_buy(client):
    """The reactivation click, the boards, and Buy."""
    client.get(LINK)
    return client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})


def _value_of(body: str, field_id: str) -> str:
    """The `value` of one input, read off the rendered page."""
    tag = body.split(f'id="{field_id}"')[0].rsplit("<input", 1)[1] + body.split(f'id="{field_id}"')[1].split(">")[0]
    if 'value="' not in tag:
        return ""
    return tag.split('value="')[1].split('"')[0]


def _register_payload(monkeypatch) -> list[dict]:
    """Records what registration asked the CRM to create."""
    sent: list[dict] = []

    def fake_register(self, payload, *a, **kw):
        sent.append(dict(payload))
        return {"token": "test-token", "customer": {"id": 77, "email": payload.get("email"),
                                                    "customer_number": payload.get("customer_number")}}

    monkeypatch.setattr(CRMClient, "auth_register", fake_register)
    return sent


# --- 1. the form arrives filled in ---


def test_a_reactivation_link_leads_to_a_sign_up_form_with_their_details_in_it(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    The whole point of the campaign: a 71-year-old should not have to retype
    what we already know about them.
    """
    buy = _arrive_and_buy(anon_client)

    assert buy.status_code == 302
    assert "/create-account" in buy.headers["Location"]

    body = anon_client.get(buy.headers["Location"]).get_data(as_text=True)

    assert _value_of(body, "registerEmail") == "lenp14@hotmail.co.uk"
    assert _value_of(body, "registerFirstName") == "Len"
    assert _value_of(body, "registerLastName") == "Pantlin"
    assert _value_of(body, "birthdate") == "1969-07-14"


def test_someone_with_no_account_is_not_sent_to_a_cart_that_asks_them_to_sign_in(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    These people have no account at all, so the cart's "sign in to see your
    quote" is a dead end. The sign-up form is the only way forward.
    """
    assert "/create-account" in _arrive_and_buy(anon_client).headers["Location"]


def test_registering_from_an_offer_goes_on_to_the_cart_and_not_to_the_account_page(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    They were buying something. Registration is a detour in the middle of that,
    and landing them on their account page abandons the cart they just built.
    """
    _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    done = anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert done.status_code == 302
    assert done.headers["Location"].endswith("/cart")


def test_the_date_of_birth_dropdowns_are_set_from_the_prefilled_date(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    The date lives on a hidden field and the customer reads three dropdowns.
    If those are not set, they see "Day Month Year" over a date they cannot
    check, and touching any one of them wipes it.
    """
    _arrive_and_buy(anon_client)
    body = anon_client.get("/create-account").get_data(as_text=True)

    assert "prefilled[1]" in body
    assert 'id="birthdate" value="1969-07-14"' in body


# --- 2. every field stays editable ---


def test_what_they_corrected_is_what_gets_saved(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    The details are up to twenty years old. A married name, a new email - the
    form is a starting point, and the CRM must be sent what they confirmed
    rather than what we guessed.
    """
    sent = _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    anon_client.post(
        "/create-account",
        data={**FORM, "email": "len.pantlin@gmail.com", "last_name": "Pantlin-Shaw", "birthdate": "1969-07-15"},
    )

    assert sent[0]["email"] == "len.pantlin@gmail.com"
    assert sent[0]["last_name"] == "Pantlin-Shaw"
    assert sent[0]["birthdate"] == "1969-07-15"


def test_no_prefilled_field_is_locked(anon_client, stub_crm, stub_mkt, promo_offer):
    _arrive_and_buy(anon_client)
    body = anon_client.get("/create-account").get_data(as_text=True)

    for field_id in ("registerEmail", "registerFirstName", "registerLastName"):
        tag = body.split(f'id="{field_id}"')[1].split(">")[0]
        assert "readonly" not in tag
        assert "disabled" not in tag


def test_they_still_choose_a_password_and_accept_the_terms(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    This prefills a form; it does not create an account. That distinction is
    the reason for doing it this way instead of importing the list.
    """
    sent = _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    without_terms = {k: v for k, v in FORM.items() if k != "accept_terms"}
    anon_client.post("/create-account", data=without_terms)

    assert sent == []


def test_the_prefilled_currency_is_a_default_they_can_change(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    `currency` is a sensible default for their account. It is not the offer's
    price, which is locked in its own currency and does not move.
    """
    sent = _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    assert 'value="GBP" selected' in anon_client.get("/create-account").get_data(as_text=True)

    anon_client.post("/create-account", data={**FORM, "currency": "EUR"})

    assert sent[0]["currency"] == "EUR"


# --- 3. a refresh keeps it ---


def test_refreshing_the_sign_up_page_keeps_the_details(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    Refreshes and back-buttons are ordinary on a sign-up form, doubly so at
    this age. Reading the Module again is explicitly allowed and the token
    confers no authority, so a second read grants nothing the first did.
    """
    _arrive_and_buy(anon_client)

    first = anon_client.get("/create-account").get_data(as_text=True)
    second = anon_client.get("/create-account").get_data(as_text=True)

    assert _value_of(first, "registerFirstName") == "Len"
    assert _value_of(second, "registerFirstName") == "Len"
    assert len(stub_mkt.prefill_calls) >= 2


def test_their_name_and_date_of_birth_are_not_kept_in_the_session_cookie(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    Re-reading the Module rather than caching the answer is the point. The
    session is a signed cookie that travels on every single request, and a
    date of birth has no business riding along in one.
    """
    _arrive_and_buy(anon_client)
    anon_client.get("/create-account")

    with anon_client.session_transaction() as s:
        held = json.dumps({k: v for k, v in s.items()})

    assert "Pantlin" not in held
    assert "1969-07-14" not in held
    assert "lenp14" not in held


# --- 4. a dead token changes nothing ---


@pytest.mark.parametrize("reason", ["unknown", "expired", "revoked", "missing"])
def test_a_dead_token_gives_an_ordinary_empty_form_and_no_error(
    anon_client, stub_crm, stub_mkt, promo_offer, reason
):
    """
    These links live thirty days and people forward them. Someone opening one
    in February must still be able to buy.
    """
    stub_mkt.response = {"ok": False, "reason": reason}
    _arrive_and_buy(anon_client)

    page = anon_client.get("/create-account")
    body = page.get_data(as_text=True)

    assert page.status_code == 200
    assert _value_of(body, "registerFirstName") == ""
    assert "expired" not in body.lower()
    assert "sorry" not in body.lower()


def test_a_token_that_is_not_a_token_is_never_carried_at_all(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    anon_client.get(f"/offer/{SLUG}?rt=<script>")
    anon_client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})

    assert stub_mkt.prefill_calls == []


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("mkt.cloudandahalf.com refused the connection"),
        TimeoutError("timed out"),
        ValueError("not json"),
    ],
)
def test_a_module_that_is_down_or_slow_still_lets_them_register(
    anon_client, stub_crm, stub_mkt, promo_offer, failure
):
    """
    "Do not show an error, and do not make them wait." A prefill is worth some
    typing saved; it is not worth a sign-up.
    """
    stub_mkt.error = failure
    _arrive_and_buy(anon_client)

    page = anon_client.get("/create-account")

    assert page.status_code == 200
    assert _value_of(page.get_data(as_text=True), "registerFirstName") == ""


def test_a_module_that_is_not_configured_at_all_is_not_an_error(
    anon_client, stub_crm, promo_offer, monkeypatch
):
    """
    Only reactivation links use the Module. Every other deployment, and every
    developer's machine, has to work without it.
    """
    monkeypatch.delenv("MM_BASE_URL", raising=False)
    monkeypatch.delenv("MM_API_KEY", raising=False)
    _arrive_and_buy(anon_client)

    assert anon_client.get("/create-account").status_code == 200


def test_a_module_failure_does_not_put_the_url_it_called_in_the_log(
    anon_client, stub_crm, stub_mkt, promo_offer, caplog
):
    """
    A `requests` failure names the URL it was calling, and that URL carries the
    token in its query string. So the class of the failure is logged and its
    message is not.
    """
    stub_mkt.error = ConnectionError(f"failed: http://mkt.invalid/api/service/prefill?token={TOKEN}")
    _arrive_and_buy(anon_client)

    with caplog.at_level(logging.DEBUG):
        anon_client.get("/create-account")

    assert TOKEN not in caplog.text
    assert "ConnectionError" in caplog.text


# --- 5. no token, nothing different ---


def test_an_ordinary_visitor_never_touches_the_module(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    anon_client.get(f"/offer/{SLUG}")
    buy = anon_client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})

    assert buy.headers["Location"].endswith("/cart")
    assert stub_mkt.prefill_calls == []


def test_an_ordinary_registration_still_lands_on_the_account_page(
    anon_client, stub_crm, stub_mkt, monkeypatch
):
    _register_payload(monkeypatch)

    done = anon_client.post("/create-account", data=FORM)

    assert done.headers["Location"].endswith("/account")


def test_an_ordinary_sign_up_page_stays_indexable(anon_client, stub_crm, stub_mkt):
    page = anon_client.get("/create-account")

    assert "noindex" not in page.get_data(as_text=True)
    assert page.headers.get("Referrer-Policy") != "no-referrer"


def test_someone_already_signed_in_is_not_diverted_to_a_sign_up_form(
    client, stub_crm, stub_mkt, promo_offer
):
    client.get(LINK)
    buy = client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})

    assert buy.headers["Location"].endswith("/cart")


# --- 6. the account carries its AS400 id ---


def test_the_new_account_carries_the_customer_number(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    Their AS400 id is the only thing tying a new account to fifteen years of
    purchase history.
    """
    sent = _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    anon_client.post("/create-account", data=FORM)

    assert sent[0]["customer_number"] == "E9654293"


def test_the_customer_number_cannot_be_claimed_by_editing_the_form(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    Read from the Module again rather than carried through a hidden field,
    because a hidden field would let anyone inherit somebody else's history by
    editing it.
    """
    sent = _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    anon_client.post("/create-account", data={**FORM, "customer_number": "E0000001"})

    assert sent[0]["customer_number"] == "E9654293"


def test_an_ordinary_registration_sends_no_customer_number(
    anon_client, stub_crm, stub_mkt, monkeypatch
):
    sent = _register_payload(monkeypatch)

    anon_client.post("/create-account", data=FORM)

    assert "customer_number" not in sent[0]


def test_a_crm_that_refuses_the_customer_number_does_not_stop_the_sign_up(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch, caplog
):
    """
    The field is not in the register contract (API 67) even though the column
    exists. An account needing its history linked by hand is a far smaller
    problem than turning away everyone on the list - but it has to be said out
    loud, because nobody would otherwise notice.
    """
    sent: list[dict] = []

    def fussy_register(self, payload, *a, **kw):
        sent.append(dict(payload))
        if "customer_number" in payload:
            raise CRMError("CRM HTTP 422: unknown field customer_number", status_code=422)
        return {"token": "test-token", "customer": {"id": 77}}

    monkeypatch.setattr(CRMClient, "auth_register", fussy_register)
    _arrive_and_buy(anon_client)

    with caplog.at_level(logging.ERROR):
        done = anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert done.headers["Location"].endswith("/cart")
    assert len(sent) == 2
    assert "customer_number" not in sent[1]
    assert "E9654293" in caplog.text


def test_a_crm_that_accepts_the_customer_number_and_drops_it_is_reported(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch, caplog
):
    """
    Silently dropping it would leave a reactivated customer looking brand new
    for ever, and the register response is the only chance to notice.
    """
    def forgetful_register(self, payload, *a, **kw):
        return {"token": "test-token", "customer": {"id": 77}}

    monkeypatch.setattr(CRMClient, "auth_register", forgetful_register)
    _arrive_and_buy(anon_client)

    with caplog.at_level(logging.ERROR):
        anon_client.post("/create-account", data=FORM)

    assert "did not keep customer_number" in caplog.text
    assert "E9654293" in caplog.text


def test_a_registration_that_kept_the_number_is_not_reported_as_a_problem(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch, caplog
):
    _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    with caplog.at_level(logging.ERROR):
        anon_client.post("/create-account", data=FORM)

    assert "customer_number" not in caplog.text


def test_a_failed_registration_returns_to_the_form_without_losing_the_cart(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    Sending them back to fix a form must not also send them back to the start
    of the purchase.
    """
    monkeypatch.setattr(
        CRMClient,
        "auth_register",
        lambda self, payload, *a, **kw: (_ for _ in ()).throw(CRMError("CRM HTTP 409: email in use", status_code=409)),
    )
    _arrive_and_buy(anon_client)

    back = anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert "next=%2Fcart" in back.headers["Location"] or "next=/cart" in back.headers["Location"]


# --- 7. the campaign survives the detour ---


def test_the_source_and_campaign_survive_registration_and_reach_the_order(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    The one most likely to break. Registration is a redirect in the middle of
    the journey, and attribution held only in the URL is dropped there - which
    would make the campaign unmeasurable while looking like it worked.

    It survives because it is read off the link once and kept server-side, so
    it is still there after the detour, on the account and on every event the
    purchase emits.
    """
    sent = _register_payload(monkeypatch)
    events: list[dict] = []
    monkeypatch.setattr(
        CRMClient, "marketing_events", lambda self, payload, *a, **kw: events.append(payload) or {"ok": True}
    )

    anon_client.get(f"{LINK}&tid=c2_lou9sv44yj13ti")
    anon_client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})
    anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert sent[0]["acquisition_campaign_code"] == "01-probe-priority"
    assert sent[0]["acquisition_click_id"] == "c2_lou9sv44yj13ti"
    # A lifecycle touch must not overwrite an acquisition source, so `src` is
    # deliberately not sent - the campaign is what identifies this list.
    assert "acquisition_source_code" not in sent[0]
    # And on to the order: the purchase's own events carry it too.
    completed = [e for e in events if e.get("event_type") == "signup_completed"]
    assert completed and completed[0]["campaign_code"] == "01-probe-priority"
    assert completed[0]["click_id"] == "c2_lou9sv44yj13ti"


def test_the_campaign_is_taken_from_the_module_when_the_link_forgot_it(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    Attribution comes off the URL, and it is right there in the link. But a
    link template that shipped without `cmp` would leave the campaign
    unmeasurable while everything else worked, and the Module tells us which
    campaign it sent this link for.
    """
    sent = _register_payload(monkeypatch)

    anon_client.get(f"/offer/{SLUG}?src=reactivation&intent=lifecycle&rt={TOKEN}")
    anon_client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})
    anon_client.post("/create-account", data=FORM)

    assert sent[0]["acquisition_campaign_code"] == "01-probe-priority"


def test_a_campaign_named_in_the_link_is_not_overruled_by_the_module(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    sent = _register_payload(monkeypatch)
    anon_client.get(f"/offer/{SLUG}?cmp=02-holdback&intent=lifecycle&rt={TOKEN}")
    anon_client.post(f"/offer/{SLUG}/start", data={"lines_json": ONE_LINE})
    anon_client.post("/create-account", data=FORM)

    assert sent[0]["acquisition_campaign_code"] == "02-holdback"


# --- 8. the token appears nowhere it should not ---


def test_the_token_is_in_no_log_line_anywhere_in_the_journey(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch, caplog
):
    _register_payload(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        _arrive_and_buy(anon_client)
        anon_client.get("/create-account")
        anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert TOKEN not in caplog.text


def test_the_token_is_in_no_analytics_call(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    events: list[dict] = []
    monkeypatch.setattr(
        CRMClient, "marketing_events", lambda self, payload, *a, **kw: events.append(payload) or {"ok": True}
    )

    _arrive_and_buy(anon_client)
    anon_client.get("/create-account")
    anon_client.post("/api/track/pageview", json={"path": f"/offer/{SLUG}?rt={TOKEN}"})
    anon_client.post("/api/track/click", json={"metadata": {"cta": "register", "href": f"/x?rt={TOKEN}"}})

    assert events
    assert TOKEN not in json.dumps(events)


def test_a_page_view_reports_the_page_and_not_its_query_string(
    anon_client, stub_crm, stub_mkt, monkeypatch
):
    """
    The browser sends a bare pathname today. This does not rely on that: the
    page decides what to report, and the guarantee has to hold on our side of
    the wire. Nothing of analytical value is lost, because attribution reaches
    the Module separately from the session.
    """
    events: list[dict] = []
    monkeypatch.setattr(
        CRMClient, "marketing_events", lambda self, payload, *a, **kw: events.append(payload) or {"ok": True}
    )

    anon_client.post("/api/track/pageview", json={"path": f"/offer/{SLUG}?src=reactivation&rt={TOKEN}"})

    assert events[0]["metadata"]["path"] == f"/offer/{SLUG}"


def test_the_set_password_token_is_held_to_the_same_rule(
    anon_client, stub_crm, stub_mkt, monkeypatch
):
    events: list[dict] = []
    monkeypatch.setattr(
        CRMClient, "marketing_events", lambda self, payload, *a, **kw: events.append(payload) or {"ok": True}
    )

    anon_client.post("/api/track/click", json={"metadata": {"cta": "register", "page": "/x?spt=abcdef123456789012"}})

    assert "abcdef123456789012" not in json.dumps(events)


def test_the_token_leaves_the_address_bar_and_is_not_in_the_page(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    _arrive_and_buy(anon_client)
    page = anon_client.get("/create-account")

    assert TOKEN not in page.get_data(as_text=True)


def test_the_module_key_never_reaches_the_browser(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    _arrive_and_buy(anon_client)

    assert "test-mm-key" not in anon_client.get("/create-account").get_data(as_text=True)


# --- the hardening ---


def test_a_sign_up_page_carrying_a_token_stays_out_of_search_and_referrers(
    anon_client, stub_crm, stub_mkt, promo_offer
):
    """
    Same three as `/set-password`, for the same reasons: the page is reachable
    with a token in the session, so it must not be indexed, must not hand the
    referrer to every asset host, and must not sit in a shared machine's back
    button.
    """
    _arrive_and_buy(anon_client)
    page = anon_client.get("/create-account")
    body = page.get_data(as_text=True)

    assert '<meta name="robots" content="noindex, nofollow">' in body
    assert page.headers["Referrer-Policy"] == "no-referrer"
    assert page.headers["Cache-Control"] == "no-store"


def test_a_dead_token_is_still_protected(anon_client, stub_crm, stub_mkt, promo_offer):
    """
    The protection follows the token being present, not the prefill working.
    A refused token was still in a URL.
    """
    stub_mkt.response = {"ok": False, "reason": "expired"}
    _arrive_and_buy(anon_client)
    page = anon_client.get("/create-account")

    assert page.headers["Referrer-Policy"] == "no-referrer"
    assert "noindex" in page.get_data(as_text=True)


# --- telling the Module they finished ---


def test_finishing_the_form_is_reported_back_to_the_module(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    The gap between opening a prefilled form and completing it is the drop-off
    worth measuring, and only the website knows when the second one happens.
    """
    _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)
    anon_client.post("/create-account", data=FORM)

    assert stub_mkt.registered_calls == [("lottoexpress", TOKEN)]


def test_a_form_that_was_not_finished_is_not_reported(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    monkeypatch.setattr(
        CRMClient,
        "auth_register",
        lambda self, payload, *a, **kw: (_ for _ in ()).throw(CRMError("CRM HTTP 409", status_code=409)),
    )
    _arrive_and_buy(anon_client)
    anon_client.post("/create-account", data=FORM)

    assert stub_mkt.registered_calls == []


def test_a_module_that_cannot_be_told_does_not_spoil_the_registration(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """Nothing depends on the report, so nothing may break because of it."""
    _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)

    def refuse(self, brand, token):
        raise ConnectionError("no route to host")

    monkeypatch.setattr("mkt_api.MktClient.prefill_registered", refuse)
    done = anon_client.post("/create-account", data={**FORM, "next": "/cart"})

    assert done.status_code == 302
    assert done.headers["Location"].endswith("/cart")


def test_the_token_is_forgotten_once_they_have_an_account(
    anon_client, stub_crm, stub_mkt, promo_offer, monkeypatch
):
    """
    It has done its job. Keeping it would mean a later visit to the sign-up
    page pulling somebody's details back onto a shared machine's screen.
    """
    _register_payload(monkeypatch)
    _arrive_and_buy(anon_client)
    anon_client.post("/create-account", data=FORM)

    with anon_client.session_transaction() as s:
        assert "reactivation_token" not in s
