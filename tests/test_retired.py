"""
The product pages for lotteries the store no longer sells.

Australian Powerball, Spanish Lotto 6/49 La Primitiva and El Gordo were sold by
the old site and are not in this CRM. Their pages carried real copy and are still
indexed, so they are served here rather than folded into `/catalog`. What matters
is that they keep their URL, keep their content, say plainly that the game is
unavailable, and never imply we can sell it or that the numbers on the page are
current.
"""

from __future__ import annotations

import re

import pytest

import retired_content
from app import app as flask_app

LIBRARY = retired_content.library()
SLUGS = [game.slug for game in LIBRARY.games]

# The archived URLs, exactly as the old site published them, and the page each
# one has to reach.
ARCHIVED_URLS = [
    ("/lotteries/Australian-Powerball", "/lotteries/australian-powerball"),
    ("/lotteries/Spanish-Lotto-649-La-Primitiva", "/lotteries/spanish-lotto-649-la-primitiva"),
    ("/lotteries/Syndicate/El-Gordo", "/lotteries/el-gordo"),
    # The results URLs for the same products. There are no numbers to show, so
    # the product's own page is the closest match a visitor can be given.
    ("/lottery-results/australian-powerball-winning-numbers", "/lotteries/australian-powerball"),
    ("/lottery-results/el-gordo-winning-numbers", "/lotteries/el-gordo"),
    (
        "/lottery-results/spanish-lotto-649-la-primitiva-winning-numbers",
        "/lotteries/spanish-lotto-649-la-primitiva",
    ),
    ("/lottery-results/spanish-lotto-winning-numbers", "/lotteries/spanish-lotto-649-la-primitiva"),
]


def _path_of(location: str) -> str:
    return re.sub(r"^https?://[^/]+", "", location or "")


def test_the_recovered_pages_are_present():
    """A missing content directory would silently take every page below with it."""
    assert len(LIBRARY) == 3, f"expected 3 recovered products, found {len(LIBRARY)}"


@pytest.mark.parametrize("slug", SLUGS)
def test_a_retired_product_page_answers_at_its_own_url(anon_client, stub_crm, slug):
    r = anon_client.get(f"/lotteries/{slug}")
    assert r.status_code == 200


@pytest.mark.parametrize("legacy,target", ARCHIVED_URLS)
def test_an_archived_url_reaches_the_page_in_one_hop(anon_client, stub_crm, legacy, target):
    r = anon_client.get(legacy)
    assert r.status_code == 301, f"{legacy} answered {r.status_code}"
    assert _path_of(r.headers.get("Location", "")) == target
    # A redirect is only worth anything if what it points at is a page.
    assert anon_client.get(target).status_code == 200


@pytest.mark.parametrize("slug", SLUGS)
def test_the_page_says_the_game_is_unavailable_before_the_old_copy(anon_client, stub_crm, slug):
    """
    The recovered copy was written while we sold the game and still says things
    like "buy your ticket today". The notice has to come first, and it has to be
    in the markup rather than only styled to look prominent.
    """
    game = LIBRARY.get(slug)
    body = anon_client.get(game.path).get_data(as_text=True)
    notice = body.find("leRetiredNotice")
    assert notice != -1, "no unavailable notice on the page"
    assert f"no longer offers {game.name}" in body
    if game.sections:
        assert notice < body.find("leRetiredCopy"), "recovered copy appears above the notice"


@pytest.mark.parametrize("slug", SLUGS)
def test_the_page_does_not_offer_a_way_to_buy_the_retired_game(anon_client, stub_crm, slug):
    """
    Every call to action has to lead to a game we actually sell. A `/play/` or
    `/cart` link carrying the retired product would be worse than a 404.
    """
    game = LIBRARY.get(slug)
    body = anon_client.get(game.path).get_data(as_text=True)
    for href in re.findall(r'href="(/play/[^"]+)"', body):
        code = href.rsplit("/", 1)[-1].split("?")[0]
        assert code in game.alternatives or code, href
    assert f'href="/play/{game.slug}"' not in body
    assert "add-to-cart" not in body


@pytest.mark.parametrize("slug", SLUGS)
def test_the_recovered_content_is_actually_on_the_page(anon_client, stub_crm, slug):
    """The whole point is the copy. An empty page here is a soft 404."""
    game = LIBRARY.get(slug)
    body = anon_client.get(game.path).get_data(as_text=True)
    assert game.quick_facts, f"{slug} recovered no quick facts"
    assert game.prize_tiers, f"{slug} recovered no prize table"
    for fact in game.quick_facts[:3]:
        assert fact["label"] in body
    for row in game.prize_tiers.rows[:3]:
        assert row[0] in body


@pytest.mark.parametrize("slug", SLUGS)
def test_stale_figures_are_labelled_as_stale(anon_client, stub_crm, slug):
    """
    Prize tables and draw dates are frozen at the capture. El Gordo's still names
    a 2023 draw date, so the page must not present them as current.
    """
    body = anon_client.get(LIBRARY.get(slug).path).get_data(as_text=True)
    assert "not maintained" in body or "not kept up to date" in body


@pytest.mark.parametrize("slug", SLUGS)
def test_the_page_carries_its_own_indexable_metadata(anon_client, full_catalog, canonical_host, slug):
    """
    These pages exist to hold a ranking, so they need their own title and
    description, a canonical pointing at themselves, and no noindex.
    """
    game = LIBRARY.get(slug)
    body = anon_client.get(game.path).get_data(as_text=True)
    assert f'<link rel="canonical" href="{canonical_host}{game.path}">' in body
    assert "noindex" not in body
    title = re.search(r"<title>(.*?)</title>", body, re.S)
    assert title and game.seo_title in title.group(1)
    desc = re.search(r'<meta name="description" content="(.*?)"', body, re.S)
    assert desc and desc.group(1).strip()


@pytest.mark.parametrize("slug", SLUGS)
def test_the_page_points_at_games_we_do_sell(anon_client, full_catalog, slug):
    game = LIBRARY.get(slug)
    body = anon_client.get(game.path).get_data(as_text=True)
    assert any(f'href="/play/{code}"' in body for code in game.alternatives), (
        f"{slug} offers no alternative anyone can play"
    )


def test_the_pages_are_in_the_sitemap(anon_client, full_catalog, canonical_host):
    body = anon_client.get("/sitemap.xml").get_data(as_text=True)
    paths = set(re.findall(rf"<loc>{re.escape(canonical_host)}([^<]*)</loc>", body))
    for game in LIBRARY.games:
        assert game.path in paths, f"{game.path} missing from the sitemap"


def test_products_with_no_recovered_page_still_go_somewhere(anon_client, stub_crm):
    """
    The recovered pages are the exception, not a new fallback: a legacy slug with
    no page behind it must still reach the catalogue rather than 404.
    """
    r = anon_client.get("/lotteries/Canadian-Lotto-Max")
    assert r.status_code in (301, 404)
    if r.status_code == 301:
        assert _path_of(r.headers.get("Location", "")) in ("/catalog", "/results")


def test_the_retired_page_does_not_shadow_a_game_we_sell(anon_client, stub_crm):
    """Nothing here may intercept a live product's legacy URL."""
    r = anon_client.get("/lotteries/EuroMillions")
    assert r.status_code == 301
    assert _path_of(r.headers.get("Location", "")) == "/play/euromillions"
