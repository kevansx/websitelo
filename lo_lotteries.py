"""LottosOnline lottery table: the one place that ties a public URL slug to a CRM game.

Every lottery has up to three public pages, and the slugs below are the ones Google has indexed:

    /lottery-tickets/<slug>           play page (number picker)
    /lotteries/<slug>                 lottery information
    /winning-lottery-numbers/<slug>   results

Old or misspelt slugs (usa-powerball, us-megamillions, german-lottery, ...) are NOT listed here: their
exact redirects are generated from the URL contract into content/legacy_redirects.json, so the new
site reproduces the old behaviour URL by URL instead of by pattern.

`game_code` is the CRM `lotto_games.code`. Codes marked `confirm` were not in the CRM's global jackpot
feed on 1 Oct 2026 and must be checked against the LottosOnline brand's /store/games once its service
key is available.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lottery:
    slug: str
    name: str            # display name as the old site printed it
    game_code: str       # CRM game code
    legacy_code: str     # old lo_lottery code suffix, used by the old image names (logo_main_<code>.png)
    sells: bool = True   # has a play page
    info: bool = True    # has a /lotteries page
    results: bool = True # has a results page
    confirm: bool = False


LOTTERIES: tuple[Lottery, ...] = (
    Lottery("us-powerball", "US Powerball", "powerball", "uspow"),
    Lottery("mega-millions", "Mega Millions", "megamillions", "usmeg"),
    Lottery("superlotto-plus", "SuperLotto Plus", "superlotto-plus-ca-us", "uscal"),
    Lottery("lotto-america", "Lotto America", "lotto-america", "uslot"),
    Lottery("millionaire4life", "Millionaire for Life", "millionaire-for-life-us", "uslif", confirm=True),
    Lottery("euromillions", "EuroMillions", "euromillions", "eueur"),
    Lottery("eurojackpot", "EuroJackpot", "eurojackpot", "eujac"),
    Lottery("superenalotto", "SuperEnaLotto", "superenalotto", "itsup"),
    Lottery("el-gordo", "Spanish El Gordo", "el-gordo-primitiva", "eselg"),
    Lottery("la-primitiva", "Spanish La Primitiva", "la-primitiva-es", "eslap", confirm=True),
    Lottery("bonoloto", "BonoLoto", "bonoloto", "esbon"),
    Lottery("german-lotto", "German Lotto", "lotto-6aus49", "delot"),
    Lottery("fr-lotto", "French Lotto", "lotto-fr", "frlot"),
    Lottery("irish-lotto", "Irish Lotto", "lotto-ie", "ielot"),
    Lottery("thunderball", "UK Thunderball", "thunderball", "ukthu"),
    Lottery("australia-powerball", "Australia Powerball", "powerball-au", "aupow"),
    Lottery("australia-oz-lotto", "Oz Lotto", "oz-lotto-au", "aulot"),
    Lottery("australia-saturday-lotto", "Australia Saturday Lotto", "sat-lotto-au", "autat"),
    Lottery("australia-weekday-lotto", "Australian Weekday Windfall", "weekday-windfall-au", "aumon"),
    # Not sold any more: results page only (Joey, 1 Oct 2026). Ticket and information URLs 301 to the hubs.
    Lottery("uk-lotto", "UK Lotto", "lotto-uk", "uklot", sells=False, info=False),
)

BY_SLUG = {l.slug: l for l in LOTTERIES}
BY_GAME_CODE = {l.game_code: l for l in LOTTERIES}


def by_slug(slug: str) -> Lottery | None:
    return BY_SLUG.get((slug or "").strip().lower())


def by_game_code(code: str) -> Lottery | None:
    return BY_GAME_CODE.get((code or "").strip().lower())


def play_path(l: Lottery) -> str:
    return f"/lottery-tickets/{l.slug}"


def info_path(l: Lottery) -> str:
    return f"/lotteries/{l.slug}"


def results_path(l: Lottery) -> str:
    return f"/winning-lottery-numbers/{l.slug}"


# --- URL converters --------------------------------------------------------------------------
# The inherited views take a CRM `game_code`; LottosOnline URLs carry a slug. These converters turn
# /lottery-tickets/us-powerball into game_code="powerball" on the way in, and make
# url_for("play", game_code="powerball") build /lottery-tickets/us-powerball on the way out, so no view
# or template has to know about slugs. An unknown slug fails the match (a 404 or a later route),
# never a page for an invented lottery.
from werkzeug.routing import BaseConverter, ValidationError  # noqa: E402


class _LotteryConverter(BaseConverter):
    regex = r"[A-Za-z0-9-]+"
    wants = "sells"

    def to_python(self, value: str) -> str:
        lot = by_slug(value)
        if lot is None or not getattr(lot, self.wants) or value != lot.slug:
            raise ValidationError()
        return lot.game_code

    def to_url(self, value: str) -> str:
        lot = by_game_code(value) or by_slug(value)
        if lot is None:
            raise ValueError(f"no LottosOnline slug for game {value!r}")
        return lot.slug


class PlayConverter(_LotteryConverter):
    wants = "sells"


class ResultsConverter(_LotteryConverter):
    wants = "results"


class InfoConverter(_LotteryConverter):
    wants = "info"


def register_converters(app) -> None:
    app.url_map.converters["lo_play"] = PlayConverter
    app.url_map.converters["lo_results"] = ResultsConverter
    app.url_map.converters["lo_info"] = InfoConverter


# --- "% above base" --------------------------------------------------------------------------
# The old site printed "2100 % above base" beside each jackpot. These starting jackpots are read back from
# its own figures on 1 Oct 2026 (US$440M at 2100% -> US$20M, EUR 106M at 960% -> EUR 10M, ...), in the
# jackpot's own currency, so the new site shows the same percentages. Lotteries the old site showed no
# percentage for (fixed or near-fixed top prizes) have no entry.
BASE_JACKPOTS: dict[str, float] = {
    "powerball": 20_000_000,
    "megamillions": 50_000_000,
    "eurojackpot": 10_000_000,
    "superlotto-plus-ca-us": 7_000_000,
    "oz-lotto-au": 3_000_000,
    "powerball-au": 10_000_000,
    "lotto-6aus49": 1_000_000,
    "el-gordo-primitiva": 4_500_000,
    "lotto-america": 2_000_000,
    "lotto-ie": 2_000_000,
    "lotto-fr": 2_000_000,
    "euromillions": 17_000_000,
    "la-primitiva-es": 2_000_000,
}


def rise_pct(game_code: str, amount) -> int | None:
    base = BASE_JACKPOTS.get(game_code)
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    if not base or amt <= base:
        return None
    return int(round((amt - base) / base * 100))
