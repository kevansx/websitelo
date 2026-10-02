"""Home banner carousel: built-in slides render, and an offer switched on in the CRM ("home" marketing banner)
appears as a slide with no code change."""
from crm_api import CRMClient


def test_banner_renders_the_built_in_slides(anon_client, stub_crm):
    body = anon_client.get("/").get_data(as_text=True)
    assert 'data-hero-track' in body
    assert "To Enter The Worlds Biggest Jackpots!" in body   # the old home banner, word for word
    assert "Deposit, Spin And Win" in body
    assert "10% Cash Back For VIPs" in body
    # banner lines are text, not headings: the page keeps its single H1
    assert body.count("<h1") == 1


def test_a_crm_offer_becomes_a_slide(anon_client, stub_crm, monkeypatch):
    real = CRMClient._request

    def fake_request(self, method, path, *a, **k):
        if path.startswith("/api/v1/marketing/banners"):
            return {"success": True, "banners": [{"id": 77, "title": "Double Lines Weekend", "body": "Two lines for the price of one.",
                                                  "cta_label": "Claim it", "cta_href": "/lottery-tickets/euromillions", "priority": 5}]}
        return real(self, method, path, *a, **k)

    monkeypatch.setattr(CRMClient, "_request", fake_request)
    monkeypatch.setenv("CRM_MARKETING_BANNERS_TTL_SECONDS", "0")
    body = anon_client.get("/").get_data(as_text=True)
    assert "Double Lines Weekend" in body
    assert "Two lines for the price of one." in body
    assert 'href="/lottery-tickets/euromillions"' in body
