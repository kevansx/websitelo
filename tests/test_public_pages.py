"""
Pre-launch smoke tests for public (anonymous) pages: home, catalog, play,
results, static/legal pages, legacy .php redirects, sitemap, health, and 404.

Includes the regression test for the product-banner countdown: the play page
must serve a `.wl-countdown` span with `data-remaining` (ticked by the global
countdown script in base.html) and must NOT hand `#drawCounterReact` to the
legacy React widget (no data-drawdate), which used to clobber the timer with
"To Be Announced".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from crm_api import CRMClient, CRMError
from crm_cache import CRMCache


def test_health(anon_client):
    resp = anon_client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_home_renders(anon_client, stub_crm):
    resp = anon_client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Countdown infrastructure must be present.
    assert "wl-countdown" in html
    assert "__wlCountdownInit" in html


def test_catalog_renders(anon_client, stub_crm):
    resp = anon_client.get("/catalog")
    assert resp.status_code == 200


def test_play_page_renders_with_products(anon_client, stub_crm):
    resp = anon_client.get("/play/powerball")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "PB_SINGLE" in html or "PowerBall" in html


def test_play_page_exposes_prices_by_currency(anon_client, stub_crm):
    """The picker must receive the CRM's per-currency retail prices. Without them
    it quotes the base-currency amount under the customer's currency symbol,
    under-quoting the price the cart then charges from the CRM quote."""
    product = dict(stub_crm["store_game"]["game"]["products"][0])
    product["prices_by_currency"] = {
        "USD": {"amount_cents": 250, "is_base": True, "is_manual": False},
        "EUR": {"amount_cents": 300, "is_base": False, "is_manual": False},
    }
    stub_crm["store_game"] = {"game": {**stub_crm["store_game"]["game"], "products": [product]}}

    resp = anon_client.get("/play/powerball")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "prices_by_currency" in html
    assert "300" in html


def test_play_page_backfills_prices_from_products_endpoint(anon_client, stub_crm):
    """Some CRM builds omit prices_by_currency from the game payload; the play
    page must backfill it from the store products endpoint so the picker can
    quote the customer-currency price."""
    game_product = dict(stub_crm["store_game"]["game"]["products"][0])
    game_product.pop("prices_by_currency", None)
    stub_crm["store_game"] = {"game": {**stub_crm["store_game"]["game"], "products": [game_product]}}
    stub_crm["store_products"] = {
        "products": [
            {
                **game_product,
                "prices_by_currency": {
                    "USD": {"amount_cents": 250, "is_base": True},
                    "EUR": {"amount_cents": 300, "is_base": False},
                },
            }
        ]
    }

    resp = anon_client.get("/play/powerball")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "prices_by_currency" in html
    assert "300" in html


def test_play_page_countdown_regression(anon_client, stub_crm, monkeypatch):
    # Provide a cached jackpot so the server computes remaining_seconds.
    monkeypatch.setattr(
        CRMCache,
        "get_cached_jackpots",
        lambda self: [
            {
                "game_code": "powerball",
                "currency": "USD",
                "jackpot_total": 100000000,
                "remaining_seconds": 3600,
            }
        ],
    )
    resp = anon_client.get("/play/powerball")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Server-rendered ticking countdown span inside the banner.
    assert 'id="drawCounterReact"' in html
    assert 'class="wl-countdown" data-remaining="3600"' in html
    # The banner container must not carry data-drawdate on the play page:
    # that would make the legacy React widget clobber the span.
    banner_div = html.split('id="drawCounterReact"')[0].rsplit("<div", 1)[1]
    assert "data-drawdate" not in banner_div


def test_play_page_countdown_absent_gracefully(anon_client, stub_crm):
    # No cached jackpot -> banner shows a placeholder, not an error.
    resp = anon_client.get("/play/powerball")
    assert resp.status_code == 200
    assert "Draw Cutoff Timer" in resp.data.decode("utf-8")


def _home_counter(anon_client, monkeypatch, jackpot):
    """
    Render the home page over one cached jackpot and return Powerball's counter.

    Assertions have to be scoped to that one counter: the countdown script in
    base.html carries the string "Results pending" on every page, so searching
    the whole document would pass no matter what the strip renders. Failing the
    jackpots call is what drives the cached jackpot through.
    """

    def fake_request(self, method, path, *args, **kwargs):
        if "store/games" in str(path):
            return {"games": [{"game_code": "powerball", "game_name": "Powerball (US)", "products": []}]}
        raise CRMError("offline")

    monkeypatch.setattr(CRMClient, "_request", fake_request)
    monkeypatch.setattr(CRMCache, "get_cached_jackpots", lambda self: [jackpot])
    # The cache is shared across the session, and a render would otherwise
    # persist this one-game catalogue for every test that runs after it.
    monkeypatch.setattr(CRMCache, "set_state", lambda self, *a, **k: None)
    html = anon_client.get("/").get_data(as_text=True)
    for ticket in html.split('class="lotteryItem')[1:]:
        if "/play/powerball" not in ticket:
            continue
        found = re.search(r'<div class="lottoTicketCounter">(.*?)</div>', ticket, re.S)
        return found.group(1) if found else None
    return None


def test_home_says_results_pending_once_the_draw_cutoff_has_passed(anon_client, stub_crm, monkeypatch):
    # The CRM sends cutoffs with no UTC offset. Parsing one leaves a naive
    # datetime, and comparing that against an aware `now` used to raise, which
    # the caller read as "sales open" -- so a drawn game kept a dead countdown.
    counter = _home_counter(
        anon_client,
        monkeypatch,
        {
            "game_code": "powerball",
            "currency": "USD",
            "jackpot_total": 100000000,
            "cutoff_at_utc": "2020-01-01T00:00:00",
        },
    )
    assert counter is not None, "home page rendered no Powerball ticket"
    assert "Results pending" in counter
    assert "wl-countdown" not in counter


def test_home_says_results_pending_for_a_long_dead_draw(anon_client, stub_crm, monkeypatch):
    # EuroMillions' live shape: a cutoff weeks old and a large negative count.
    counter = _home_counter(
        anon_client,
        monkeypatch,
        {
            "game_code": "powerball",
            "currency": "USD",
            "jackpot_total": 100000000,
            "cutoff_at_utc": "2026-07-31T18:30:00",
            "remaining_seconds": -2860180,
        },
    )
    assert counter is not None
    assert "Results pending" in counter


def test_home_still_counts_down_when_the_cutoff_is_ahead(anon_client, stub_crm, monkeypatch):
    ahead = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    counter = _home_counter(
        anon_client,
        monkeypatch,
        {
            "game_code": "powerball",
            "currency": "USD",
            "jackpot_total": 100000000,
            "cutoff_at_utc": ahead,
        },
    )
    assert counter is not None
    assert "Results pending" not in counter
    remaining = int(re.search(r'data-remaining="(-?\d+)"', counter).group(1))
    assert 3000 < remaining <= 7200


def test_countdown_ticker_leaves_a_finished_timer_alone(anon_client, stub_crm):
    # On finishing, the ticker labels the span and drops `data-remaining`. It
    # only rebuilds its element list every fifth tick, so the retired span is
    # still in hand on the next one; without this guard it was re-read as NaN
    # and the label was overwritten with a dash a second after appearing.
    html = anon_client.get("/").get_data(as_text=True)
    assert 'if (!el.hasAttribute("data-remaining")) return;' in html


def test_results_index_renders(anon_client, stub_crm):
    resp = anon_client.get("/results")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/about",
        "/contact",
        "/faq",
        "/terms",
        "/privacy",
        "/privacy/au",
        "/privacy/world",
        "/responsible-gaming",
        "/identity-verification-info",
        "/login",
        "/forgot-password",
    ],
)
def test_static_and_entry_pages_render(anon_client, stub_crm, path):
    resp = anon_client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_register_page_renders(anon_client, stub_crm):
    resp = anon_client.get("/register")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "legacy, expect_in_location",
    [
        ("/index.php", "/"),
        ("/about-us.php", "/about"),
        ("/faq.php", "/faq"),
        ("/login.php", "/login"),
        ("/terms-and-conditions.php", "/terms"),
        ("/account.php", "/account"),
    ],
)
def test_legacy_php_redirects(anon_client, stub_crm, legacy, expect_in_location):
    resp = anon_client.get(legacy)
    assert resp.status_code in (301, 302, 308), f"{legacy} returned {resp.status_code}"
    assert expect_in_location in resp.headers.get("Location", "")


def test_sitemap_renders(anon_client, stub_crm):
    resp = anon_client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert b"<urlset" in resp.data or b"<?xml" in resp.data


def test_unknown_url_renders_branded_404(anon_client, stub_crm):
    resp = anon_client.get("/definitely-not-a-page")
    assert resp.status_code == 404


def test_tracking_endpoints_accept_posts(anon_client, stub_crm):
    for path in ("/api/track/click", "/api/track/pageview"):
        resp = anon_client.post(path, json={"path": "/", "tid": "t"})
        assert resp.status_code < 500, f"{path} returned {resp.status_code}"
