"""Test copies (www1.lottosonline.com etc.) stay out of search; a CRM outage is a temporary page, not an error."""
import pytest
import requests

from crm_api import CRMClient, CRMError

WWW = "https://www.lottosonline.com"
WWW1 = "https://www1.lottosonline.com"


@pytest.mark.parametrize("base", [WWW1, "https://staging.lottosonline.com"])
def test_test_copies_are_hidden_from_search(anon_client, stub_crm, base):
    page = anon_client.get("/", base_url=base)
    assert page.headers.get("X-Robots-Tag") == "noindex, nofollow"
    robots = anon_client.get("/robots.txt", base_url=base).get_data(as_text=True)
    assert robots.strip().endswith("Disallow: /")


@pytest.mark.parametrize("base", [WWW, "https://lottosonline-origin.azurewebsites.net"])
def test_the_real_site_stays_indexable(anon_client, stub_crm, base):
    # including when the edge forwards an origin hostname: that must never de-index the site
    page = anon_client.get("/", base_url=base)
    assert "X-Robots-Tag" not in page.headers
    robots = anon_client.get("/robots.txt", base_url=base).get_data(as_text=True)
    assert "Disallow: /cart" in robots and "Disallow: /\n" not in robots


def test_noindex_switch(anon_client, stub_crm, monkeypatch):
    monkeypatch.setenv("WEBSITE_NOINDEX", "1")
    assert anon_client.get("/", base_url=WWW).headers.get("X-Robots-Tag") == "noindex, nofollow"


@pytest.mark.parametrize("failure", [
    requests.ConnectionError("CRM unreachable"),
    CRMError("CRM HTTP 502: bad gateway", status_code=502),
])
def test_play_page_during_a_crm_outage(anon_client, stub_crm, monkeypatch, failure):
    def down(self, *a, **k):
        raise failure
    monkeypatch.setattr(CRMClient, "store_game", down)
    r = anon_client.get("/lottery-tickets/euromillions", base_url=WWW)
    assert r.status_code == 503 and r.headers.get("Retry-After")
    body = r.get_data(as_text=True)
    assert "Ticket sales for EuroMillions are temporarily unavailable" in body
    assert "/winning-lottery-numbers/euromillions" in body


@pytest.mark.parametrize("answer", ["crm_404", "empty", "no_products"])
def test_a_missing_crm_product_never_404s_a_lottery_page(anon_client, stub_crm, monkeypatch, answer):
    # Launch-day case: the brand's product is missing or switched off. The page must stay "temporarily
    # unavailable" (503), never 404, which would tell search engines the ranking page is gone.
    def store_game(self, *a, **k):
        if answer == "crm_404":
            raise CRMError("CRM HTTP 404: not found", status_code=404)
        if answer == "empty":
            return {}
        return {"game": {"game_code": "euromillions", "game_name": "EuroMillions", "products": []}}
    monkeypatch.setattr(CRMClient, "store_game", store_game)
    monkeypatch.setattr(CRMClient, "store_products", lambda self, *a, **k: {"products": []})
    r = anon_client.get("/lottery-tickets/euromillions", base_url=WWW)
    assert r.status_code == 503
    assert "temporarily unavailable" in r.get_data(as_text=True)
