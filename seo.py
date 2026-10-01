"""
Page metadata for search engines.

The site this replaces ranked on per-page titles and descriptions that were
written and tuned over years; this app shipped one global title and no
description at all, so a cutover would have thrown those signals away. The
titles and descriptions below for the game and results pages are the ones the
old site served on the equivalent URL (recovered from the Wayback Machine), so
the move keeps them. Everything else is written to the same house style
("<Page> | Lotto Express").

Keyed by CRM `game_code`, because that is what the new URLs carry. Games the CRM
adds later fall back to a generated title rather than the site-wide default.
"""

from __future__ import annotations

BRAND = "Lotto Express"
DEFAULT_TITLE = "Lotto Express | Play the World's Biggest Lotto Jackpots Online!"
DEFAULT_DESCRIPTION = (
    "Play the world's biggest lottery jackpots online with Lotto Express. "
    "Register a free account, deposit funds and play EuroMillions, Powerball, "
    "Mega Millions and more."
)

# The name the old site used for each game in titles and copy. These differ from
# the CRM's own names ("Powerball (US)"), and it is the old wording that the
# rankings were earned on.
GAME_DISPLAY_NAMES: dict[str, str] = {
    "powerball": "American Powerball",
    "megamillions": "American Mega Millions",
    "euromillions": "EuroMillions",
    "eurojackpot": "EuroJackpot",
    "lotto-fr": "French Lotto",
    "lotto-6aus49": "German Lotto 6aus49",
    "lotto-ie": "Irish Lotto",
    "oz-lotto-au": "Oz Lotto",
    "sat-lotto-au": "Australian Lotto 6/45",
    "superenalotto": "SuperEnalotto",
}

# Play pages: exactly what the old /lotteries/<Game> page served.
GAME_SEO: dict[str, dict[str, str]] = {
    "powerball": {
        "title": "Play Powerball Lottery Jackpots Online with Lotto Express",
        "description": (
            "Lotto Express is a lottery site that allows you to play American Powerball "
            "online. Play for free, win the biggest cash prizes on Saturday, Monday & "
            "Wednesday!"
        ),
    },
    "megamillions": {
        "title": "Play Mega Millions Online | American Lottery | Lotto Express",
        "description": (
            "The jackpot of the American Mega Millions is an incredible prize that you can "
            "win by playing jackpot online. Play with Lotto Express and win exciting prizes."
        ),
    },
    "euromillions": {
        "title": "Play EuroMillions, Online Lottery Jackpot with Lotto Express",
        "description": (
            "With Lotto Express, EuroMillions lottery jackpots are easier to play and win! "
            "This is the biggest lottery jackpot online! We have bonus weekly draws for members."
        ),
    },
    "eurojackpot": {
        "title": "Play EuroJackpot, Online Lottery Jackpot with Lotto Express",
        "description": (
            "With Lotto Express, EuroJackpot lottery jackpots are easier to play and win! "
            "This is the biggest lottery jackpot online! We have bonus weekly draws for members."
        ),
    },
    "lotto-fr": {
        "title": "Play French Lotto Jackpot Online Today | Lotto Express",
        "description": (
            "Play and win the biggest French Lotto jackpot online. With Lotto Express get a "
            "chance to win biggest lottery jackpots. Register, deposit fund, play & win!!"
        ),
    },
    "lotto-6aus49": {
        "title": "Play German Lotto 6aus49 Jackpot Online Today | Lotto Express",
        "description": (
            "Play and win the biggest German Lotto 6aus49 jackpot online. With Lotto Express "
            "get a chance to win biggest lottery jackpots. Register, deposit fund, play & win!!"
        ),
    },
    "lotto-ie": {
        "title": "Play Online and Win Irish Lotto Jackpot Today | Lotto Express",
        "description": (
            "Play the Irish Lottery Online with Lotto Express. Our Irish Lotto draws take "
            "place each Wednesday and Saturday. Registration is free, and winning is super easy!"
        ),
    },
    "oz-lotto-au": {
        "title": "Play the Biggest Oz Lotto Jackpot Online with Lotto Express",
        "description": (
            "Play Oz Lotto Online with Lotto Express. Grab your chance of winning exciting "
            "prizes every Tuesday. The Registrations process is free, and winning is easy!"
        ),
    },
    "sat-lotto-au": {
        "title": "Play Australian Lotto Jackpot Online with Lotto Express",
        "description": (
            "Play the Australian Lotto 6/45 jackpot online every Saturday and win exciting "
            "prize money. Registration is free with Lotto Express, and winning is easy!"
        ),
    },
    "superenalotto": {
        "title": "Play SuperEnalotto, Online Lottery Jackpot with Lotto Express",
        "description": (
            "With Lotto Express, SuperEnalotto lottery jackpots are easier to play and win! "
            "This is the biggest lottery jackpot online! We have bonus weekly draws for members."
        ),
    },
}

# Results pages kept the old title pattern; the old descriptions were a single
# broken site-wide string, so these are written per game.
RESULTS_DESCRIPTIONS: dict[str, str] = {
    "powerball": (
        "Check the latest American Powerball winning numbers and past results online, "
        "draw by draw, with Lotto Express."
    ),
    "megamillions": (
        "Check the latest American Mega Millions winning numbers and past results online, "
        "draw by draw, with Lotto Express."
    ),
    "euromillions": (
        "Check the latest EuroMillions winning numbers and past results online, including "
        "Lucky Stars, with Lotto Express."
    ),
    "eurojackpot": (
        "Check the latest EuroJackpot winning numbers and past results online, draw by draw, "
        "with Lotto Express."
    ),
    "lotto-fr": "Check the latest French Lotto winning numbers and past results online with Lotto Express.",
    "lotto-6aus49": (
        "Check the latest German Lotto 6aus49 winning numbers and past results online with Lotto Express."
    ),
    "lotto-ie": (
        "Check the latest Irish Lotto winning numbers from every Wednesday and Saturday draw "
        "with Lotto Express."
    ),
    "oz-lotto-au": "Check the latest Oz Lotto winning numbers from every Tuesday draw with Lotto Express.",
    "sat-lotto-au": (
        "Check the latest Australian Lotto 6/45 winning numbers from every Saturday draw with Lotto Express."
    ),
    "superenalotto": "Check the latest SuperEnalotto winning numbers and past results online with Lotto Express.",
}

# Static pages, by Flask endpoint. Titles match the old site where it had one.
PAGE_SEO: dict[str, dict[str, str]] = {
    "home": {"title": DEFAULT_TITLE, "description": DEFAULT_DESCRIPTION},
    "catalog": {
        "title": "Play Online Lotteries | The World's Biggest Jackpots | Lotto Express",
        "description": (
            "Browse every lottery you can play online with Lotto Express, from EuroMillions "
            "and Powerball to Oz Lotto, with current jackpots and draw times."
        ),
    },
    "results_index": {
        "title": "Lottery Results | Lotto Express",
        "description": (
            "Winning numbers for every lottery we offer, updated after each draw. Check your "
            "numbers online with Lotto Express."
        ),
    },
    "promotions_index": {
        "title": "Promotions | Lotto Express",
        "description": "Current lottery promotions, bundles and free play offers from Lotto Express.",
    },
    "about": {
        "title": "About Us | Lotto Express",
        "description": (
            "Lotto Express lets you play the world's biggest lottery jackpots online. Learn who "
            "we are and how playing with us works."
        ),
    },
    "contact": {
        "title": "Contact Us | Lotto Express",
        "description": "Get in touch with the Lotto Express support team by email or phone.",
    },
    "faq": {
        "title": "Frequently Asked Questions | Lotto Express",
        "description": (
            "Answers to the questions we are asked most about playing lotteries online, "
            "deposits, withdrawals, prizes and account security."
        ),
    },
    "responsible_gaming": {
        "title": "Responsible Gaming | Lotto Express",
        "description": (
            "Lotto Express is committed to responsible play: deposit limits, self-exclusion and "
            "where to find help."
        ),
    },
    "terms": {
        "title": "Terms and Conditions | Lotto Express",
        "description": "The terms and conditions that apply to playing lotteries online with Lotto Express.",
    },
    "privacy": {
        "title": "Privacy Policy | Lotto Express",
        "description": "How Lotto Express collects, uses and protects your personal information.",
    },
    "privacy_au": {
        "title": "Privacy Policy (Australia) | Lotto Express",
        "description": "How Lotto Express handles personal information for players in Australia.",
    },
    "privacy_world": {
        "title": "Privacy Policy | Lotto Express",
        "description": "How Lotto Express collects, uses and protects your personal information.",
    },
    "identity_verification_info": {
        "title": "Identity Verification | Lotto Express",
        "description": (
            "Why we verify your identity, which documents we accept and how to send them to "
            "Lotto Express."
        ),
    },
    "login": {
        "title": "Login | Lotto Express",
        "description": "Sign in to your Lotto Express account to play, check tickets and manage your funds.",
    },
    "register": {
        "title": "Register | Lotto Express",
        "description": (
            "Create a free Lotto Express account in a minute and start playing the world's "
            "biggest lottery jackpots online."
        ),
    },
    "forgot_password": {
        "title": "Reset Your Password | Lotto Express",
        "description": "Request a password reset link for your Lotto Express account.",
    },
}

# Pages that must never be indexed: private, transactional, or a duplicate of a
# page that is already indexable. `follow` is kept so link equity still flows.
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
    code = (game_code or "").strip().lower()
    return GAME_DISPLAY_NAMES.get(code) or (crm_name or code or "Lottery")


def play_seo(game_code: str, crm_name: str | None = None) -> dict[str, str]:
    code = (game_code or "").strip().lower()
    known = GAME_SEO.get(code)
    if known:
        return dict(known)
    name = game_display_name(code, crm_name)
    return {
        "title": f"Play {name} Online | {BRAND}",
        "description": (
            f"Play {name} online with {BRAND}. Pick your numbers or quick pick, check the "
            "current jackpot and enter the next draw."
        ),
    }


def results_seo(game_code: str, crm_name: str | None = None) -> dict[str, str]:
    code = (game_code or "").strip().lower()
    name = game_display_name(code, crm_name)
    return {
        "title": f"{name} Online Winning Numbers | {BRAND}",
        "description": RESULTS_DESCRIPTIONS.get(code)
        or f"Check the latest {name} winning numbers and past results online with {BRAND}.",
    }


def page_seo(endpoint: str | None) -> dict[str, str]:
    return dict(PAGE_SEO.get(endpoint or "", {}))


def is_noindex(endpoint: str | None) -> bool:
    return (endpoint or "") in NOINDEX_ENDPOINTS
