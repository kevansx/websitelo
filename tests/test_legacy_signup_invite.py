"""
Mail-order customers being invited onto the website.

These people bought lottery tickets by post, some of them for fifteen years.
They are in the AS400 and nowhere else, the CRM holds what is known about them,
and their invite link - `/register?lst=<token>` - is the only thing tying the
form they are about to meet to the record that already exists.

Three things separate this from an ordinary sign-up:

The email is not theirs to type. The CRM issued the invite against an address
it has already verified, and that address is the identity being claimed. A form
that let it be edited would let one person claim another's fifteen years.

The token is a lookup key for a name and a date of birth, so it is treated like
`spt` and `rt`: captured on arrival, kept out of `mkt`, never logged, never
sent to analytics.

A third of these records - 34,521 of them - have no date of birth at all. The
CRM only refuses under-18s when it is given a date to judge, so on this path
the form is the only age check there is before KYC.

And underneath all of it: a dead invite must never be a dead end. Someone in
their seventies who followed a link from an envelope must still end up with an
account, even when the token has expired, the CRM is down, or the claim is
refused for a reason nobody anticipated.
"""

from __future__ import annotations

import logging

import pytest

from crm_api import CRMClient, CRMError


TOKEN = "lst_7f3a91c4e08b2d6a5419fe73cc82b10d"
SPT = "spt_5c8e21b7a94f03d6e7182bc45a90ff31"

# What the CRM holds for this customer. The address is the part that matters:
# it is verified, and it is the identity the invite was issued against.
INVITE = {
    "success": True,
    "prefill": {
        "email": "d.hollingsworth@btinternet.com",
        "first_name": "Doris",
        "last_name": "Hollingsworth",
        "birthdate": "1948-03-22",
        "country": "GB",
        "phone": "+441514960123",
    },
}

# What the invited form posts. No password: the claim does not take one, so
# the box is not shown and they choose it on the set-password page instead.
FORM = {
    "email": "d.hollingsworth@btinternet.com",
    "title": "Mrs",
    "first_name": "Doris",
    "last_name": "Hollingsworth",
    "birthdate": "1948-03-22",
    "phone": "+441514960123",
    "country": "GB",
    "currency": "GBP",
    "accept_terms": "on",
}


@pytest.fixture
def invite(monkeypatch, stub_crm):
    """
    The CRM's two invite endpoints, and a record of what we sent them.

    Defaults to a live invite that claims cleanly. Tests set `state["check"]`
    or `state["claim"]` to a `CRMError`, or to a different body, to get each
    way it can go wrong.
    """
    state: dict = {
        "check": dict(INVITE),
        "claim": {"success": True, "next": "set_password", "spt": SPT,
                  "customer": {"id": 8812, "customer_number": "A0041288"}},
        "check_calls": [],
        "claim_calls": [],
        "register_calls": [],
    }

    def fake_check(self, token):
        state["check_calls"].append(token)
        if isinstance(state["check"], BaseException):
            raise state["check"]
        return state["check"]

    def fake_claim(self, payload):
        state["claim_calls"].append(payload)
        if isinstance(state["claim"], BaseException):
            raise state["claim"]
        return state["claim"]

    def fake_register(self, payload):
        state["register_calls"].append(payload)
        return {"token": "ordinary-bearer", "customer": {"id": 1}}

    monkeypatch.setattr(CRMClient, "auth_legacy_signup_check", fake_check)
    monkeypatch.setattr(CRMClient, "auth_legacy_signup_claim", fake_claim)
    monkeypatch.setattr(CRMClient, "auth_register", fake_register)
    return state


@pytest.fixture
def countries(stub_crm):
    """The country list the register form really reads: the SQLite cache."""
    from app import app as flask_app

    cache = flask_app.config["CRM_CACHE"]
    cache.upsert_countries(
        [
            {"iso2": "GB", "name": "United Kingdom", "is_active": 1, "active": 1},
            {"iso2": "US", "name": "United States", "is_active": 1, "active": 1},
        ]
    )
    return cache


def _arrive(client, token=TOKEN):
    """Follow the link from the envelope."""
    return client.get(f"/register?lst={token}")


def _sign_up(client, **overrides):
    data = {**FORM, **overrides}
    return client.post("/register", data=data)


# --- the token ---


def test_the_invite_token_is_remembered_from_the_link(anon_client, invite):
    _arrive(anon_client)
    with anon_client.session_transaction() as s:
        assert s["legacy_signup_token"] == TOKEN


def test_it_survives_a_look_around_the_site_first(anon_client, invite, stub_crm):
    """
    Captured on the way in rather than at the form, so somebody can read about
    the games for ten minutes and still be recognised when they get there.
    """
    _arrive(anon_client)
    anon_client.get("/")
    anon_client.get("/lotteries")
    body = anon_client.get("/register").data.decode("utf-8")
    assert "Doris" in body


def test_it_is_not_swept_into_marketing_attribution(anon_client, invite):
    """
    `mkt` goes out in marketing events. A lookup key for somebody's date of
    birth has no business travelling with attribution.
    """
    _arrive(anon_client)
    with anon_client.session_transaction() as s:
        assert TOKEN not in str(s.get("mkt") or {})


def test_arriving_with_an_invite_is_never_written_to_the_log(
    anon_client, invite, caplog
):
    with caplog.at_level(logging.DEBUG):
        _arrive(anon_client)
    assert TOKEN not in caplog.text


def test_claiming_an_invite_is_never_written_to_the_log(client, invite, caplog):
    with caplog.at_level(logging.DEBUG):
        _arrive(client)
        _sign_up(client)
    assert TOKEN not in caplog.text
    assert SPT not in caplog.text


def test_a_token_that_is_not_shaped_like_one_is_ignored(anon_client, invite):
    """A bound on what gets into the session, not a guess at the format."""
    _arrive(anon_client, token="short")
    with anon_client.session_transaction() as s:
        assert not s.get("legacy_signup_token")
    assert not invite["check_calls"]


def test_the_invite_page_stays_out_of_search_results_and_referrers(anon_client, invite):
    """
    The token is in the URL, so the browser would otherwise hand it to every
    asset host in the `Referer` and leave the page in the back button.
    """
    resp = _arrive(anon_client)
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert resp.headers.get("Cache-Control") == "no-store"
    assert "noindex" in resp.data.decode("utf-8")


# --- what they see ---


def test_the_form_arrives_with_their_details_already_in_it(anon_client, invite):
    body = _arrive(anon_client).data.decode("utf-8")
    assert 'value="Doris"' in body
    assert 'value="Hollingsworth"' in body
    assert 'value="1948-03-22"' in body
    assert 'value="+441514960123"' in body


def test_the_country_the_crm_holds_is_the_one_selected(anon_client, invite, countries):
    """
    What the record says, not where they happen to be browsing from. They can
    still change it; losing it silently is the failure.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    picked = body.split('<option value="GB"')[1].split(">")[0]
    assert "selected" in picked


def test_the_country_survives_even_on_the_fallback_country_list(anon_client, invite):
    """
    The cache is cold on a fresh deploy and the form falls back to a short
    hard-coded list. An invited customer's country has to survive that too.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    picked = body.split('<option value="GB"')[1].split(">")[0]
    assert "selected" in picked


def test_it_says_what_it_has_done_before_showing_them_a_page_of_boxes(
    anon_client, invite
):
    body = _arrive(anon_client).data.decode("utf-8")
    assert "Welcome back" in body
    assert "we've filled in what we already hold" in body


def test_the_email_is_shown_but_cannot_be_edited(anon_client, invite):
    """
    It is the identity the invite was issued against and the CRM has verified
    it. Editable, it becomes a way to point somebody else's history at an
    address of your choosing.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    email_input = body.split('id="registerEmail"')[0].rsplit("<input", 1)[1] + body.split(
        'id="registerEmail"'
    )[1].split(">")[0]
    assert "d.hollingsworth@btinternet.com" in body
    assert "readonly" in email_input


def test_it_says_how_to_change_the_email_rather_than_just_refusing(anon_client, invite):
    """A locked box with no explanation is where an older customer gives up."""
    body = _arrive(anon_client).data.decode("utf-8")
    assert "This is the email address we have for you" in body


def test_they_are_not_asked_for_a_password_they_would_have_to_type_again(
    anon_client, invite
):
    """
    The claim does not take a password; the CRM answers it with a set-password
    token. A box here would be typed into, thrown away, and then asked for
    again on the next page - three entries for one password.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    assert 'name="password"' not in body
    assert "You'll choose your password on the next step." in body


def test_an_ordinary_sign_up_still_has_its_password_box(anon_client, invite, stub_crm):
    body = anon_client.get("/register").data.decode("utf-8")
    assert 'name="password"' in body


def test_a_uk_record_is_not_offered_a_euro_account(anon_client, invite):
    """
    Only three currencies exist here, and the CRM knows where this customer
    lives. Defaulting a Liverpool address to euros is a wrong answer we had
    the information to avoid.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    picked = body.split('<option value="GBP"')[1].split(">")[0]
    assert "selected" in picked


def test_a_currency_the_crm_states_outright_wins(anon_client, invite):
    """If the check ever starts naming one, it knows better than the mapping."""
    invite["check"] = {"success": True, "prefill": {**INVITE["prefill"], "currency": "USD"}}
    body = _arrive(anon_client).data.decode("utf-8")
    picked = body.split('<option value="USD"')[1].split(">")[0]
    assert "selected" in picked


def test_the_currency_is_still_theirs_to_change(client, invite):
    _arrive(client)
    _sign_up(client, currency="EUR")
    assert invite["claim_calls"][0]["currency"] == "EUR"


def test_the_marketing_box_is_not_ticked_for_them(anon_client, invite):
    """Consent is theirs to give. An invite is not consent."""
    body = _arrive(anon_client).data.decode("utf-8")
    optin = body.split('name="marketing_opt_in"')[0].rsplit("<input", 1)[1]
    assert "checked" not in optin


def test_the_date_of_birth_is_required_on_this_path(anon_client, invite):
    """
    34,521 of these records have no date of birth, and the CRM only judges age
    when it is given one.
    """
    body = _arrive(anon_client).data.decode("utf-8")
    dob = body.split('id="leRegisterDobDropdowns"')[1].split("</div>")[0]
    assert dob.count("required") == 3


def test_an_ordinary_sign_up_is_left_exactly_as_it_was(anon_client, invite, stub_crm):
    """The constraint that matters most: nobody without an invite notices."""
    body = anon_client.get("/register").data.decode("utf-8")
    assert "Welcome back" not in body
    assert "readonly" not in body.split('id="registerEmail"')[1].split(">")[0]
    dob = body.split('id="leRegisterDobDropdowns"')[1].split("</div>")[0]
    assert "required" not in dob
    assert not invite["check_calls"]


# --- an invite that will not open ---


@pytest.mark.parametrize(
    "outcome",
    [
        {"success": False, "reason": "expired"},
        {"success": False, "reason": "claimed"},
        {"success": False, "reason": "unknown"},
        CRMError("not found", status_code=404, payload={"success": False}),
        CRMError("bad request", status_code=400, payload={"success": False}),
    ],
)
def test_a_dead_invite_still_lets_them_sign_up(anon_client, invite, outcome):
    invite["check"] = outcome
    resp = _arrive(anon_client)
    body = resp.data.decode("utf-8")
    assert resp.status_code == 200
    assert "That invite link has expired. You can still sign up below." in body
    assert "leRegisterForm" in body, "the ordinary form is still there"


def test_a_dead_invite_is_still_a_page_reached_by_a_token(anon_client, invite):
    """
    Forgetting the token does not unsend the URL. The address it arrived on is
    still in the address bar and would still go out in the `Referer` of every
    asset this page loads.
    """
    invite["check"] = {"success": False, "reason": "expired"}
    resp = _arrive(anon_client)
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert resp.headers.get("Cache-Control") == "no-store"
    assert "noindex" in resp.data.decode("utf-8")


def test_a_dead_invite_is_forgotten_so_the_next_step_does_not_try_to_claim_it(
    anon_client, invite
):
    invite["check"] = {"success": False, "reason": "claimed"}
    _arrive(anon_client)
    with anon_client.session_transaction() as s:
        assert not s.get("legacy_signup_token")


def test_a_dead_invite_never_says_whether_the_address_is_known(anon_client, invite):
    """
    The CRM endpoint answers about a token and never about an address, so that
    a list of emails cannot be tested against it. A message here naming the
    reason would hand back exactly what the endpoint withholds.
    """
    invite["check"] = {"success": False, "reason": "claimed"}
    body = _arrive(anon_client).data.decode("utf-8").lower()
    for leak in ("already", "claimed", "registered", "exists", "account was"):
        assert leak not in body.split("still sign up below")[0][-400:], leak


def test_a_crm_that_is_down_is_not_a_reason_to_stop_someone_registering(
    anon_client, invite
):
    invite["check"] = CRMError("gateway timeout", status_code=504)
    resp = _arrive(anon_client)
    assert resp.status_code == 200
    assert "leRegisterForm" in resp.data.decode("utf-8")


def test_an_answer_without_a_verified_address_is_treated_as_a_dead_invite(
    anon_client, invite
):
    """
    Without the address there is no identity to claim against, however
    well-formed the rest of the answer was.
    """
    invite["check"] = {"success": True, "prefill": {"first_name": "Doris"}}
    body = _arrive(anon_client).data.decode("utf-8")
    assert "That invite link has expired" in body
    with anon_client.session_transaction() as s:
        assert not s.get("legacy_signup_token")


# --- claiming it ---


def test_an_invite_is_claimed_rather_than_registered(client, invite):
    _arrive(client)
    _sign_up(client)
    assert len(invite["claim_calls"]) == 1
    assert not invite["register_calls"], "the ordinary register call is not made"


def test_the_claim_carries_the_token_and_the_details_they_confirmed(client, invite):
    _arrive(client)
    _sign_up(client)
    sent = invite["claim_calls"][0]
    assert sent["token"] == TOKEN
    assert sent["first_name"] == "Doris"
    assert sent["last_name"] == "Hollingsworth"
    assert sent["birthdate"] == "1948-03-22"
    assert sent["country"] == "GB"
    assert sent["phone"] == "+441514960123"
    assert sent["currency"] == "GBP"


def test_the_claim_does_not_send_an_email_address_at_all(client, invite):
    """
    The CRM keeps the one it verified. Sending one would make the browser the
    authority on who this account belongs to.
    """
    _arrive(client)
    _sign_up(client)
    assert "email" not in invite["claim_calls"][0]


def test_reopening_the_locked_email_box_cannot_move_the_account(client, invite):
    """
    `readonly` is a courtesy to the person filling the form in, not a control.
    Anyone can reopen it in devtools; the field is simply never sent.
    """
    _arrive(client)
    _sign_up(client, email="attacker@example.com")
    assert "email" not in invite["claim_calls"][0]
    assert "attacker@example.com" not in str(invite["claim_calls"][0])


def test_a_claimed_invite_goes_on_to_choose_a_password(client, invite):
    """
    The account exists but has no password, so the CRM issues a short-lived
    set-password token. It is handed over exactly as an emailed one would be,
    so there is one implementation of choosing a first password.
    """
    _arrive(client)
    resp = _sign_up(client)
    assert resp.status_code in (301, 302)
    assert "/set-password" in resp.headers["Location"]
    with client.session_transaction() as s:
        assert s["set_password_token"] == SPT


def test_the_set_password_page_then_works_for_them(client, invite, stub_crm):
    """The handover has to land, not just point in the right direction."""
    _arrive(client)
    _sign_up(client)
    resp = client.get("/set-password")
    assert resp.status_code == 200


def test_the_invite_is_forgotten_once_it_has_been_claimed(client, invite):
    """Single use. Left in the session it would be claimed again on the next
    form they touch."""
    _arrive(client)
    _sign_up(client)
    with client.session_transaction() as s:
        assert not s.get("legacy_signup_token")


def test_where_they_were_heading_survives_the_claim(client, invite, stub_crm):
    """
    Somebody who followed an invite into an offer is mid-purchase, and the
    set-password page has to carry them back to it.
    """
    _arrive(client)
    resp = _sign_up(client, next="/cart")
    assert "next=%2Fcart" in resp.headers["Location"] or "next=/cart" in resp.headers["Location"]


def test_the_crm_is_told_the_currency_they_chose(client, invite):
    _arrive(client)
    _sign_up(client, currency="USD")
    assert invite["claim_calls"][0]["currency"] == "USD"


# --- no date of birth, which a third of these records have ---


def test_an_invite_without_a_date_of_birth_is_refused_until_one_is_given(
    client, invite
):
    """
    The only age check before KYC. The CRM cannot make it, because it only
    judges a date it has been given.
    """
    invite["check"] = {"success": True, "prefill": {
        "email": "d.hollingsworth@btinternet.com", "first_name": "Doris",
        "last_name": "Hollingsworth"}}
    _arrive(client)
    resp = _sign_up(client, birthdate="")
    assert resp.status_code in (301, 302)
    assert not invite["claim_calls"], "nothing is claimed without a date of birth"


def test_being_asked_for_a_date_of_birth_says_so_plainly(client, invite, stub_crm):
    invite["check"] = {"success": True, "prefill": {
        "email": "d.hollingsworth@btinternet.com"}}
    _arrive(client)
    _sign_up(client, birthdate="")
    body = client.get("/register").data.decode("utf-8")
    assert "date of birth" in body.lower()


def test_an_ordinary_sign_up_without_a_date_of_birth_is_unaffected(
    client, invite, stub_crm
):
    """The requirement is this path's, not the form's."""
    resp = _sign_up(client, birthdate="", password="Str0ng!Pass")
    assert resp.status_code in (301, 302)
    assert len(invite["register_calls"]) == 1
    assert invite["register_calls"][0]["birthdate"] is None


# --- a claim that will not go through ---


def test_a_refused_claim_sends_them_to_the_ordinary_form(client, invite):
    """
    Never a dead end. An invite nobody will honour is our problem, and they
    still came here to open an account - but the invited form never showed a
    password box, so there is nothing to register them with and they have to
    be given the full form.
    """
    invite["claim"] = CRMError(
        "already claimed", status_code=409,
        payload={"success": False, "error": "This invite has already been used."},
    )
    _arrive(client)
    resp = _sign_up(client)
    assert len(invite["claim_calls"]) == 1
    assert not invite["register_calls"], "there was no password to register with"
    assert "/register" in resp.headers["Location"]
    body = client.get("/register").data.decode("utf-8")
    assert 'name="password"' in body, "and now they are asked for one"


def test_a_refused_claim_says_what_the_crm_said_and_what_to_do(client, invite):
    invite["claim"] = CRMError(
        "already claimed", status_code=409,
        payload={"success": False, "error": "This invite has already been used."},
    )
    _arrive(client)
    _sign_up(client)
    body = client.get("/register").data.decode("utf-8")
    assert "This invite has already been used." in body
    assert "Please fill in the form below to create your account." in body


def test_a_refused_claim_still_registers_anyone_who_did_give_a_password(
    client, invite
):
    """
    A cached page from before the password box was removed, or a form posted
    by hand. If we have what registration needs, use it rather than sending
    them round again.
    """
    invite["claim"] = CRMError("boom", status_code=500)
    _arrive(client)
    _sign_up(client, password="Str0ng!Pass")
    assert len(invite["register_calls"]) == 1


def test_a_refused_claim_forgets_the_invite(client, invite):
    invite["claim"] = CRMError("boom", status_code=500)
    _arrive(client)
    _sign_up(client)
    with client.session_transaction() as s:
        assert not s.get("legacy_signup_token")


def test_a_claim_that_returns_no_password_token_is_not_a_dead_end(client, invite):
    """
    A success that cannot be finished is worse than a failure: the account
    exists and they have no way into it. They are put back on a form they can
    complete rather than left on a page that has run out of instructions.
    """
    invite["claim"] = {"success": True, "next": "set_password"}
    _arrive(client)
    resp = _sign_up(client)
    assert "/register" in resp.headers["Location"]
    assert "Please fill in the form below" in client.get("/register").data.decode("utf-8")


def test_a_claim_that_returns_no_password_token_is_logged_loudly(
    client, invite, caplog
):
    """Nobody would notice this from the outside; the customer just registers."""
    invite["claim"] = {"success": True, "next": "set_password"}
    with caplog.at_level(logging.ERROR):
        _arrive(client)
        _sign_up(client)
    assert "set-password token" in caplog.text


@pytest.mark.parametrize("key", ["spt", "set_password_token", "token"])
def test_the_password_token_is_read_under_whichever_name_it_arrives(
    client, invite, key
):
    """
    These endpoints are in no published contract. The last time a field name
    was guessed at here, a payment flow failed live on `hosted_url`.
    """
    invite["claim"] = {"success": True, "next": "set_password", key: SPT}
    _arrive(client)
    _sign_up(client)
    with client.session_transaction() as s:
        assert s["set_password_token"] == SPT


# --- the bot controls are not relaxed for invited customers ---


def test_a_script_posting_straight_at_the_form_claims_nothing(bot_client, invite):
    """
    The invite path is a more attractive target than the ordinary one: it makes
    accounts against addresses the CRM has already verified.
    """
    with bot_client.session_transaction() as s:
        s["legacy_signup_token"] = TOKEN
    bot_client.post("/register", data=FORM)
    assert not invite["claim_calls"]


def test_the_hidden_field_still_turns_an_invite_away(client, invite):
    _arrive(client)
    body = client.get("/register").data.decode("utf-8")
    decoy = body.split('class="signupDecoy"')[1].split('name="')[1].split('"')[0]
    _sign_up(client, **{decoy: "filled in by a script"})
    assert not invite["claim_calls"]
