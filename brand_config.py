from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _canonical_domain_from_env() -> str | None:
    """Read the public production domain used to build absolute payment
    return URLs (must be allowlisted in CRM). Accepts values with or without
    scheme/path, e.g. "https://lottoexpress.com/" -> "lottoexpress.com".
    """
    raw = (os.getenv("WEBSITE_CANONICAL_DOMAIN") or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^https?://", "", raw, flags=re.IGNORECASE).strip()
    raw = raw.strip("/").split("/")[0].strip()
    return raw or None


@dataclass(frozen=True)
class BrandConfig:
    slug: str
    display_name: str
    canonical_domain: str | None

    # Static assets (within /static)
    logo_path: str
    favicon_path: str

    # Analytics (can also be overridden via env)
    gtm_id: str | None = None
    ga4_id: str | None = None

    # Featured lists (used for /results and sitemap)
    featured_results_game_slugs: tuple[str, ...] = ()

    # Legacy slug mappings.
    #
    # Prefer mapping directly to CRM `game_code` / `bundle_slug` when known.
    # If not known yet, map to a human `game_name` and the website will resolve
    # it to a `game_code` by matching against `/api/v1/store/games`.
    legacy_lottery_slug_to_game_code: dict[str, str] = None  # type: ignore[assignment]
    legacy_lottery_slug_to_game_name: dict[str, str] = None  # type: ignore[assignment]
    legacy_results_slug_to_game_code: dict[str, str] = None  # type: ignore[assignment]
    legacy_results_slug_to_game_name: dict[str, str] = None  # type: ignore[assignment]
    legacy_promo_slug_to_bundle_slug: dict[str, str] = None  # type: ignore[assignment]

    # Legacy URLs for products the CRM does not sell. They ranked, so they must
    # go somewhere relevant rather than 404: slug (lowercased) → path.
    legacy_slug_to_path: dict[str, str] = None  # type: ignore[assignment]

    # Whole legacy paths that moved, lowercased and without a trailing slash.
    legacy_path_to_path: dict[str, str] = None  # type: ignore[assignment]

    # Optional UI fallback mapping (used only if CRM does not return `logo_url`).
    # Keyed by normalized game_name (lowercase, alnum only) → legacy image path under /resources/images/.
    legacy_game_name_to_logo_small_path: dict[str, str] = None  # type: ignore[assignment]


def load_brand_config() -> BrandConfig:
    # Single-brand repo, but keep config centralized for clarity.
    return BrandConfig(
        slug="lottoexpress",
        display_name="Lotto Express",
        # Public production domain (set WEBSITE_CANONICAL_DOMAIN in .env).
        # Used to build absolute payment return URLs that CRM must allowlist.
        canonical_domain=_canonical_domain_from_env(),
        logo_path="brands/lottoexpress/images/logo.svg",
        favicon_path="brands/lottoexpress/images/favicon.svg",
        featured_results_game_slugs=(
            "American-Powerball",
            "American-Mega-Millions",
            "EuroMillions",
            "EuroJackpot",
            "French-Lotto",
        ),
        # Confirmed against /api/v1/store/games. Keys are lowercased because the
        # old site linked these in mixed case (/lotteries/EuroMillions) and that
        # is the form Google has indexed; lookups normalise before matching.
        # Name-based fuzzy matching stays as a fallback for games added later,
        # but it must not be the primary path: it silently sent half of these
        # pages to a "currently unavailable" screen because the CRM renamed the
        # games ("Lotto 6aus49 (DE)" no longer matches "German Lotto").
        legacy_lottery_slug_to_game_code={
            "american-powerball": "powerball",
            "american-mega-millions": "megamillions",
            "euromillions": "euromillions",
            "euromillions-superdraw": "euromillions",
            "eurojackpot": "eurojackpot",
            "french-lotto": "lotto-fr",
            "german-lotto": "lotto-6aus49",
            "irish-lotto": "lotto-ie",
            "oz-lotto": "oz-lotto-au",
            "australian-lotto-645": "sat-lotto-au",
            "australian-superdraw": "sat-lotto-au",
            "superenalotto": "superenalotto",
        },
        legacy_lottery_slug_to_game_name={
            # Minimal starter set; add more as you validate CRM tenant.
            "American-Powerball": "American Powerball",
            "American-Mega-Millions": "American Mega Millions",
            "EuroMillions": "EuroMillions",
            "EuroJackpot": "EuroJackpot",
            "French-Lotto": "French Lotto",
            "German-Lotto": "German Lotto",
            "Irish-Lotto": "Irish Lotto",
            "Australian-Powerball": "Australian Powerball",
            "Australian-Lotto-645": "Australian Lotto 6/45",
            "Oz-Lotto": "Oz Lotto",
            "Canadian-Lotto-649": "Canadian Lotto 6/49",
            "Canadian-Lotto-Max": "Canadian Lotto Max",
            "Spanish-Lotto-649-La-Primitiva": "Spanish Lotto 6/49 La Primitiva",
            "SuperEnalotto": "SuperEnalotto",
        },
        legacy_results_slug_to_game_code={
            "american-powerball-winning-numbers": "powerball",
            "american-mega-millions-winning-numbers": "megamillions",
            "euromillions-winning-numbers": "euromillions",
            "eurojackpot-winning-numbers": "eurojackpot",
            "french-lotto-winning-numbers": "lotto-fr",
            "german-lotto-winning-numbers": "lotto-6aus49",
            "irish-lotto-winning-numbers": "lotto-ie",
            "oz-lotto-winning-numbers": "oz-lotto-au",
            "australian-lotto-645-winning-numbers": "sat-lotto-au",
            "superenalotto-winning-numbers": "superenalotto",
        },
        legacy_results_slug_to_game_name={
            "american-powerball-winning-numbers": "American Powerball",
            "american-mega-millions-winning-numbers": "American Mega Millions",
            "euromillions-winning-numbers": "EuroMillions",
            "eurojackpot-winning-numbers": "EuroJackpot",
            "french-lotto-winning-numbers": "French Lotto",
            "german-lotto-winning-numbers": "German Lotto",
            "irish-lotto-winning-numbers": "Irish Lotto",
            "oz-lotto-winning-numbers": "Oz Lotto",
            "spanish-lotto-649-la-primitiva-winning-numbers": "Spanish Lotto 6/49 La Primitiva",
            "superenalotto-winning-numbers": "SuperEnalotto",
        },
        # Products the old site sold that this CRM does not: send the URL to the
        # nearest relevant page instead of dropping it.
        #
        # Australian Powerball, La Primitiva and El Gordo have recovered pages in
        # `content/retired/` which are served at their own URLs and take
        # precedence over this table. These entries stay as the fallback for a
        # deploy that is missing that content, and must keep pointing at a page
        # outside `/lotteries/` or the redirect would loop.
        legacy_slug_to_path={
            "australian-powerball": "/catalog",
            "spanish-lotto-649-la-primitiva": "/catalog",
            "syndicate/el-gordo": "/catalog",
            "australian-powerball-winning-numbers": "/results",
            "spanish-lotto-649-la-primitiva-winning-numbers": "/results",
            "spanish-lotto-winning-numbers": "/results",
            "el-gordo-winning-numbers": "/results",
        },
        legacy_path_to_path={
            # The old responsible-play page.
            "/safe-play": "/responsible-gaming",
            "/lottery-results": "/results",
            # The one results PDF the archive still has a link to.
            "/lottery-results/gordo2023.s052.pdf": "/results",
            "/lotteries": "/catalog",
            # The ASP.NET MVC site that preceded the PHP one, in both languages
            # it shipped. The archive still has these indexed at 200.
            "/home/index": "/",
            "/home/aboutus": "/about",
            "/home/contactus": "/contact",
            "/home/faq": "/faq",
            "/home/howitworks": "/faq",
            "/home/privacypolicy": "/privacy",
            "/home/promotions": "/lotteries/promotions",
            "/home/responsiblegambling": "/responsible-gaming",
            "/home/selfexclusion": "/responsible-gaming",
            "/home/termsandconditions": "/terms",
            "/home/result": "/results",
            "/home/lotteries": "/catalog",
            "/en": "/",
            "/en/home/index": "/",
            "/en/home/aboutus": "/about",
            "/en/home/contactus": "/contact",
            "/en/home/faq": "/faq",
            "/en/home/howitworks": "/faq",
            "/en/home/privacypolicy": "/privacy",
            "/en/home/promotions": "/lotteries/promotions",
            "/en/home/responsiblegambling": "/responsible-gaming",
            "/en/home/selfexclusion": "/responsible-gaming",
            "/en/home/termsandconditions": "/terms",
            "/en/home/result": "/results",
            "/en/payment/checkout": "/cart",
            # French was never rebuilt; the English page is the closest thing.
            "/fr": "/",
            "/fr/home/index": "/",
            "/fr/home/aboutus": "/about",
            "/fr/home/contactus": "/contact",
            "/fr/home/faq": "/faq",
            "/fr/home/howitworks": "/faq",
            "/fr/home/privacypolicy": "/privacy",
            "/fr/home/promotions": "/lotteries/promotions",
            "/fr/home/responsiblegambling": "/responsible-gaming",
            "/fr/home/selfexclusion": "/responsible-gaming",
            "/fr/home/termsandconditions": "/terms",
            "/fr/home/result": "/results",
            "/fr/payment/checkout": "/cart",
            # The ISAPI site before that. Every page was one query string on the
            # same entry point, so the entry point is all there is to redirect.
            "/pl.dll": "/",
            "/main.html": "/",
            "/winners.html": "/",
            "/promotions": "/lotteries/promotions",
            # The root feed only ever answered the homepage; now there is a real
            # one to send it to.
            "/feed": "/blog/feed/",
            "/feed.xml": "/blog/feed/",
            "/atom.xml": "/blog/feed/",
            "/index.xml": "/blog/feed/",
        },
        legacy_promo_slug_to_bundle_slug={
            # TODO: map legacy promo pages to CRM Marketing Module bundle slugs.
            # Examples from legacy inventory (requires CRM bundle creation):
            # "American-Powerball-2_zh5rb": "powerball-rollover-2-lines",
            # "American-Mega-Millions-with-Free-Play_zkadq": "mega-millions-free-play",
            # "specialoffer1": "specialoffer1",
        },
        legacy_game_name_to_logo_small_path={
            # These are legacy site image assets (small logos).
            # If CRM returns `logo_url`, that will be preferred automatically.
            "americanpowerball": "/resources/images/s-lotto-logo-usa-powerball.png",
            "americanmegamillions": "/resources/images/s-lotto-logo-usa-mega-millions.png",
            "powerball": "/resources/images/s-lotto-logo-usa-powerball.png",
            "powerballus": "/resources/images/s-lotto-logo-usa-powerball.png",
            "megamillions": "/resources/images/s-lotto-logo-usa-mega-millions.png",
            "megamillionsus": "/resources/images/s-lotto-logo-usa-mega-millions.png",
            "euromillions": "/resources/images/s-lotto-logo-euro-millions.png",
            "euromillionssuperdraw": "/resources/images/s-lotto-logo-euromillions-superdraw.png",
            "eurojackpot": "/resources/images/s-lotto-logo-eurojackpot.png",
            "frenchlotto": "/resources/images/s-lotto-logo-french-lotto.png",
            "lottofr": "/resources/images/s-lotto-logo-lotto-france.png",
            "lottofrance": "/resources/images/s-lotto-logo-lotto-france.png",
            "germanlotto": "/resources/images/s-lotto-logo-german-lotto.png",
            "lotto6aus49": "/resources/images/s-lotto-logo-lotto-6aus49.png",
            "lotto6aus49de": "/resources/images/s-lotto-logo-lotto-6aus49.png",
            "irishlotto": "/resources/images/s-lotto-logo-irish-lotto.png",
            "ozlotto": "/resources/images/s-lotto-logo-oz-lotto.png",
            "australianpowerball": "/resources/images/s-lotto-logo-aus-powerball.png",
            "australianlotto645": "/resources/images/s-lotto-logo-aus645-lotto.png",
            "saturdaylotto": "/resources/images/s-lotto-logo-aus645-lotto.png",
            "saturdaylottoau": "/resources/images/s-lotto-logo-aus645-lotto.png",
            "satlottoau": "/resources/images/s-lotto-logo-aus645-lotto.png",
            "australiansuperdraw": "/resources/images/s-lotto-logo-australian-superdraw.png",
            "elgordo": "/resources/images/s-lotto-logo-el-gordo.png",
            "spanishlotto649laprimitiva": "/resources/images/s-lotto-logo-spanish-lotto.png",
            "spanishlotto": "/resources/images/s-lotto-logo-spanish-lotto.png",
            "superenalotto": "/resources/images/s-lotto-logo-superenalotto.png",
            "canadianlotto649": "/resources/images/s-lotto-logo-canadian-lotto-649.png",
            "canadianlottomax": "/resources/images/s-lotto-logo-canadian-lotto-max.png",
        },
    )

