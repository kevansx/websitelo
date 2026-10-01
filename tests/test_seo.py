"""
Search-engine behaviour at the cutover.

This site is replacing lottoexpress.com, so the URLs Google already has indexed
have to keep working and keep their signals. The legacy URLs asserted here are
the real ones, taken from the archived copies of the old site, not invented
examples.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from app import app as flask_app
from conftest import ALL_GAME_CODES
from crm_api import CRMClient, CRMError

# Archived legacy play pages → the game they must land on.
LEGACY_PLAY_URLS = [
    ("/lotteries/American-Powerball", "/play/powerball"),
    ("/lotteries/American-Mega-Millions", "/play/megamillions"),
    ("/lotteries/EuroMillions", "/play/euromillions"),
    ("/lotteries/Eurojackpot", "/play/eurojackpot"),
    ("/lotteries/French-Lotto", "/play/lotto-fr"),
    ("/lotteries/German-Lotto", "/play/lotto-6aus49"),
    ("/lotteries/Irish-Lotto", "/play/lotto-ie"),
    ("/lotteries/Oz-Lotto", "/play/oz-lotto-au"),
    ("/lotteries/Australian-Lotto-645", "/play/sat-lotto-au"),
    ("/lotteries/SuperEnalotto", "/play/superenalotto"),
    # Sub-pages and one-off draws belong to the same game.
    ("/lotteries/EuroMillions/Lucky-5", "/play/euromillions"),
    ("/lotteries/French-Lotto/10-to-win", "/play/lotto-fr"),
    ("/lotteries/Irish-Lotto/Lucky-5", "/play/lotto-ie"),
    ("/lotteries/Oz-Lotto/Lucky-5", "/play/oz-lotto-au"),
    ("/lotteries/EuroMillions-Superdraw", "/play/euromillions"),
    ("/lotteries/Australian-Superdraw", "/play/sat-lotto-au"),
]

LEGACY_RESULTS_URLS = [
    ("/lottery-results/american-powerball-winning-numbers", "/results/powerball"),
    ("/lottery-results/american-mega-millions-winning-numbers", "/results/megamillions"),
    ("/lottery-results/euromillions-winning-numbers", "/results/euromillions"),
    ("/lottery-results/eurojackpot-winning-numbers", "/results/eurojackpot"),
    ("/lottery-results/french-lotto-winning-numbers", "/results/lotto-fr"),
    ("/lottery-results/german-lotto-winning-numbers", "/results/lotto-6aus49"),
    ("/lottery-results/irish-lotto-winning-numbers", "/results/lotto-ie"),
    ("/lottery-results/oz-lotto-winning-numbers", "/results/oz-lotto-au"),
    ("/lottery-results/australian-lotto-645-winning-numbers", "/results/sat-lotto-au"),
    ("/lottery-results/superenalotto-winning-numbers", "/results/superenalotto"),
]

# Games the old site sold that this CRM does not. Their pages were recovered
# from the archive and are served at their own URLs, so both the play and the
# results URL lead to the product's page rather than a generic index. The pages
# themselves are covered by tests/test_retired.py.
LEGACY_RETIRED_URLS = [
    ("/lotteries/Australian-Powerball", "/lotteries/australian-powerball"),
    ("/lotteries/Spanish-Lotto-649-La-Primitiva", "/lotteries/spanish-lotto-649-la-primitiva"),
    ("/lotteries/Syndicate/El-Gordo", "/lotteries/el-gordo"),
    ("/lottery-results/el-gordo-winning-numbers", "/lotteries/el-gordo"),
    ("/lottery-results/spanish-lotto-winning-numbers", "/lotteries/spanish-lotto-649-la-primitiva"),
    ("/lottery-results/australian-powerball-winning-numbers", "/lotteries/australian-powerball"),
]

LEGACY_STATIC_URLS = [
    ("/index.php", "/"),
    ("/about-us", "/about"),
    ("/about-us.php", "/about"),
    ("/contact-us", "/contact"),
    ("/faq.php", "/faq"),
    ("/terms-and-conditions", "/terms"),
    ("/terms-and-conditions.php", "/terms"),
    ("/privacy-policy", "/privacy"),
    ("/privacy-policy-au.php", "/privacy/au"),
    ("/responsible-gaming.php", "/responsible-gaming"),
    ("/safe-play", "/responsible-gaming"),
    ("/identity-verification-info.php", "/identity-verification-info"),
    ("/lottery-results", "/results"),
    ("/lottery-results/", "/results"),
    ("/lottery-results/index.php", "/results"),
    ("/login.php", "/login"),
    ("/register.php", "/register"),
]

# This domain ran two generations of site before the PHP one, and the archive
# has both still indexed at 200: an ASP.NET MVC site with a language prefix, and
# an ISAPI site that served every page from one entry point.
OLDER_GENERATION_URLS = [
    ("/home/faq", "/faq"),
    ("/home/index", "/"),
    ("/Home/TermsAndConditions", "/terms"),
    ("/Home/responsiblegambling", "/responsible-gaming"),
    ("/home/promotions/", "/lotteries/promotions"),
    ("/home/result", "/results"),
    ("/en/home/aboutus/", "/about"),
    ("/en/home/contactus/", "/contact"),
    ("/en/home/selfexclusion/", "/responsible-gaming"),
    ("/en/payment/checkout/", "/cart"),
    ("/fr/home/privacypolicy/", "/privacy"),
    ("/fr/home/howitworks/", "/faq"),
    ("/fr/", "/"),
    ("/pl.dll", "/"),
    ("/main.html", "/"),
    ("/winners.html", "/"),
    ("/promotions/", "/lotteries/promotions"),
    ("/feed/", "/blog/feed/"),
    ("/lottery-results/gordo2023.S052.pdf", "/results"),
]

def _path_of(location: str) -> str:
    return re.sub(r"^https?://[^/]+", "", location or "")


@pytest.mark.parametrize("legacy,target", LEGACY_PLAY_URLS + LEGACY_RESULTS_URLS + LEGACY_RETIRED_URLS)
def test_an_indexed_legacy_game_url_moves_permanently_to_its_new_home(anon_client, stub_crm, legacy, target):
    r = anon_client.get(legacy)
    # 301, not 302: a temporary redirect tells Google to keep the old URL.
    assert r.status_code == 301, f"{legacy} answered {r.status_code}"
    assert _path_of(r.headers.get("Location", "")) == target


@pytest.mark.parametrize("legacy,target", LEGACY_STATIC_URLS)
def test_an_indexed_legacy_page_moves_permanently(anon_client, stub_crm, legacy, target):
    r = anon_client.get(legacy)
    assert r.status_code == 301, f"{legacy} answered {r.status_code}"
    assert _path_of(r.headers.get("Location", "")) == target


@pytest.mark.parametrize("legacy,target", OLDER_GENERATION_URLS)
def test_a_url_from_an_older_site_still_finds_its_page(anon_client, stub_crm, legacy, target):
    """
    Two site generations predate the PHP one and are still indexed. Their URLs
    are recognised in the 404 handler rather than as routes, so this also guards
    that the handler is reached.
    """
    r = anon_client.get(legacy)
    assert r.status_code == 301, f"{legacy} answered {r.status_code}"
    assert _path_of(r.headers.get("Location", "")) == target


@pytest.mark.parametrize(
    "variant",
    [
        "/lotteries/euromillions",
        "/lotteries/EUROMILLIONS",
        "/lotteries/EuroMillions.php",
        "/lotteries/EuroMillions/",
    ],
)
def test_the_old_urls_casing_and_php_suffix_do_not_lose_the_page(anon_client, stub_crm, variant):
    r = anon_client.get(variant)
    assert r.status_code in (301, 308)
    assert _path_of(r.headers.get("Location", "")).rstrip("/") in ("/play/euromillions", variant.rstrip("/"))


def test_a_retired_promotion_goes_to_the_live_promotions(anon_client, stub_crm):
    r = anon_client.get("/promotions/specialoffer3")
    assert r.status_code == 301
    assert _path_of(r.headers.get("Location", "")) == "/lotteries/promotions"


def test_no_legacy_redirect_lands_on_another_redirect(anon_client, full_catalog):
    """A chain wastes the equity a 301 is supposed to pass on."""
    for legacy, target in LEGACY_PLAY_URLS + LEGACY_RESULTS_URLS + LEGACY_STATIC_URLS + LEGACY_RETIRED_URLS:
        r = anon_client.get(target)
        assert r.status_code != 301, f"{legacy} redirects to {target}, which redirects again"


@pytest.mark.parametrize(
    "path",
    ["/home/not-a-real-page", "/en/home/nonsense", "/pl.dll/extra", "/C/O", "/totally-made-up"],
)
def test_the_legacy_map_only_answers_for_urls_it_knows(anon_client, stub_crm, path):
    """
    The map is matched exactly, never by prefix. Redirecting a whole section
    would turn genuine 404s into 301s and hide broken internal links.
    """
    assert anon_client.get(path).status_code == 404


def test_a_game_that_does_not_exist_is_reported_missing_rather_than_broken(anon_client, full_catalog):
    # Used to be a 500 (CRM 404 escaping as a server error) and a 200 empty page:
    # both keep the URL in the index.
    assert anon_client.get("/play/no-such-game").status_code == 404
    assert anon_client.get("/results/no-such-game").status_code == 404


def test_every_page_states_its_own_canonical_url(anon_client, full_catalog):
    brand = dataclasses.replace(flask_app.config["BRAND_CONFIG"], canonical_domain="www.example.com")
    original = flask_app.config["BRAND_CONFIG"]
    flask_app.config["BRAND_CONFIG"] = brand
    try:
        body = anon_client.get("/play/powerball").get_data(as_text=True)
        assert '<link rel="canonical" href="https://www.example.com/play/powerball">' in body
        # Query strings are the same page.
        body = anon_client.get("/results/powerball?month=2026-01").get_data(as_text=True)
        assert '<link rel="canonical" href="https://www.example.com/results/powerball">' in body
    finally:
        flask_app.config["BRAND_CONFIG"] = original


def test_pages_carry_their_own_title_and_description(anon_client, full_catalog):
    home = anon_client.get("/").get_data(as_text=True)
    play = anon_client.get("/play/euromillions").get_data(as_text=True)

    def title(body):
        return re.search(r"<title[^>]*>(.*?)</title>", body, re.S).group(1).strip()

    def description(body):
        m = re.search(r'<meta name="description" content="(.*?)">', body, re.S)
        return m.group(1).strip() if m else ""

    assert title(home) != title(play)
    assert "EuroMillions" in title(play)
    # The description the old EuroMillions page ranked on.
    assert "EuroMillions lottery jackpots are easier to play and win" in description(play)
    assert description(home) and description(home) != description(play)


def test_private_pages_are_kept_out_of_the_index(client, stub_crm):
    for path in ("/cart", "/account", "/orders"):
        body = client.get(path).get_data(as_text=True)
        assert '<meta name="robots" content="noindex, follow">' in body, path


def test_public_pages_are_open_to_the_index(anon_client, full_catalog):
    for path in ("/", "/catalog", "/results", "/play/powerball", "/faq"):
        body = anon_client.get(path).get_data(as_text=True)
        assert '<meta name="robots" content="index, follow">' in body, path


def test_robots_txt_points_at_the_sitemap_and_fences_off_private_areas(anon_client, stub_crm):
    r = anon_client.get("/robots.txt")
    assert r.status_code == 200
    assert r.mimetype == "text/plain"
    body = r.get_data(as_text=True)
    assert "Sitemap: https://" in body and "/sitemap.xml" in body
    for private in ("/account", "/cart", "/admin/", "/api/", "/wallet/"):
        assert f"Disallow: {private}" in body


def test_the_sitemap_lists_every_page_we_want_ranked(anon_client, full_catalog):
    body = anon_client.get("/sitemap.xml").get_data(as_text=True)
    locs = re.findall(r"<loc>(.*?)</loc>", body)
    paths = [_path_of(loc) for loc in locs]

    for code in ALL_GAME_CODES:
        assert f"/play/{code}" in paths
        assert f"/results/{code}" in paths
    assert "/" in paths and "/catalog" in paths and "/results" in paths

    # Absolute URLs on one host, and no URL that merely redirects.
    assert all(loc.startswith("https://") for loc in locs)
    assert len({re.match(r"https://[^/]+", loc).group(0) for loc in locs}) == 1
    for legacy, _ in LEGACY_STATIC_URLS + LEGACY_PLAY_URLS + LEGACY_RESULTS_URLS:
        assert legacy not in paths, f"sitemap lists {legacy}, which redirects"


def test_the_site_links_to_its_own_canonical_urls(anon_client, full_catalog):
    """Internal navigation used to point at the legacy slugs, adding a hop."""
    body = anon_client.get("/").get_data(as_text=True)
    assert 'href="/lotteries/' not in body.replace('href="/lotteries/promotions"', "")
    assert 'href="/lottery-results/' not in body


def test_the_brand_is_described_once_in_structured_data(anon_client, full_catalog):
    body = anon_client.get("/").get_data(as_text=True)
    assert body.count('<script type="application/ld+json">') == 1
    assert '"@type": "Organization"' in body


def test_the_blog_is_part_of_the_site_rather_than_a_hole_in_it(anon_client, full_catalog):
    """
    `/blog/` used to 404 after the cutover, losing the archive's 576 indexed
    URLs. It is now served from recovered content — see tests/test_blog.py for
    the detail; this just guards the cutover-level promise.
    """
    assert anon_client.get("/blog/").status_code == 200
    body = anon_client.get("/sitemap.xml").get_data(as_text=True)
    assert "/blog/" in body


def test_a_shared_link_previews_as_lotto_express(anon_client, stub_crm):
    """
    WhatsApp, Facebook and X build a link's preview from `og:image`. The old
    default was `images/logo.png`, a stock "React Core Boilerplate" banner left
    over from a template, so every shared link showed that.
    """
    body = anon_client.get("/").get_data(as_text=True)

    og = re.search(r'<meta property="og:image" content="([^"]+)"', body).group(1)
    tw = re.search(r'<meta name="twitter:image" content="([^"]+)"', body).group(1)
    assert og.endswith("/static/brands/lottoexpress/images/share-card.png")
    assert tw == og
    assert "images/logo.png" not in body


def test_the_share_card_is_the_shape_previews_are_cut_to(anon_client):
    from io import BytesIO

    from PIL import Image

    r = anon_client.get("/static/brands/lottoexpress/images/share-card.png")
    assert r.status_code == 200
    assert Image.open(BytesIO(r.data)).size == (1200, 630)
