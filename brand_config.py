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
    # Single-brand repo. LottosOnline's lottery slugs, legacy codes and URL rules live in
    # lo_lotteries.py (one table drives play, information and results pages); the generic
    # legacy tables below are kept empty so the inherited Lotto Express routes stay inert.
    return BrandConfig(
        slug="lottosonline",
        display_name="LottosOnline",
        canonical_domain=_canonical_domain_from_env() or "www.lottosonline.com",
        logo_path="brands/lottosonline/img/logo-on-dark.webp",
        favicon_path="brands/lottosonline/img/favicon-196.png",
        featured_results_game_slugs=(
            "us-powerball",
            "mega-millions",
            "euromillions",
            "eurojackpot",
            "fr-lotto",
        ),
        legacy_lottery_slug_to_game_code={},
        legacy_lottery_slug_to_game_name={},
        legacy_results_slug_to_game_code={},
        legacy_results_slug_to_game_name={},
        legacy_slug_to_path={},
        legacy_path_to_path={},
        legacy_promo_slug_to_bundle_slug={},
        legacy_game_name_to_logo_small_path={},
    )
