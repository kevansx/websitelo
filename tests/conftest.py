from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import time

# Ensure required env exists before the app module is imported, and keep the
# background CRM sync disabled inside tests.
os.environ.setdefault("CRM_BASE_URL", "http://crm.invalid")
os.environ.setdefault("CRM_API_SERVICE_KEY", "test-service-key")
os.environ["CRM_SYNC_ENABLE"] = "0"
# Tests default to the spec behavior (hide the tab when the customer has no
# legacy orders); the verification override is exercised by dedicated tests.
os.environ["LEGACY_ORDERS_SHOW_EMPTY"] = "0"
# Isolate the CRM cache: never read the developer's synced ./data cache in tests.
os.environ["CRM_CACHE_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="lx-test-cache-"), "crm_cache.sqlite")
# Tests must not inherit a processor override from the developer's .env
# (load_dotenv doesn't overwrite pre-set env vars).
os.environ["WALLET_TOPUP_PROCESSOR"] = ""
# A test fills the sign-up form in faster than any person could. The real
# threshold is exercised deliberately in tests/test_signup_bots.py.
os.environ["SIGNUP_MIN_SECONDS"] = "0"

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
from flask.testing import FlaskClient

from app import app as flask_app
from crm_api import CRMClient, CRMError
from mkt_api import MktClient

# The ten games this CRM actually sells, confirmed against /store/games.
ALL_GAME_CODES = [
    "powerball",
    "megamillions",
    "euromillions",
    "eurojackpot",
    "lotto-fr",
    "lotto-6aus49",
    "lotto-ie",
    "oz-lotto-au",
    "sat-lotto-au",
    "superenalotto",
]

TEST_GAME = {
    "game_code": "powerball",
    "game_name": "PowerBall",
    "products": [
        {
            "code": "PB_SINGLE",
            "product_code": "PB_SINGLE",
            "game_code": "powerball",
            "product_type": "single",
            "price_in_base_cents": 500,
            "base_currency": "USD",
            "line_schema": {"main": {"count": 5, "min": 1, "max": 69}, "power": {"count": 1, "min": 1, "max": 26}},
            "addons": [],
        }
    ],
}

TEST_CUSTOMER = {
    "id": 1,
    "email": "test@example.com",
    "first_name": "Test",
    "last_name": "User",
    "email_verified": True,
    "currency": "USD",
    # Registration collects a country and the CRM routes payments on it, so a
    # customer without one is the exception rather than the default.
    "country": "US",
    # Likewise an address: some processors will not open a payment page without
    # one, so a customer who has none is asked before the intent is created.
    # That is the exception, and the tests that care about it say so.
    "street": "1 Main St",
    "city": "Springfield",
    "postal_code": "12345",
}


class BrowserClient(FlaskClient):
    """
    A client that registers the way a browser does.

    The sign-up form carries a token proving the page was served to whoever is
    posting it, so a client that posts straight at `/register` is refused -
    which is the point, because that is what the sign-up bots do. A browser
    satisfies that by loading the form first, so this does too, rather than
    every test that happens to create an account having to know about it.

    `bot_client` is the same client without this courtesy, for the tests that
    are about the refusal itself.
    """

    def post(self, *args, **kwargs):
        path = str(args[0] if args else kwargs.get("path", ""))
        data = kwargs.get("data")
        if path.rstrip("/").endswith("/register") and isinstance(data, dict) and "form_token" not in data:
            kwargs["data"] = {**data, "form_token": self.signup_form_token()}
        return super().post(*args, **kwargs)

    def signup_form_token(self) -> str:
        body = self.get("/register").get_data(as_text=True)
        marker = 'name="form_token" value="'
        return body.split(marker)[1].split('"')[0] if marker in body else ""


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.test_client_class = BrowserClient
    with flask_app.test_client() as c:
        with c.session_transaction() as s:
            s["crm_token"] = "test-token"
            s["customer"] = dict(TEST_CUSTOMER)
        yield c


@pytest.fixture
def anon_client():
    flask_app.config["TESTING"] = True
    flask_app.test_client_class = BrowserClient
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """
    Nothing here is allowed off the machine.

    The suite already stubs the CRM, but not every path is stubbed and some
    tests exist precisely to drive one that is not - a failed quote, a CRM
    that is down. Those used to cost nothing because `crm.invalid` came back
    as NXDOMAIN instantly, which made the suite silently dependent on the
    developer's DNS: on a machine where lookups hang instead of failing, the
    same tests sit on a 25-second timeout each and a 27-second run becomes an
    hour.

    Refusing at the socket is the same answer those tests were always getting,
    delivered immediately and identically everywhere.
    """
    import requests

    def refuse(self, method, url, *args, **kwargs):
        raise requests.exceptions.ConnectionError(
            f"the test suite does not make real requests ({method} {url})"
        )

    monkeypatch.setattr(requests.Session, "request", refuse)


@pytest.fixture(autouse=True)
def _forget_earlier_signups():
    """
    Every test starts from an address that has created no accounts.

    Sign-up rate limiting is counted in the SQLite cache on purpose, because
    the site runs two gunicorn workers and a limit each worker counts on its
    own is half a limit. That storage outlives an individual test, so without
    this the thirtieth test to register is refused for something the first
    twenty-nine did.
    """
    try:
        flask_app.config["CRM_CACHE"].prune_signup_attempts(before=time.time() + 1)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _forget_earlier_charges():
    """
    Every test starts with intents that have never been charged.

    A charge claims its intent in the shared cache so a second press of Pay
    cannot charge it again. Real intent ids are never reused; these tests all
    call theirs `intent-1`, so without this only the first to charge would.
    """
    try:
        with flask_app.config["CRM_CACHE"]._connect() as conn:
            conn.execute("DELETE FROM sync_state WHERE k LIKE 'lock:topup_charge:%'")
            conn.commit()
    except Exception:
        pass
    yield


@pytest.fixture
def bot_client():
    """A client that posts at the sign-up form without ever loading it."""
    flask_app.config["TESTING"] = True
    flask_app.test_client_class = FlaskClient
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def canonical_host():
    """
    Pin the canonical domain.

    Canonical tags and the sitemap are built on the configured host rather than
    whichever `Host` header the request arrived with, so a test that asserts an
    absolute URL has to know what that host is.
    """
    original = flask_app.config["BRAND_CONFIG"]
    flask_app.config["BRAND_CONFIG"] = dataclasses.replace(original, canonical_domain="www.example.com")
    try:
        yield "https://www.example.com"
    finally:
        flask_app.config["BRAND_CONFIG"] = original


@pytest.fixture
def full_catalog(stub_crm, monkeypatch):
    """
    The CRM's real ten games, so results and sitemap coverage can be checked.

    The catalogue the site reads comes through `_request` on its way into the
    cache rather than through `store_games()`, and an unknown game code answers
    404 the way the CRM does.
    """
    games = [{"game_code": code, "game_name": code, "products": []} for code in ALL_GAME_CODES]

    def fake_request(self, method, path, *args, **kwargs):
        if str(path).endswith("/store/games"):
            return {"games": games}
        raise CRMError(f"unexpected {method} {path}", status_code=404)

    def fake_store_game(self, game_code, *args, **kwargs):
        for game in games:
            if game["game_code"] == str(game_code).strip().lower():
                return {"game": game}
        raise CRMError("CRM HTTP 404: game not found", status_code=404)

    monkeypatch.setattr(CRMClient, "_request", fake_request)
    monkeypatch.setattr(CRMClient, "store_game", fake_store_game)
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": []})
    return games


REACTIVATION_PREFILL = {
    "ok": True,
    "campaign": "01-probe-priority",
    "prefill": {
        "email": "lenp14@hotmail.co.uk",
        "first_name": "Len",
        "last_name": "Pantlin",
        "birthdate": "1969-07-14",
        "currency": "GBP",
        "customer_number": "E9654293",
    },
}


@pytest.fixture
def stub_mkt(monkeypatch):
    """
    The Marketing Module's prefill API, configured and answering.

    Configuring it is the test's job because `get_mkt()` answers None without
    it, which is what lets every other test - and any deployment that is not
    running a reactivation campaign - carry on never having heard of the
    Module. `response` and `error` are what a test reaches for; `prefill_calls`
    and `registered_calls` record what we asked it.
    """
    monkeypatch.setenv("MM_BASE_URL", "http://mkt.invalid")
    monkeypatch.setenv("MM_API_KEY", "test-mm-key")

    class Stub:
        def __init__(self) -> None:
            self.response: object = dict(REACTIVATION_PREFILL)
            self.error: BaseException | None = None
            self.prefill_calls: list[tuple[str, str]] = []
            self.registered_calls: list[tuple[str, str]] = []

    stub = Stub()

    def fake_prefill(self, brand, token):
        stub.prefill_calls.append((brand, token))
        if stub.error is not None:
            raise stub.error
        return stub.response

    def fake_registered(self, brand, token):
        stub.registered_calls.append((brand, token))

    monkeypatch.setattr(MktClient, "prefill", fake_prefill)
    monkeypatch.setattr(MktClient, "prefill_registered", fake_registered)
    return stub


@pytest.fixture
def stub_crm(monkeypatch):
    """
    Stub every public CRMClient method with safe defaults so any page can render
    without network access. Tests can re-patch individual methods on top of this.
    Returns the defaults dict so tests can tweak shared payloads.
    """
    defaults = {
        "health": {"ok": True},
        "countries": {"countries": [{"iso2": "US", "name": "United States", "active": 1}]},
        "store_games": {"games": [TEST_GAME]},
        "store_game": {"game": TEST_GAME},
        "store_products": {"products": TEST_GAME["products"]},
        "bundle": {"bundle": None},
        "auth_register": {"token": "test-token", "customer": TEST_CUSTOMER},
        "auth_login": {"token": "test-token", "customer": TEST_CUSTOMER},
        "auth_me": {"customer": TEST_CUSTOMER},
        "password_reset_request": {"success": True},
        "password_reset_confirm": {"success": True},
        "auth_set_password_check": {"valid": False},
        # No invite, unless a test says otherwise. A default that answered with
        # somebody's details would prefill forms in tests that never mentioned
        # an invite, and hide the ordinary sign-up path from its own tests.
        "auth_legacy_signup_check": {"success": False, "reason": "unknown"},
        "auth_legacy_signup_claim": {"success": False, "error": "no invite"},
        "auth_set_password": {"ok": True, "token": "test-token", "customer_id": 1},
        "auth_email_verification_request": {"success": True},
        "auth_email_verification_confirm": {"success": True},
        "customer_me": {"customer": TEST_CUSTOMER},
        "customer_update": {"customer": TEST_CUSTOMER},
        "wallet": {"wallet": {"currency": "USD", "balance_cents": 10000, "withdrawable_cents": 10000}},
        "wallet_transactions": {"transactions": []},
        "wallet_topup_init": {"mode": "hpp_redirect", "intent_id": "intent-1", "redirect_url": "https://pay.example/hpp"},
        "wallet_topup_status": {"status": "pending"},
        "winnings_tickets": {"tickets": []},
        "wallet_cards": {"cards": []},
        "wallet_cards_add": {"card": {"id": 1}},
        "wallet_cards_delete": None,
        "wallet_topup_charge": {"status": "completed"},
        "wallet_topup_hpp_start": {"mode": "hpp_redirect", "redirect_url": "https://pay.example/hpp"},
        "wallet_topup_emerchant_3ds_method_continue": {"status": "completed"},
        # An emailed payment link, shaped as Bitolo answers: the wallet is
        # credited in the customer's currency and the transfer is made in MXN.
        "wallet_topup_email_link_context": {
            "success": True,
            "intent": {"id": 456, "status": "pending", "processor": "bitolo", "amount_cents": 5000, "currency": "USD"},
            "charge": {"amount_cents": 92500, "currency": "MXN"},
            "payment_requirements": {
                "rfc": {"required": True, "label": "Mexican RFC", "min_length": 12, "max_length": 13},
                "curp": {"required": True, "label": "Mexican CURP", "length": 18},
                "identity_handling": "transient",
            },
        },
        "wallet_topup_email_link_hpp_start": {
            "success": True,
            "intent_id": 456,
            "mode": "bitolo_spei_deposit",
            "status": "pending",
            "redirect_url": "https://mxnpay.example/v1/spei.php?enc=abc",
            "order_id": "pi00000456",
        },
        "wallet_topup_email_link_status": {"success": True, "intent": {"status": "pending"}},
        "orders": {"orders": []},
        "order": {"order": {"id": 1, "status": "completed", "currency": "USD", "total_cents": 500, "tickets": []}},
        "legacy_orders": {"success": True, "page": 1, "per_page": 25, "total": 0, "orders": []},
        "legacy_order": {"success": True, "order": None},
        "checkout_quote": {"quote": {"currency": "USD", "subtotal_cents": 500, "items": []}},
        "checkout": {"order_id": 1, "debited_cents": 500, "currency": "USD"},
        "checkout_submit": {"order_id": 1, "quote_id": 1, "currency": "USD", "total_cents": 500},
        "draw_results": {"draw_results": [], "results": [], "next_cursor": None},
        "marketing_banners": {"banners": []},
        "marketing_events": {"ok": True},
    }

    def make(name):
        def fake(self, *args, **kwargs):
            return defaults[name]

        return fake

    for name in defaults:
        monkeypatch.setattr(CRMClient, name, make(name))
    return defaults
