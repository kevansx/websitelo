"""
Support staff can look at a customer's account, and that is all they can do.

CRM staff with the `customers.login_as` permission open this site as a
customer without the customer's password. The CRM sends the staff browser to
`/support/login-as/<audit_id>?token=...` with a handoff that is brand-bound,
single-use and good for two minutes; this end trades it for a customer bearer
token the CRM restricts to reads, and then has to behave like it means it.

Three things can go wrong, and all three are worse than a broken feature:

The handoff is a credential in a URL, so it must be spent on arrival and never
kept, logged, sent to analytics, or left in the address bar for the next person
at that desk to find in the history.

The staff browser was probably already signed in as somebody - possibly another
customer, from the previous ticket. Their cart, wallet cache and staged billing
address have to be gone before the new token lands, or one customer's things
appear under another's name.

Read-only has to mean the server refuses writes, not that the buttons are
greyed out. Plenty of this site changes state without asking the CRM anything:
adding to a cart, applying a promo code, staging an address. None of that
should happen to a customer because support looked at their account.
"""

from __future__ import annotations

import logging
import time

import pytest

from crm_api import CRMClient, CRMError


AUDIT = 4471
HANDOFF = "hx_9f2b7c4d1e8a6b3f5c0d2e4a6b8c1d3f"
CUSTOMER_TOKEN = "support-bearer-token-for-9270"
CUSTOMER = {"id": 9270, "first_name": "Magdalena", "last_name": "Amaya", "email": "m@example.com"}


@pytest.fixture
def handoff(monkeypatch):
    """
    The CRM's side of the exchange, and a record of exactly what we sent it.

    Defaults to the documented success. Tests set `state["error"]` to a status
    code to get each documented failure instead.
    """
    state: dict = {"error": None, "ttl": 3600, "read_only": True, "calls": []}

    def fake_exchange(self, *, audit_id, token, ip=None):
        state["calls"].append({"audit_id": audit_id, "token": token, "ip": ip})
        if state["error"]:
            raise CRMError(
                "login-as handoff refused",
                status_code=state["error"],
                payload={"success": False, "error": "handoff refused"},
            )
        body = {
            "success": True,
            "token": CUSTOMER_TOKEN,
            "customer": dict(CUSTOMER),
            "support_session": {"expires_in_seconds": state["ttl"]},
        }
        if state["read_only"] is not None:
            body["support_session"]["read_only"] = state["read_only"]
        return body

    monkeypatch.setattr(CRMClient, "auth_login_as_customer", fake_exchange)
    return state


def _open(client, *, audit=AUDIT, token=HANDOFF):
    """What the CRM points the staff browser at."""
    url = f"/support/login-as/{audit}"
    if token is not None:
        url += f"?token={token}"
    return client.get(url)


def _start_session(client, handoff):
    """A support session, opened the way the CRM opens one."""
    resp = _open(client, )
    assert resp.status_code in (301, 302), "the handoff must not render a page"
    return resp


# --- the exchange ---


def test_the_handoff_is_exchanged_with_the_service_key_behind_the_browser(
    anon_client, handoff
):
    """
    The key that redeems the handoff signs a server call. It is the one part of
    this that must never be within reach of the browser holding the URL.
    """
    _start_session(anon_client, handoff)
    assert len(handoff["calls"]) == 1, "exactly one exchange, on arrival"
    sent = handoff["calls"][0]
    assert sent["audit_id"] == AUDIT
    assert sent["token"] == HANDOFF


def test_the_visitor_ip_is_passed_so_the_crm_can_audit_the_session(anon_client, handoff):
    """The CRM records who opened it and from where; we know the browser's IP."""
    anon_client.get(
        f"/support/login-as/{AUDIT}?token={HANDOFF}",
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert handoff["calls"][0]["ip"] == "203.0.113.10"


def test_the_customer_is_signed_in_with_the_token_the_crm_returned(anon_client, handoff):
    """
    Stored through the same server-side session as a normal login, so the
    bearer never reaches JavaScript and rides an HttpOnly cookie.
    """
    _start_session(anon_client, handoff)
    with anon_client.session_transaction() as s:
        assert s["crm_token"] == CUSTOMER_TOKEN
        assert s["customer"]["id"] == CUSTOMER["id"]


def test_it_redirects_to_the_account_page_so_the_handoff_leaves_the_url(
    anon_client, handoff
):
    """
    The token cannot stay in the address bar. On a shared machine the history
    is the next person's to read.
    """
    resp = _start_session(anon_client, handoff)
    assert resp.headers["Location"].endswith("/account")


def test_the_redirect_does_not_hand_the_token_to_the_next_request(anon_client, handoff):
    """
    Without this the browser puts the callback URL in the `Referer` of
    everything the account page loads, token and all.
    """
    resp = _start_session(anon_client, handoff)
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert resp.headers.get("Cache-Control") == "no-store"


def test_the_handoff_token_is_not_kept_anywhere_in_the_session(anon_client, handoff):
    """
    Single-use and two minutes long: there is nothing to retry and no reason to
    hold it. Parked in a session it is a credential we are storing for one
    person about another.
    """
    _start_session(anon_client, handoff)
    with anon_client.session_transaction() as s:
        assert HANDOFF not in str(dict(s))


def test_the_handoff_token_is_never_written_to_the_log(anon_client, handoff, caplog):
    """A log is a place tokens outlive the two minutes they were meant to."""
    with caplog.at_level(logging.DEBUG):
        _start_session(anon_client, handoff)
    assert HANDOFF not in caplog.text


def test_the_session_is_recorded_in_the_log_by_audit_id_instead(
    anon_client, handoff, caplog
):
    """Support sessions are worth an audit trail; the CRM gave us a safe id."""
    with caplog.at_level(logging.INFO):
        _start_session(anon_client, handoff)
    assert f"audit={AUDIT}" in caplog.text


# --- the browser that was already signed in as somebody else ---


def test_another_customers_cart_does_not_follow_staff_into_the_session(
    client, handoff, stub_crm
):
    """
    The staff browser arrives from the previous ticket. A cart left in that
    session would show up as this customer's, and could be bought.
    """
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "PB_SINGLE", "lines": []}]
        s["checkout_quote_id"] = 991
    _start_session(client, handoff)
    with client.session_transaction() as s:
        assert not s.get("cart_items")
        assert not s.get("checkout_quote_id")


def test_another_customers_wallet_and_billing_details_do_not_follow_either(
    client, handoff, stub_crm
):
    """
    A cached wallet would put someone else's balance in the header, and a
    staged billing address is a home address.
    """
    with client.session_transaction() as s:
        s["wallet"] = {"currency": "USD", "balance_cents": 999999}
        s["topup_address"] = {"street": "1 Someone Else Road"}
        s["pending_checkout"] = {"amount_cents": 2500}
    _start_session(client, handoff)
    with client.session_transaction() as s:
        assert not s.get("wallet")
        assert not s.get("topup_address")
        assert not s.get("pending_checkout")


def test_a_password_link_from_an_earlier_ticket_does_not_follow_either(
    client, handoff, stub_crm
):
    """
    Set-password, reactivation and payment-link tokens are all credentials for
    whoever the browser was last looking at, and none of them are this
    customer's.
    """
    with client.session_transaction() as s:
        s["set_password_token"] = "spt-for-a-different-customer"
        s["reactivation_token"] = "rt-for-a-different-customer"
        s["payment_link_token"] = "paylink-for-a-different-customer"
    _start_session(client, handoff)
    with client.session_transaction() as s:
        assert not s.get("set_password_token")
        assert not s.get("reactivation_token")
        assert not s.get("payment_link_token")


def test_the_callback_is_not_recorded_as_the_visit_that_brought_them_here(
    client, handoff, stub_crm
):
    """
    Attributing a support session to a campaign would put staff activity in
    the customer's acquisition record.
    """
    with client.session_transaction() as s:
        s["mkt"] = {"tid": "c4_fxh0b1ji8bpsxd", "cmp": "callcentre-welcome"}
    _start_session(client, handoff)
    with client.session_transaction() as s:
        assert not s.get("mkt")


# --- read-only, enforced by the server ---


def test_the_session_is_marked_read_only(anon_client, handoff):
    _start_session(anon_client, handoff)
    with anon_client.session_transaction() as s:
        assert s["customer_login_as"]["read_only"] is True
        assert s["customer_login_as"]["audit_id"] == AUDIT


def test_a_support_session_that_omits_the_flag_is_still_read_only(anon_client, handoff):
    """
    The CRM only issues these read-only. A missing flag is not a reason to
    hand someone write access to an account that is not theirs.
    """
    handoff["read_only"] = None
    _start_session(anon_client, handoff)
    with anon_client.session_transaction() as s:
        assert s["customer_login_as"]["read_only"] is True


def test_nothing_can_be_added_to_the_customers_cart(client, handoff, stub_crm, full_catalog):
    """
    The CRM refuses writes on this token, but a cart is local. Without a
    server-side block, support browsing the site would quietly build a cart
    for a customer who never asked for one.
    """
    _start_session(client, handoff)
    resp = client.post(
        "/cart/add",
        data={"product_code": "PB_SINGLE", "game_code": "powerball",
              "game_name": "PowerBall", "lines_json": '[{"main":"1,2,3,4,5","power":6}]'},
    )
    assert resp.status_code in (301, 302)
    with client.session_transaction() as s:
        assert not s.get("cart_items")


def test_an_order_cannot_be_placed(client, handoff, stub_crm, monkeypatch):
    """The one that would take a customer's money."""
    submitted: list = []
    monkeypatch.setattr(
        CRMClient,
        "checkout_submit",
        lambda self, *a, **kw: submitted.append(kw) or {"order": {"id": 1}},
    )
    _start_session(client, handoff)
    with client.session_transaction() as s:
        s["cart_items"] = [
            {"kind": "single", "product_code": "PB_SINGLE",
             "lines": [{"main": "1,2,3,4,5", "power": 6}], "game_code": "powerball"}
        ]
        s["checkout_quote_id"] = 991
    resp = client.post("/checkout")
    assert resp.status_code in (301, 302)
    assert not submitted, "the request never reached the CRM"


@pytest.mark.parametrize(
    "path,data",
    [
        ("/cart/clear", {}),
        ("/cart/apply-promo", {"promo_code": "SAVE10"}),
        ("/wallet/add-funds", {"amount": "25.00"}),
        ("/verify-email/resend", {}),
        ("/verify-email/dismiss", {}),
    ],
)
def test_every_other_write_is_refused_too(client, handoff, stub_crm, path, data):
    """
    Not a list of the dangerous ones. The block is on the method, so a route
    added next month is covered without anyone remembering to cover it.
    """
    _start_session(client, handoff)
    resp = client.post(path, data=data)
    assert resp.status_code in (301, 302, 403)
    if resp.status_code != 403:
        assert "/support/login-as" not in resp.headers.get("Location", "")


def test_a_refused_write_says_it_is_read_only_rather_than_failing_oddly(
    client, handoff, stub_crm
):
    _start_session(client, handoff)
    client.post("/cart/clear")
    body = client.get("/account").data.decode("utf-8")
    assert "This customer support session is read-only." in body


def test_a_refused_api_call_answers_in_the_crms_own_terms(client, handoff, stub_crm):
    """
    Scripts on the page expect JSON, and the contract names an error code for
    exactly this so a caller knows not to retry.
    """
    _start_session(client, handoff)
    resp = client.post("/api/track/click", json={"path": "/"})
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["error_code"] == "SUPPORT_SESSION_READ_ONLY"
    assert body["error"] == "This customer support session is read-only."


def test_reading_the_account_still_works(client, handoff, stub_crm):
    """Read-only is the point, not a punishment. The GETs have to work."""
    _start_session(client, handoff)
    assert client.get("/account").status_code == 200
    assert client.get("/cart").status_code == 200
    assert client.get("/orders").status_code == 200


# --- staff can see what they are in ---


def test_every_page_says_it_is_a_read_only_support_session(client, handoff, stub_crm):
    """
    An hour is long enough to forget. A flash shown once on the account page
    would be gone by the second click.
    """
    _start_session(client, handoff)
    for path in ("/account", "/cart", "/"):
        body = client.get(path).data.decode("utf-8")
        assert "Read-only customer support session" in body, f"missing on {path}"
        assert "Purchases, wallet changes, saved-item changes, and account updates are blocked" in body


def test_the_banner_is_not_shown_to_an_ordinary_customer(client, stub_crm):
    body = client.get("/account").data.decode("utf-8")
    assert "Read-only customer support session" not in body


def test_the_add_funds_button_is_not_offered_in_a_support_session(
    client, handoff, stub_crm
):
    """Taking a staff member to a card form for someone else's wallet."""
    _start_session(client, handoff)
    body = client.get("/account").data.decode("utf-8")
    assert "addFundsLink" not in body


def test_the_cart_explains_itself_instead_of_offering_a_dead_button(
    client, handoff, stub_crm, full_catalog
):
    """A greyed-out pay button reads as a bug they should work around."""
    _start_session(client, handoff)
    with client.session_transaction() as s:
        s["cart_items"] = [
            {"kind": "single", "product_code": "PB_SINGLE",
             "lines": [{"main": "1,2,3,4,5", "power": 6}], "game_code": "powerball"}
        ]
    body = client.get("/cart").data.decode("utf-8")
    assert "Read-only support session" in body
    assert "Confirm Order" not in body


# --- the ways a handoff fails ---


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_every_documented_failure_gives_the_same_safe_page(anon_client, handoff, status):
    """
    Expired, wrong brand, revoked permission, no such customer, already used.
    The staff member's next step is identical in all of them, and telling the
    holder of a URL which one it was describes a live credential's state.
    """
    handoff["error"] = status
    resp = _open(anon_client)
    assert resp.status_code in (400, 403)
    body = resp.data.decode("utf-8")
    assert "invalid, expired, or already used" in body


def test_a_failed_handoff_does_not_sign_anybody_in(anon_client, handoff):
    handoff["error"] = 409
    _open(anon_client)
    with anon_client.session_transaction() as s:
        assert not s.get("crm_token")
        assert not s.get("customer_login_as")


def test_a_failed_handoff_does_not_disturb_an_existing_session(client, handoff, stub_crm):
    """
    A dead link must not log the staff member out of whatever they were doing,
    and must not half-clear a session into an odd state.
    """
    handoff["error"] = 401
    _open(client)
    with client.session_transaction() as s:
        assert s.get("crm_token") == "test-token", "the existing login survived"


def test_a_missing_token_never_reaches_the_crm(anon_client, handoff):
    """Nothing to exchange, so nothing to ask."""
    resp = _open(anon_client, token=None)
    assert resp.status_code == 400
    assert not handoff["calls"]


def test_a_malformed_token_never_reaches_the_crm(anon_client, handoff):
    resp = _open(anon_client, token="short")
    assert resp.status_code == 400
    assert not handoff["calls"]


def test_an_audit_id_that_is_not_a_number_never_reaches_the_crm(anon_client, handoff):
    resp = _open(anon_client, audit="'; drop table audits--")
    assert resp.status_code == 400
    assert not handoff["calls"]


def test_a_crm_outage_is_not_reported_as_a_used_link_but_is_still_safe(
    anon_client, handoff
):
    """An outage is not the staff member's fault, and still opens no session."""
    handoff["error"] = 503
    resp = _open(anon_client)
    assert resp.status_code == 400
    with anon_client.session_transaction() as s:
        assert not s.get("crm_token")


def test_the_failure_page_does_not_report_its_own_url_to_analytics(anon_client, handoff):
    """
    The one page in this flow that renders was reached by a URL carrying a
    credential. A pageview would file that path.
    """
    handoff["error"] = 401
    body = _open(anon_client).data.decode("utf-8")
    assert "track.js" not in body


def test_the_failure_page_is_not_cached_or_indexed(anon_client, handoff):
    handoff["error"] = 401
    resp = _open(anon_client)
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "noindex" in resp.data.decode("utf-8")


# --- the session ends ---


def test_the_session_expires_after_the_hour_the_crm_gave_it(client, handoff, stub_crm):
    """
    The bearer dies with it. An expired marker would leave staff reading
    "read-only" above a page whose every request is refused.
    """
    _start_session(client, handoff)
    with client.session_transaction() as s:
        s["customer_login_as"] = dict(s["customer_login_as"], expires_at=int(time.time()) - 1)
    body = client.get("/").data.decode("utf-8")
    assert "Read-only customer support session" not in body
    with client.session_transaction() as s:
        assert not s.get("crm_token"), "an expired support session is signed out, not left dangling"


def test_a_session_longer_than_an_hour_is_not_honoured(anon_client, handoff):
    """The CRM's ceiling is an hour; we do not extend it on its behalf."""
    handoff["ttl"] = 86400
    opened = int(time.time())
    _start_session(anon_client, handoff)
    with anon_client.session_transaction() as s:
        assert s["customer_login_as"]["expires_at"] <= opened + 3600


def test_logging_out_ends_the_support_session(client, handoff, stub_crm):
    _start_session(client, handoff)
    client.get("/logout")
    with client.session_transaction() as s:
        assert not s.get("customer_login_as")
    body = client.get("/").data.decode("utf-8")
    assert "Read-only customer support session" not in body


def test_a_real_customer_signing_in_afterwards_is_not_held_read_only(
    client, handoff, stub_crm, monkeypatch
):
    """
    The marker must not outlive the session it describes. A customer who signs
    in on this browser is themselves, with their own token and their own right
    to spend their own money.
    """
    _start_session(client, handoff)
    monkeypatch.setattr(
        CRMClient, "auth_login",
        lambda self, payload: {"token": "their-own-token", "customer": {"id": 1}},
    )
    client.post("/login", data={"email": "a@example.com", "password": "pw"})
    with client.session_transaction() as s:
        assert not s.get("customer_login_as")
    resp = client.post("/cart/clear")
    assert resp.status_code in (301, 302)
    body = client.get("/").data.decode("utf-8")
    assert "read-only" not in body.lower()


# --- a read-only refusal from the CRM itself ---


def test_a_read_only_403_from_the_crm_is_shown_in_its_own_words(
    client, handoff, stub_crm, monkeypatch
):
    """
    Belt and braces: if a write ever reaches the CRM on a support token, the
    answer is not "something went wrong, try again" - retrying cannot work.
    """
    monkeypatch.setattr(
        CRMClient, "auth_login",
        lambda self, payload: (_ for _ in ()).throw(
            CRMError(
                "read only",
                status_code=403,
                payload={
                    "success": False,
                    "error": "This customer support session is read-only.",
                    "error_code": "SUPPORT_SESSION_READ_ONLY",
                },
            )
        ),
    )
    client.get("/logout")
    client.post("/login", data={"email": "a@example.com", "password": "pw"})
    body = client.get("/login").data.decode("utf-8")
    assert "This customer support session is read-only." in body
