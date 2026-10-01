"""
The play page cannot be bought from unless a draw day is on it.

Draw weekdays are not in the CRM feed — jackpots carry only the next cutoff —
so the picker holds its own map of game code to weekdays. A game missing from
that map ticks nothing, and nothing ticked is zero draws, a total of 0.00 and a
dead Play button, with no clue on the page as to why. German Lotto and Irish
Lotto shipped that way. These tests keep the map level with the catalogue.
"""

from __future__ import annotations

import re

import pytest

from conftest import ALL_GAME_CODES


def _function_body(js: str, name: str) -> str:
    match = re.search(r"function " + re.escape(name) + r"\b.*?\n  \}", js, re.S)
    assert match, f"{name} is no longer in play_picker.js"
    return match.group(0)


@pytest.fixture
def picker_js(client) -> str:
    resp = client.get("/resources/js/play_picker.js")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.mark.parametrize("game_code", ALL_GAME_CODES)
def test_every_game_we_sell_has_draw_weekdays(picker_js, game_code):
    assert f'"{game_code}"' in _function_body(picker_js, "drawWeekdaysForGame")


@pytest.mark.parametrize("game_code", ALL_GAME_CODES)
def test_every_game_we_sell_has_a_draw_timezone(picker_js, game_code):
    """Weekday labels are formatted in the lottery's own timezone. Left to
    default to UTC, a late-evening European draw can name the wrong day."""
    assert f'"{game_code}"' in _function_body(picker_js, "timeZoneForGame")


def test_german_and_irish_lotto_draw_on_wednesday_and_saturday(picker_js):
    body = _function_body(picker_js, "drawWeekdaysForGame")
    for game_code in ("lotto-6aus49", "lotto-ie"):
        line = next(ln for ln in body.splitlines() if f'"{game_code}"' in ln)
        assert "[3, 6]" in line, f"{game_code} should draw Wed and Sat, got: {line.strip()}"


def test_an_unmapped_game_still_offers_the_draw_its_cutoff_names(picker_js):
    """
    The map will fall behind the catalogue again the next time a game is added.
    When it does, the cutoff the CRM did send names one real draw, and offering
    that beats a page with a price of zero and no way to proceed.
    """
    assert "weekdays = [weekdayIndexInTz(base, tz)]" in picker_js
    # The inert label is now reachable only with no usable cutoff at all.
    assert "if (!base || !weekdays.length)" in picker_js
