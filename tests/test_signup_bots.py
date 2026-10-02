"""
Keeping scripted sign-ups out without getting in a customer's way.

Bots have been creating accounts with random letters for names. They are noise
in the CRM and a distortion in the campaign numbers, so they are worth
stopping - but the reactivation list runs to 325,938 people with a median age
of 71, and a control that turns one of those away costs more than the junk
account it prevented.

So every test here comes in a pair. One proves a script is refused; the other
proves the person the control could plausibly catch by mistake is not. The
second of each pair is the one that matters: a slow reader, a shared address, a
name that an algorithm finds unlikely, somebody with JavaScript switched off.
"""

from __future__ import annotations

import logging
import time

import pytest

from crm_api import CRMClient


FORM = {
    "email": "len.pantlin@gmail.com",
    "password": "Sixpence!9",
    "title": "Mr",
    "first_name": "Len",
    "last_name": "Pantlin",
    "birthdate": "1955-03-02",
    "currency": "GBP",
    "accept_terms": "on",
}


@pytest.fixture
def created(monkeypatch):
    """Records the accounts the CRM was actually asked to create."""
    made: list[dict] = []

    def fake_register(self, payload, *a, **kw):
        made.append(dict(payload))
        return {"token": "test-token", "customer": {"id": 77, "email": payload.get("email")}}

    monkeypatch.setattr(CRMClient, "auth_register", fake_register)
    return made


def _token(client) -> str:
    """The token from a freshly served form, as a browser would have it."""
    body = client.get("/create-account").get_data(as_text=True)
    return body.split('name="form_token" value="')[1].split('"')[0]


# --- posting straight at the endpoint ---


def test_a_script_that_never_loaded_the_form_creates_nothing(bot_client, stub_crm, created):
    """
    The reported attack. A script posts at the endpoint; it does not fetch the
    page first, so it has no token to send and nothing to copy one from.
    """
    done = bot_client.post("/create-account", data=FORM)

    assert created == []
    assert done.status_code == 302


def test_a_browser_that_loaded_the_form_creates_an_account(anon_client, stub_crm, created):
    """The same submission, from something that behaved like a browser."""
    anon_client.post("/create-account", data=FORM)

    assert len(created) == 1
    assert created[0]["email"] == "len.pantlin@gmail.com"


def test_a_made_up_token_is_not_good_enough(bot_client, stub_crm, created):
    bot_client.post("/create-account", data={**FORM, "form_token": "eyJhbGciOi.bW9j.a2Vk"})

    assert created == []


def test_a_token_we_did_not_sign_is_refused(bot_client, stub_crm, created):
    """
    It is the signature doing the work, not the presence of a field. A script
    that fetches the page and then edits the token it found gets nowhere - the
    secret it would need to re-sign it is ours.
    """
    genuine = _token(bot_client)
    forged = genuine[:-6] + ("a" if genuine[-6] != "a" else "b") + genuine[-5:]

    bot_client.post("/create-account", data={**FORM, "form_token": forged})

    assert created == []


def test_submitting_the_same_form_twice_is_not_treated_as_an_attack(
    anon_client, stub_crm, created
):
    """
    Double-clicking Create Account is ordinary, and doubly so at this age. The
    token says when the form was served; it is not a one-shot nonce, because
    invalidating it would turn a slipped finger into a lost registration.
    """
    token = _token(anon_client)
    anon_client.post("/create-account", data={**FORM, "form_token": token})
    anon_client.post("/create-account", data={**FORM, "form_token": token})

    assert len(created) == 2


def test_the_form_needs_no_javascript_to_be_submitted(anon_client, stub_crm):
    """
    The token is a plain hidden input the server renders, not something a
    script writes in on load. A customer on an old browser, or with JavaScript
    switched off, must still be able to register - and on a list with a median
    age of 71 a good few will be.
    """
    body = anon_client.get("/create-account").get_data(as_text=True)
    token_tag = body.split('name="form_token"')[0].rsplit("<input", 1)[1]
    scripts = "".join(chunk.split("</script>")[0] for chunk in body.split("<script")[1:])

    assert 'type="hidden"' in token_tag
    assert "form_token" not in scripts


# --- submitting faster than a person can read ---


def test_a_form_returned_in_milliseconds_is_refused(anon_client, stub_crm, created):
    anon_client.application.config["SIGNUP_MIN_SECONDS"] = 2.0
    try:
        anon_client.post("/create-account", data=FORM)
    finally:
        anon_client.application.config["SIGNUP_MIN_SECONDS"] = 0.0

    assert created == []


def test_somebody_who_took_their_time_is_not_refused(anon_client, stub_crm, created):
    """
    The threshold only has a floor. There is no ceiling a real person can hit:
    someone can open this form, take a phone call, make a cup of tea and come
    back to it, and being slow is not evidence of anything.
    """
    token = _token(anon_client)
    anon_client.application.config["SIGNUP_MIN_SECONDS"] = 0.05
    try:
        time.sleep(0.2)
        anon_client.post("/create-account", data={**FORM, "form_token": token})
    finally:
        anon_client.application.config["SIGNUP_MIN_SECONDS"] = 0.0

    assert len(created) == 1


def test_the_threshold_can_be_loosened_without_a_deploy(anon_client, stub_crm, created):
    """If it ever catches someone real, it can be turned down from config."""
    anon_client.application.config["SIGNUP_MIN_SECONDS"] = 0.0
    anon_client.post("/create-account", data=FORM)

    assert len(created) == 1


# --- the field only a script can see ---


def test_filling_in_the_hidden_field_creates_nothing(anon_client, stub_crm, created):
    anon_client.post("/create-account", data={**FORM, "signup_ref": "http://spam.example"})

    assert created == []


def test_the_hidden_field_is_hidden_from_sight_and_from_screen_readers(anon_client, stub_crm):
    """
    A decoy that a blind customer is offered is not a decoy, it is a trap. It
    is out of the tab order, marked hidden to assistive technology, labelled,
    and told not to autofill.
    """
    body = anon_client.get("/create-account").get_data(as_text=True)
    block = body.split('class="lo-decoy"')[1].split("</div>")[0]

    assert 'aria-hidden="true"' in block.split(">")[0]
    assert 'tabindex="-1"' in block
    assert 'autocomplete="off"' in block
    assert "<label" in block


def test_a_password_manager_would_not_recognise_the_hidden_field(anon_client, stub_crm):
    """
    `website`, `url` and `company` are exactly the names a password manager
    fills in for you, which would make the decoy catch its own customers.
    """
    body = anon_client.get("/create-account").get_data(as_text=True)
    block = body.split('class="lo-decoy"')[1].split("</div>")[0]

    for tempting in ('name="website"', 'name="url"', 'name="company"', 'name="email_confirm"'):
        assert tempting not in block


def test_leaving_the_hidden_field_alone_registers_normally(anon_client, stub_crm, created):
    anon_client.post("/create-account", data={**FORM, "signup_ref": ""})

    assert len(created) == 1


# --- how many accounts one address may create ---


def test_an_address_churning_out_accounts_is_stopped(anon_client, stub_crm, created):
    for n in range(9):
        anon_client.post("/create-account", data={**FORM, "email": f"bot{n}@example.com"})

    # Six an hour, and the rest refused.
    assert len(created) == 6


def test_a_household_or_a_care_home_is_not_stopped(anon_client, stub_crm, created):
    """
    The one control here that can catch real people. A care home, a library and
    anyone behind mobile CGNAT share an address with hundreds of legitimate
    customers, so the ceiling sits well above any plausible household.
    """
    for n in range(4):
        anon_client.post("/create-account", data={**FORM, "email": f"resident{n}@example.com"})

    assert len(created) == 4


def test_being_refused_says_how_to_get_help_rather_than_accusing_them(
    anon_client, stub_crm, created
):
    for n in range(7):
        done = anon_client.post("/create-account", data={**FORM, "email": f"bot{n}@example.com"})

    page = anon_client.get(done.headers["Location"]).get_data(as_text=True)
    told = page.split('lo-flash--error" role="status">')[1].split("</div>")[0].lower()

    assert "contact us" in told
    for accusation in ("bot", "abuse", "suspicious", "blocked", "fraud"):
        assert accusation not in told


def test_a_refusal_names_the_address_so_a_wrong_ceiling_can_be_found(
    anon_client, stub_crm, created, caplog
):
    """
    If this ever fires for an address that is not a script, the limit is wrong
    and someone has to be able to see that it was us who turned them away.
    """
    with caplog.at_level(logging.WARNING):
        for n in range(7):
            anon_client.post("/create-account", data={**FORM, "email": f"bot{n}@example.com"})

    assert "has reached the limit" in caplog.text
    assert "127.0.0.1" in caplog.text


def test_fumbling_the_form_does_not_count_against_them(anon_client, stub_crm, created):
    """
    Counted against accounts created, not forms submitted, so somebody who
    mistypes their password four times has spent none of their allowance.
    """
    for _ in range(8):
        anon_client.post("/create-account", data={**FORM, "password": ""})

    anon_client.post("/create-account", data=FORM)

    assert len(created) == 1


def test_a_broken_counter_leaves_registration_open(anon_client, stub_crm, created, monkeypatch, caplog):
    """
    If the rate limiter cannot be consulted, it must not be the thing that
    closes registration. A broken defence is not a reason to stop trading.
    """
    def broken(self, *a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("crm_cache.CRMCache.count_signup_attempts", broken)

    with caplog.at_level(logging.WARNING):
        anon_client.post("/create-account", data=FORM)

    assert len(created) == 1
    assert "rate limit unavailable" in caplog.text


# --- what the data looks like, for the record only ---


@pytest.mark.parametrize(
    "first,last",
    [
        ("Xkjhgf", "Qwertyu"),
        ("Asdfgh", "Zxcvbn"),
        ("Bbbbbb", "Ccccdd"),
    ],
)
def test_machine_typed_names_are_recorded(anon_client, stub_crm, created, caplog, first, last):
    with caplog.at_level(logging.INFO):
        anon_client.post("/create-account", data={**FORM, "first_name": first, "last_name": last})

    assert "looks machine-typed" in caplog.text


def test_a_machine_typed_name_is_still_allowed_through(anon_client, stub_crm, created):
    """
    Evidence, not enforcement. Every rule anyone writes for this is defeated by
    real names, and a customer turned away because an algorithm disliked their
    surname is a far worse outcome than a junk account in the CRM.
    """
    anon_client.post("/create-account", data={**FORM, "first_name": "Xkjhgf", "last_name": "Qwertyu"})

    assert len(created) == 1


@pytest.mark.parametrize(
    "first,last",
    [
        ("Len", "Pantlin"),
        ("Siobhan", "Ni Bhriain"),
        ("Jean-Luc", "Le Guen"),
        ("Bo", "Ng"),
        ("Aleksandra", "Wojciechowska"),
        ("Ann", "Lee"),
        ("Mary", "O'Rourke"),
        ("Grzegorz", "Brzeczyszczykiewicz"),
    ],
)
def test_real_names_are_not_called_machine_typed(anon_client, stub_crm, created, caplog, first, last):
    """
    Short names, repeated letters, apostrophes, hyphens, and consonant runs
    that look implausible to an English eye and are somebody's actual surname.
    """
    with caplog.at_level(logging.INFO):
        anon_client.post("/create-account", data={**FORM, "first_name": first, "last_name": last})

    assert "looks machine-typed" not in caplog.text
    assert len(created) == 1


# --- the captcha that was never a captcha ---


def test_turning_on_the_legacy_recaptcha_says_it_protects_nothing(
    anon_client, stub_crm, monkeypatch, caplog
):
    """
    The widget's answer is never sent to Google to be checked, so switching it
    on adds a hurdle for a 71-year-old and stops nobody who posts at the
    endpoint. Nobody should discover that from a spreadsheet of junk accounts.
    """
    monkeypatch.setenv("RECAPTCHA_ENABLE", "1")

    with caplog.at_level(logging.WARNING):
        anon_client.get("/create-account")

    assert "decorative" in caplog.text


def test_the_real_controls_do_not_depend_on_that_flag(bot_client, stub_crm, created, monkeypatch):
    monkeypatch.setenv("RECAPTCHA_ENABLE", "0")

    bot_client.post("/create-account", data=FORM)

    assert created == []
