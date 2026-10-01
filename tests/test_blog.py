"""
The blog, after WordPress.

The old `/blog/` was a WordPress install on a host that no longer exists, while
576 archived `/blog/` URLs were still indexed. The content was recovered into
`content/blog` and is served by the app at the same URLs. These tests hold that
promise: the URLs Google has must keep answering, and each page must still carry
the signals it had.
"""

from __future__ import annotations

import re

import pytest

import blog_content
from app import app as flask_app


@pytest.fixture(scope="module")
def catalogue():
    posts = blog_content.blog()
    if not posts.posts:
        pytest.skip("no recovered posts in content/blog")
    return posts


def test_every_recovered_post_answers_at_its_original_url(anon_client, stub_crm, catalogue):
    for post in catalogue.posts:
        r = anon_client.get(post.url)
        assert r.status_code == 200, f"{post.url} answered {r.status_code}"


def test_a_post_still_carries_its_own_title_and_description(anon_client, stub_crm, catalogue):
    """One global title across 115 posts would throw away what they rank for."""
    post = next(p for p in catalogue.posts if p.description)
    body = anon_client.get(post.url).get_data(as_text=True)
    assert f"<title>{post.title}</title>" in body
    assert f'<meta name="description" content="{post.description}">' in body
    assert f'<link rel="canonical" href="https://lottoexpress.com{post.url}">' in body
    assert 'content="article"' in body


def test_a_post_describes_itself_as_an_article(anon_client, stub_crm, catalogue):
    body = anon_client.get(catalogue.posts[0].url).get_data(as_text=True)
    assert '"@type": "BlogPosting"' in body
    assert '"@type": "BreadcrumbList"' in body
    assert '"datePublished"' in body


def test_the_old_marketing_stack_did_not_come_back_with_the_content(anon_client, stub_crm, catalogue):
    """HubSpot, MonsterInsights and the ShortPixel proxy were stripped at harvest."""
    for post in catalogue.posts[:25]:
        body = anon_client.get(post.url).get_data(as_text=True)
        article = body.split('class="leBlogBody"', 1)[-1].split("</article>", 1)[0]
        for junk in ("shortpixel.ai", "hubspot", "hscta.net", "monsterinsights", "<script"):
            assert junk not in article.lower(), f"{post.url} still contains {junk}"


def test_post_images_are_served_from_here_not_from_the_dead_host(anon_client, stub_crm, catalogue):
    for post in catalogue.posts[:25]:
        body = anon_client.get(post.url).get_data(as_text=True)
        for src in re.findall(r'<img[^>]+src="([^"]+)"', body):
            assert "lottoexpress.com/blog" not in src, f"{post.url} points at the old host"


def test_the_blog_links_into_the_shop_without_a_redirect_hop(anon_client, stub_crm, catalogue):
    """The posts' internal links are part of why the product pages rank."""
    hits = 0
    for post in catalogue.posts:
        for href in re.findall(r'href="(/[^"]*)"', post.body_html):
            assert not href.startswith("/lotteries/"), f"{post.url} links to a legacy URL"
            hits += href.startswith("/play/")
    assert hits > 0, "no post links to a product page any more"


def test_the_index_paginates_the_way_wordpress_did(anon_client, stub_crm, catalogue):
    assert anon_client.get("/blog/").status_code == 200
    assert anon_client.get("/blog/page/2/").status_code == 200
    # Page one has one URL, not two.
    r = anon_client.get("/blog/page/1/")
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/")
    # Running off the end used to 404; that would strand an indexed pager URL.
    r = anon_client.get("/blog/page/99/")
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/")


def test_the_bare_blog_url_settles_on_one_form(anon_client, stub_crm, catalogue):
    r = anon_client.get("/blog")
    assert r.status_code == 301
    assert r.headers["Location"].endswith("/blog/")


@pytest.mark.parametrize(
    "url",
    [
        "/blog/category/lottery-news/",
        "/blog/category/winners-story/",
        "/blog/category/jackpot-alert/",
        "/blog/tag/american-powerball/",
        "/blog/tag/euromillions/",
    ],
)
def test_the_archived_category_and_tag_pages_still_exist(anon_client, stub_crm, catalogue, url):
    assert anon_client.get(url).status_code == 200


def test_an_archive_lists_only_its_own_posts(anon_client, stub_crm, catalogue):
    term = catalogue.categories["winners-story"]
    body = anon_client.get(term.url).get_data(as_text=True)
    shown = set(re.findall(r'href="/blog/([a-z0-9\-]+)/"', body))
    member_slugs = {p.slug for p in term.posts}
    assert shown & member_slugs
    stray = shown - member_slugs - {"category", "tag", "page"}
    assert not stray, f"{term.url} lists posts that are not in it: {sorted(stray)[:5]}"


def test_a_term_that_no_longer_exists_goes_to_the_blog(anon_client, stub_crm, catalogue):
    r = anon_client.get("/blog/tag/a-tag-that-never-existed/")
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/")


@pytest.mark.parametrize(
    "url,target",
    [
        ("/blog/23-reasons-to-play-the-lotto-online/q_glossy", "/blog/23-reasons-to-play-the-lotto-online/"),
        ("/blog/23-reasons-to-play-the-lotto-online/ret_img", "/blog/23-reasons-to-play-the-lotto-online/"),
        ("/blog/psychology-playing-lottery-guide/embed/", "/blog/psychology-playing-lottery-guide/"),
        ("/blog/category/lifestyle/ret_img", "/blog/category/lifestyle/"),
        # The same artefacts also got indexed at the top level, where there is
        # no post to walk back to.
        ("/blog/q_glossy/", "/blog/"),
        ("/blog/ret_img/", "/blog/"),
    ],
)
def test_the_junk_paths_the_old_plugins_left_behind_walk_back_to_the_page(anon_client, stub_crm, catalogue, url, target):
    """ShortPixel and oEmbed published these, and Google indexed them at 200."""
    r = anon_client.get(url)
    assert r.status_code == 301
    assert r.headers["Location"].endswith(target)


def test_the_feed_is_a_feed(anon_client, stub_crm, catalogue):
    r = anon_client.get("/blog/feed/")
    assert r.status_code == 200
    assert r.mimetype == "application/rss+xml"
    body = r.get_data(as_text=True)
    assert body.startswith("<?xml")
    assert body.count("<item>") >= 10
    assert "https://lottoexpress.com/blog/" in body


@pytest.mark.parametrize(
    "url",
    ["/blog/wp-json/", "/blog/wp-json/wp/v2/posts/1786", "/blog/xmlrpc.php", "/blog/wp-login.php", "/blog/comments/feed/"],
)
def test_wordpress_itself_is_gone_rather_than_missing(anon_client, stub_crm, catalogue, url):
    assert anon_client.get(url).status_code == 410


def test_a_post_that_never_existed_is_a_404(anon_client, stub_crm, catalogue):
    assert anon_client.get("/blog/not-a-real-post/").status_code == 404


def test_the_images_are_served_at_their_published_paths(anon_client, stub_crm, catalogue):
    post = next((p for p in catalogue.posts if p.hero_image), None)
    assert post is not None
    r = anon_client.get(post.hero_image)
    if r.status_code == 404:
        pytest.skip("images not harvested in this checkout")
    assert r.status_code == 200
    assert "max-age" in r.headers.get("Cache-Control", "")


def test_the_sitemap_carries_the_posts_and_when_they_changed(anon_client, stub_crm, catalogue):
    body = anon_client.get("/sitemap.xml").get_data(as_text=True)
    locs = re.findall(r"<loc>(.*?)</loc>", body)
    paths = {loc.split("lottoexpress.com", 1)[-1] for loc in locs}
    assert "/blog/" in paths
    for post in catalogue.posts[:20]:
        assert post.url in paths, f"{post.url} missing from the sitemap"
    # Posts are dated when they were written, not when the sitemap was built.
    assert len(set(re.findall(r"<lastmod>(.*?)</lastmod>", body))) > 1


def test_the_blog_is_open_to_crawlers(anon_client, stub_crm):
    body = anon_client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /blog" not in body


def test_a_term_name_maps_to_the_slug_wordpress_used():
    # "Winner's Story" was indexed as winners-story, not winner-s-story.
    assert blog_content.slugify("Winner's Story") == "winners-story"
    assert blog_content.slugify("Australia 6/45") == "australia-6-45"
    assert blog_content.slugify("American Mega Millions") == "american-mega-millions"


def test_posts_are_listed_newest_first(catalogue):
    dated = [p for p in catalogue.posts if p.published]
    assert dated == sorted(dated, key=lambda p: p.published, reverse=True)
