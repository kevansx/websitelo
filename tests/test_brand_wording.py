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
