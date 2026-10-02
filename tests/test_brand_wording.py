"""The engine came from Lotto Express: no customer-facing page may name it."""
import re

import pytest

LEAK = re.compile(r"lotto\s*express", re.I)


@pytest.mark.parametrize("path", ["/account", "/wallet/add-funds", "/cart", "/orders"])
def test_money_pages_do_not_name_lotto_express(client, stub_crm, path):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    assert not LEAK.search(html), LEAK.search(html).group(0)


def test_engine_scripts_load_nothing_from_lottoexpress_com():
    from pathlib import Path
    js = Path(__file__).resolve().parent.parent / "static" / "brands" / "engine" / "js"
    hits = [p.name for p in js.glob("*.js") if "lottoexpress.com" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == []


def test_euromillions_jackpot_is_shown_in_euros(client, monkeypatch):
    app = client.application
    # The CRM's "euromillions" feed is the UK one (GBP); LottosOnline sells and shows EuroMillions in EUR.
    rows = [
        {"game_code": "euromillions", "currency": "GBP", "jackpot": {"amount": 24_000_000, "currency": "GBP"},
         "next_draw_utc": "2099-01-01T20:00:00Z"},
        {"game_code": "euromillions-es", "currency": "EUR", "jackpot": {"amount": 28_000_000, "currency": "EUR"}},
    ]
    eng = dict(app.config["LO_ENGINE"])
    eng["jackpots_live_or_cache"] = lambda **k: (rows, None)
    monkeypatch.setitem(app.config, "LO_ENGINE", eng)
    jp = app.jinja_env.globals["lo_jackpot"]("euromillions")
    assert jp["currency"] == "EUR" and jp["display"].startswith("€28")
    assert jp["cutoff_iso"].startswith("2099-01-01")    # draw time still from the game's own feed
