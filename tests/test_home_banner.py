"""Home banner carousel: built-in slides render, and an offer switched on in the CRM ("home" marketing banner)
appears as a slide with no code change."""
from crm_api import CRMClient


def test_banner_renders_the_built_in_slides(anon_client, stub_crm):
    body = anon_client.get("/").get_data(as_text=True)
    assert 'data-hero-track' in body
    assert "To Enter The Worlds Biggest Jackpots!" in body   # the old home banner, word for word
    # promotions that are no longer offered are not advertised (Spin to Win, VIP cash back)
    assert "Deposit, Spin And Win" not in body
    assert "10% Cash Back For VIPs" not in body
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


def test_banner_shows_what_lottosonline_offers():
    import lo_banners
    ball = lambda lot: "/b.png"
    extras = {"pack_img": "/pack.webp", "homescreen": True, "app_icon": "/icon.png", "max_saving_pct": 20,
              "share_offers": [{"name": "US Powerball", "slug": "us-powerball", "cents": 390, "url": "/syndicates/us-powerball", "ball": "/b.png"}]}
    slides = lo_banners.home_slides([], [], [], logged_in=False, lo_ball=ball, extras=extras)
    titles = [s["title"] for s in slides]
    assert "Open A Gift With Your Order" in titles
    assert "10 Lines Every Draw For €3.90 A Week" in titles
    assert "A Free Saturday Lotto Line" in titles
    assert "Save Up To 20% A Line" in titles
    pack = next(s for s in slides if s["id"] == "gift-packs")
    words = (pack["title"] + " " + pack["text"]).lower()
    assert "random" in words and not any(w in words for w in ("win", "prize", "jackpot", "lucky"))
    # an offer that is switched off has no slide
    none = lo_banners.home_slides([], [], [], logged_in=False, lo_ball=ball, extras={})
    assert not {"gift-packs", "homescreen", "multi-draw"} & {s["id"] for s in none}
