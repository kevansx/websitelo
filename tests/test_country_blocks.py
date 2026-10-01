"""
Country blocking.

Two independent layers: a list the site owns in the environment, and the CRM's
own `block_website` flag on the countries table. Both have to stop a visitor
browsing and stop them registering, and neither may be steerable by the visitor.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app import app as flask_app
from crm_api import CRMClient, CRMError
from crm_cache import CacheConfig, CRMCache
from crm_sync import is_sync_enabled


BLOCKED_TEXT = "not able to provide services in your country"

# The header our edge sets. Anything else on the wire is the caller talking.
TRUSTED = "X-Geo-Country"


@pytest.fixture
def block_malta(monkeypatch):
    monkeypatch.setenv("WEBSITE_BLOCKED_COUNTRIES_ISO2", "MT")


@pytest.fixture
def own_cache(tmp_path):
    """
    A cache belonging to this test alone.

    These tests let a real fetch write a real block list. On the shared session
    cache that would leave Malta blocked for everything that ran afterwards.
    """
    original = flask_app.config["CRM_CACHE"]
    cache = CRMCache(CacheConfig(db_path=str(tmp_path / "cache.sqlite"), brand=original.cfg.brand))
    cache.init_db()
    flask_app.config["CRM_CACHE"] = cache
    try:
        yield cache
    finally:
        flask_app.config["CRM_CACHE"] = original


def test_nothing_is_blocked_by_default(anon_client, stub_crm):
    resp = anon_client.get("/", headers={TRUSTED: "MT"})
    assert resp.status_code == 200


def test_a_country_on_the_env_list_cannot_browse(anon_client, stub_crm, block_malta):
    resp = anon_client.get("/", headers={TRUSTED: "MT"})

    assert resp.status_code == 403
    assert BLOCKED_TEXT in resp.get_data(as_text=True)


def test_the_block_does_not_catch_the_neighbours(anon_client, stub_crm, block_malta):
    assert anon_client.get("/", headers={TRUSTED: "IE"}).status_code == 200


def test_the_env_list_takes_several_countries(anon_client, stub_crm, monkeypatch):
    monkeypatch.setenv("WEBSITE_BLOCKED_COUNTRIES_ISO2", "MT, GB CY")

    for iso2 in ("MT", "GB", "CY"):
        assert anon_client.get("/", headers={TRUSTED: iso2}).status_code == 403, iso2
    assert anon_client.get("/", headers={TRUSTED: "IE"}).status_code == 200


def test_the_env_list_works_even_though_the_crm_allows_the_country(anon_client, stub_crm, block_malta, monkeypatch):
    """The regression that made this list dead config: it used to be read only
    when the country was missing from the cache, and the CRM's table carries
    every country, so the cache always answered and the list never ran."""
    monkeypatch.setattr(CRMCache, "is_country_blocked_for_website", lambda self, iso2: False)

    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 403


def test_the_crm_flag_still_blocks_on_its_own(anon_client, stub_crm, own_cache):
    own_cache.upsert_countries(
        [
            {"iso2": "MT", "name": "Malta", "is_active": False, "soft_block": False, "block_website": True},
            {"iso2": "IE", "name": "Ireland", "is_active": True, "soft_block": False, "block_website": False},
        ]
    )

    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 403
    assert anon_client.get("/", headers={TRUSTED: "IE"}).status_code == 200


def test_a_visitor_cannot_send_their_way_past_the_block(anon_client, stub_crm, block_malta):
    """`CF-IPCountry` and friends are as settable as any other request header.
    While they were checked ahead of the edge's own, a blocked visitor could
    walk straight through by sending one."""
    resp = anon_client.get(
        "/",
        headers={TRUSTED: "MT", "CF-IPCountry": "IE", "CloudFront-Viewer-Country": "IE", "X-Country": "IE"},
    )

    assert resp.status_code == 403


def test_another_cdns_header_is_still_read_when_ours_is_absent(anon_client, stub_crm, block_malta):
    """The fallbacks are what make this work behind a CDN that is not ours; they
    are only untrustworthy when a trusted header exists to contradict them."""
    assert anon_client.get("/", headers={"CF-IPCountry": "MT"}).status_code == 403


def test_the_trusted_header_is_configurable(anon_client, stub_crm, block_malta, monkeypatch):
    monkeypatch.setenv("GEO_COUNTRY_HEADER", "X-Edge-Country")

    resp = anon_client.get("/", headers={"X-Edge-Country": "MT", "CF-IPCountry": "IE"})

    assert resp.status_code == 403


def test_an_unknown_country_is_not_blocked(anon_client, stub_crm, block_malta):
    """Geo is best effort. No country header means no decision, not a lockout."""
    assert anon_client.get("/").status_code == 200


def test_static_files_are_never_gated(anon_client, stub_crm, block_malta):
    """The block page loads a stylesheet, so gating static would leave a blocked
    visitor staring at unstyled markup — and health has to answer for the load
    balancer regardless of where it is probing from."""
    assert anon_client.get("/health", headers={TRUSTED: "MT"}).status_code == 200


def _countries_stub(*, calls=None):
    def fake_request(self, method, path, *args, **kwargs):
        if "/countries" in str(path):
            if calls is not None:
                calls.append(path)
            return {
                "countries": [
                    {"iso2": "MT", "name": "Malta", "is_active": False, "block_website": True},
                    {"iso2": "IE", "name": "Ireland", "is_active": True, "block_website": False},
                ]
            }
        raise CRMError("the rest of the CRM is not this test's business")

    return fake_request


def test_the_crm_block_list_arrives_without_the_sync_switch(anon_client, stub_crm, own_cache, monkeypatch):
    """
    The reason a Malta block set in CRM Admin stopped nobody.

    Fetching the countries table was part of the general background sync, which
    is off unless `CRM_SYNC_ENABLE` is set, so the site never had a list to
    check and answered "not blocked" to everyone. Blocking a country is a
    compliance control and cannot wait on a performance switch.
    """
    assert not is_sync_enabled()
    monkeypatch.setattr(CRMClient, "_request", _countries_stub())

    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 403
    assert anon_client.get("/", headers={TRUSTED: "IE"}).status_code == 200


def test_the_list_is_fetched_once_and_then_served_from_the_cache(anon_client, stub_crm, own_cache, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(CRMClient, "_request", _countries_stub(calls=calls))

    for _ in range(3):
        anon_client.get("/", headers={TRUSTED: "MT"})

    assert len(calls) == 1


def test_the_list_refreshes_behind_the_request_once_there_is_one(anon_client, stub_crm, own_cache, monkeypatch):
    """
    The path a running server actually takes.

    With a list already cached there is something to answer from, so the refresh
    goes into a thread instead of holding the visitor up. It still has to reach
    the CRM from there, and a request-scoped client cannot be used off the
    request — taking one raises, the thread dies, and the list quietly stops
    updating while every page still answers 200.
    """
    own_cache.upsert_countries([{"iso2": "MT", "name": "Malta", "is_active": True, "block_website": False}])
    monkeypatch.setattr(CRMClient, "_request", _countries_stub())

    anon_client.get("/", headers={TRUSTED: "IE"})

    deadline = time.time() + 5.0
    while time.time() < deadline and not own_cache.is_country_blocked_for_website("MT"):
        time.sleep(0.05)

    assert own_cache.is_country_blocked_for_website("MT") is True
    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 403


def test_an_empty_list_is_retried_sooner_than_a_stale_one(anon_client, stub_crm, own_cache, monkeypatch):
    """
    What kept Canada browsing for five minutes after the fix went out.

    The attempt stamp survives a restart, so a run of failures leaves it recent
    while the table is still empty — and the site waves everyone through for the
    rest of the interval holding no list at all. An empty table backs off in
    seconds instead.
    """
    stale_by_a_minute = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    own_cache.set_state("last_countries_attempt_at", stale_by_a_minute)
    monkeypatch.setattr(CRMClient, "_request", _countries_stub())

    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 403


def test_a_stale_list_is_left_alone_until_the_interval_is_up(anon_client, stub_crm, own_cache, monkeypatch):
    """The short retry is only for having nothing. With a list in hand the
    steady-state interval applies, or every visitor would trigger a fetch."""
    own_cache.upsert_countries([{"iso2": "MT", "name": "Malta", "is_active": True, "block_website": False}])
    own_cache.set_state(
        "last_countries_attempt_at",
        (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
    )
    calls: list[str] = []
    monkeypatch.setattr(CRMClient, "_request", _countries_stub(calls=calls))

    assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 200
    assert calls == []


def test_a_crm_outage_does_not_refetch_on_every_request(anon_client, stub_crm, own_cache, monkeypatch):
    """The attempt is stamped before the call, so a failure backs off to the
    same interval as a success rather than retrying on every page view."""
    calls: list[str] = []

    def failing(self, method, path, *args, **kwargs):
        if "/countries" in str(path):
            calls.append(path)
        raise CRMError("offline")

    monkeypatch.setattr(CRMClient, "_request", failing)

    for _ in range(3):
        assert anon_client.get("/", headers={TRUSTED: "MT"}).status_code == 200

    assert len(calls) == 1


def test_the_background_sync_reaches_the_crm_from_its_own_thread(stub_crm, own_cache, monkeypatch):
    """
    `CRM_SYNC_ENABLE=1` was offered as the fix for this and would not have
    worked either. The loop runs on a thread with no application context, and
    everything it does reaches the CRM through a client kept on `g`, so the
    first call raised and the loop died on every pass.
    """
    settled = datetime.now(timezone.utc).isoformat()
    for key in (
        "last_jackpots_fetch_at",
        "last_website_policies_fetch_at",
        "last_product_prices_fetch_at",
        "last_draw_results_fetch_at",
    ):
        own_cache.set_state(key, settled)

    def fake_request(self, method, path, *args, **kwargs):
        if "/countries" in str(path):
            return {"countries": [{"iso2": "MT", "name": "Malta", "is_active": False, "block_website": True}]}
        return {"games": [], "banners": []}

    monkeypatch.setattr(CRMClient, "_request", fake_request)

    flask_app.extensions["crm_sync_once"]()

    assert own_cache.is_country_blocked_for_website("MT") is True


def test_the_admin_console_is_reachable_from_a_blocked_country(anon_client, stub_crm, block_malta):
    """Blocking follows the CRM without anyone confirming it, so a wrong entry
    must not lock the people who can correct it out of the page that does."""
    resp = anon_client.get("/admin/crm-cache", headers={TRUSTED: "MT"})

    assert resp.status_code != 403
    assert BLOCKED_TEXT not in resp.get_data(as_text=True)


def test_registering_from_a_blocked_country_is_refused(anon_client, stub_crm, block_malta):
    """Someone browsing from an allowed country cannot register a blocked one."""
    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "mt@example.com",
            "password": "Passw0rd!",
            "country": "MT",
            "currency": "EUR",
            "accept_terms": "1",
        },
        headers={TRUSTED: "IE"},
    )

    assert resp.status_code == 403
    assert BLOCKED_TEXT in resp.get_data(as_text=True)


# --- The CRM's three website modes ---
#
# Active, Soft Block and Block Website are separate flags, and a country is in
# exactly one of them. Soft Block used to be inferred from `is_active = 0`; it
# has its own flag now and that inference no longer holds.

SOFT_BLOCK_TEXT = "Registration is not available in your country."


@pytest.fixture
def three_modes(own_cache):
    own_cache.upsert_countries(
        [
            {"iso2": "IE", "name": "Ireland", "is_active": True, "soft_block": False, "block_website": False},
            {"iso2": "DE", "name": "Germany", "is_active": True, "soft_block": True, "block_website": False},
            {"iso2": "MT", "name": "Malta", "is_active": False, "soft_block": False, "block_website": True},
        ]
    )
    return own_cache


def test_each_flag_combination_resolves_to_one_mode(three_modes):
    assert three_modes.country_restriction("IE") == "active"
    assert three_modes.country_restriction("DE") == "soft_block"
    assert three_modes.country_restriction("MT") == "block_website"
    assert three_modes.country_restriction("FR") == "unknown"


def test_a_country_with_no_readable_active_flag_is_not_blocked(own_cache):
    """
    An inactive country closes the site, so a flag we cannot find must not read
    as inactive. Otherwise a renamed field in the countries payload takes the
    whole site down for every visitor at once.
    """
    own_cache.upsert_countries([{"iso2": "IE", "name": "Ireland"}])

    assert own_cache.country_restriction("IE") == "unknown"


def test_a_soft_blocked_country_browses_the_site_normally(anon_client, stub_crm, three_modes):
    """Soft Block is a registration rule. Turning it into a door policy would
    lock out the existing customers it exists to keep serving."""
    assert anon_client.get("/", headers={TRUSTED: "DE"}).status_code == 200


def test_a_soft_blocked_country_is_told_at_the_form_that_it_cannot_register(anon_client, stub_crm, three_modes):
    body = anon_client.get("/register", headers={TRUSTED: "DE"}).get_data(as_text=True)

    assert SOFT_BLOCK_TEXT in body
    assert "disabled" in body.split('id="registerSubmit"')[1].split(">")[0]


def test_a_soft_blocked_country_is_still_offered_in_the_dropdown(anon_client, stub_crm, three_modes):
    """It is an active country, so it belongs in the select; only the submit is
    refused. A Block Website country has no business being listed at all."""
    body = anon_client.get("/register", headers={TRUSTED: "IE"}).get_data(as_text=True)
    options = body.split('id="registerCountry"')[1].split("</select>")[0]

    assert 'value="DE"' in options
    assert 'value="MT"' not in options


def test_registering_a_soft_blocked_country_is_refused_without_closing_the_site(
    anon_client, stub_crm, three_modes, monkeypatch
):
    calls: list[dict] = []
    monkeypatch.setattr(CRMClient, "auth_register", lambda self, payload: calls.append(payload))

    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "de@example.com",
            "password": "Passw0rd!",
            "country": "DE",
            "accept_terms": "1",
        },
        headers={TRUSTED: "IE"},
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/register")
    assert not calls, "a soft-blocked registration reached the CRM"


def test_a_soft_block_where_the_visitor_is_refuses_the_registration_too(anon_client, stub_crm, three_modes, monkeypatch):
    """The rule covers both the country they are in and the one they claim."""
    calls: list[dict] = []
    monkeypatch.setattr(CRMClient, "auth_register", lambda self, payload: calls.append(payload))

    resp = anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "de@example.com",
            "password": "Passw0rd!",
            "country": "IE",
            "accept_terms": "1",
        },
        headers={TRUSTED: "DE"},
    )

    assert resp.status_code == 302
    assert not calls


def test_the_crms_own_refusal_decides_where_the_customer_ends_up(anon_client, stub_crm, three_modes, monkeypatch):
    """
    The CRM enforces the same rules and names which one it applied. A soft block
    returns to the form; a website block closes the site.
    """

    def refuse(restriction: str, message: str):
        def fake(self, payload):
            raise CRMError(message, status_code=403, payload={"success": False, "error": message, "restriction": restriction})

        return fake

    form = {
        "title": "Mr",
        "first_name": "Test",
        "last_name": "User",
        "email": "x@example.com",
        "password": "Passw0rd!",
        "country": "IE",
        "accept_terms": "1",
    }

    monkeypatch.setattr(CRMClient, "auth_register", refuse("soft_block", SOFT_BLOCK_TEXT))
    soft = anon_client.post("/register", data=form, headers={TRUSTED: "IE"})
    assert soft.status_code == 302
    assert soft.headers["Location"].endswith("/register")

    monkeypatch.setattr(
        CRMClient, "auth_register", refuse("block_website", "Website access is not available in your country.")
    )
    hard = anon_client.post("/register", data=form, headers={TRUSTED: "IE"})
    assert hard.status_code == 403
    assert BLOCKED_TEXT in hard.get_data(as_text=True)


def test_a_blocked_country_stops_a_signed_in_customer_at_the_door(client, stub_crm, three_modes):
    """Block Website is an entry gate, not an account rule."""
    assert client.get("/", headers={TRUSTED: "MT"}).status_code == 403


def test_the_registration_carries_the_country_even_when_the_form_omitted_it(
    anon_client, stub_crm, three_modes, monkeypatch
):
    """The CRM routes wallet payments on the stored country, so it wants one on
    every registration where a country is known at all."""
    calls: list[dict] = []
    monkeypatch.setattr(
        CRMClient,
        "auth_register",
        lambda self, payload: calls.append(payload) or {"token": "t", "customer": {"id": 1, "email": "x@example.com"}},
    )

    anon_client.post(
        "/register",
        data={
            "title": "Mr",
            "first_name": "Test",
            "last_name": "User",
            "email": "x@example.com",
            "password": "Passw0rd!",
            "accept_terms": "1",
        },
        headers={TRUSTED: "IE"},
    )

    assert calls and calls[0]["country"] == "IE"
