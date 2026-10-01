"""
Page metadata for search engines (LottosOnline).

The rule for this site: every page that exists on www.lottosonline.com today keeps the exact title and
meta description it was captured with (content/legacy_pages, by URL). lo_routes / the app's SEO context
processor look that up first; the tables here are only the fallback for pages the old site did not
have (for example the restored UK Lotto results page) and for engine pages.

DESCRIPTION_FIXES holds the approved fixes (Joey, 1 Oct 2026: "fix short meta descriptions"): four
pages whose live description is under 100 characters. Titles are never changed.
"""

from __future__ import annotations

BRAND = "LottosOnline"
DEFAULT_TITLE = "Lottery Tickets and Lottery Results Online - LottosOnline.com"
DEFAULT_DESCRIPTION = (
    "Buy official lottery tickets online at LottosOnline and play the world's biggest jackpots, "
    "including US Powerball, Mega Millions and EuroMillions."
)

GAME_DISPLAY_NAMES: dict[str, str] = {}
GAME_SEO: dict[str, dict[str, str]] = {}
RESULTS_DESCRIPTIONS: dict[str, str] = {
    "lotto-uk": "UK Lotto results and winning numbers for every Wednesday and Saturday draw, with the latest jackpot. Check your numbers at LottosOnline.",
}

# Approved fixes for live descriptions that are too short to make a useful search snippet.
DESCRIPTION_FIXES: dict[str, str] = {
    "/lottery-tickets/australia-weekday-lotto": "Play Australia's Weekday Windfall lottery online at LottosOnline. Buy official Weekday Windfall tickets for the Monday, Wednesday and Friday draws and receive a scan of your ticket.",
    "/lottery-tickets/fr-lotto": "Play the French Lotto online at LottosOnline. Buy official French Lotto tickets for the Monday, Wednesday and Saturday draws and receive a scan of every ticket.",
    "/lottery-tickets/millionaire4life": "Play Millionaire for Life online at LottosOnline. Buy official Millionaire for Life lottery tickets from outside the USA and receive a scan of every ticket.",
    "/winning-lottery-numbers/australia-weekday-lotto": "Weekday Windfall results and winning numbers for every Monday, Wednesday and Friday draw. Check the latest Weekday Windfall numbers at LottosOnline.",
    "/winning-lottery-numbers/fr-lotto": "French Lotto results and winning numbers for every Monday, Wednesday and Saturday draw. Check the latest French Lotto numbers at LottosOnline.",
    "/winning-lottery-numbers/millionaire4life": "Millionaire for Life results and winning numbers for every draw. Check the latest Millionaire for Life numbers and prizes at LottosOnline.",
}

PAGE_SEO: dict[str, dict[str, str]] = {
    "home": {"title": DEFAULT_TITLE, "description": DEFAULT_DESCRIPTION},
}


NOINDEX_ENDPOINTS: frozenset[str] = frozenset(
    {
        "account",
        "orders",
        "order_detail",
        "legacy_orders",
        "legacy_order_detail",
        "cart",
        "cart_add_get",
        "checkout_after_topup",
        "wallet_add_funds",
        "wallet_topup",
        "wallet_topup_return",
        "wallet_payment_success",
        "wallet_payment_failed",
        "wallet_payment_cancelled",
        "legacy_wallet_confirm_order",
        "legacy_wallet_order_placed",
        "legacy_wallet_confirm_syndicate",
        "legacy_wallet_add_funds_for_promo",
        "legacy_wallet_add_funds_for_purchase",
        "verify_email",
        "reset_password",
        "set_password",
        "admin_login",
        "admin_crm_cache",
    }
)


def game_display_name(game_code: str, crm_name: str | None = None) -> str:
    import lo_lotteries

    code = (game_code or "").strip().lower()
    lot = lo_lotteries.by_game_code(code)
    return (lot.name if lot else None) or GAME_DISPLAY_NAMES.get(code) or (crm_name or code or "Lottery")


def play_seo(game_code: str, crm_name: str | None = None) -> dict[str, str]:
    code = (game_code or "").strip().lower()
    known = GAME_SEO.get(code)
    if known:
        return dict(known)
    name = game_display_name(code, crm_name)
    return {
        "title": f"Play {name} Online - Buy {name} Tickets Online",
        "description": (
            f"Play {name} online at {BRAND}. Pick your numbers or quick pick and buy official "
            f"{name} tickets for the next draw."
        ),
    }


def results_seo(game_code: str, crm_name: str | None = None) -> dict[str, str]:
    code = (game_code or "").strip().lower()
    name = game_display_name(code, crm_name)
    return {
        "title": f"{name} Results - {name} Winning Numbers",
        "description": RESULTS_DESCRIPTIONS.get(code)
        or f"{name} results and winning numbers for every draw. Check the latest {name} numbers at {BRAND}.",
    }


def page_seo(endpoint: str | None) -> dict[str, str]:
    return dict(PAGE_SEO.get(endpoint or "", {}))


def is_noindex(endpoint: str | None) -> bool:
    return (endpoint or "") in NOINDEX_ENDPOINTS


def description_for(path: str, captured: str) -> str:
    return DESCRIPTION_FIXES.get(path) or captured
