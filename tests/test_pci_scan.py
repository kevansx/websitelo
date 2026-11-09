"""
The PCI scan findings (Nov 2026). The scan was of lottoexpress.com, which runs the same engine, so every finding is
fixed here too before the scan reaches lottosonline.com.

1. Mixed content: a link over http on an https page (here the affiliate site, in the footer and the FAQs).
2. Auto-completion enabled for password fields: each password field and its form must say autocomplete="off".
3. Insecure cookie attributes: every cookie must be HttpOnly and Secure. The cookie banner set its cookie from
   JavaScript, which can't, and the affiliate cookie was set without either flag.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent
TEMPLATES = SITE / "templates"
PAGES = SITE / "content" / "legacy_pages"
INDEX_JS = SITE / "static" / "brands" / "engine" / "js" / "index.js"
HTTP_LINK = re.compile(r'(?:href|src|action)\s*=\s*\\?["\']http://')


@pytest.fixture(autouse=True)
def _secure_cookies_as_on_the_servers(monkeypatch):
    """A local .env may turn Secure off for plain-http testing; the servers never do."""
    from app import app as flask_app
    monkeypatch.setitem(flask_app.config, "SESSION_COOKIE_SECURE", True)


def test_no_template_links_or_loads_anything_over_http():
    offenders = [f"{p.relative_to(TEMPLATES)}: {m.group(0)}"
                 for p in TEMPLATES.rglob("*.html") for m in HTTP_LINK.finditer(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


def test_no_carried_over_page_links_anything_over_http():
    offenders = [f"{p.name}: {m.group(0)}"
                 for p in PAGES.glob("*.json") for m in HTTP_LINK.finditer(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


@pytest.mark.parametrize("path", ["/", "/faqs"])
def test_the_pages_as_served_link_nothing_over_http(anon_client, stub_crm, path):
    body = anon_client.get(path).get_data(as_text=True)
    assert not HTTP_LINK.search(body), HTTP_LINK.search(body).group(0)


def test_every_password_field_and_its_form_turn_autocomplete_off():
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        for field in re.finditer(r"<input\b[^>]*type=\"password\"[^>]*>", html):
            if 'autocomplete="off"' not in field.group(0):
                offenders.append(f"{path.relative_to(TEMPLATES)}: field {field.group(0)}")
            form_start = html.rfind("<form", 0, field.start())
            form_tag = html[form_start: html.index(">", form_start) + 1]
            if 'autocomplete="off"' not in form_tag:
                offenders.append(f"{path.relative_to(TEMPLATES)}: form {form_tag}")
    assert not offenders, offenders


@pytest.mark.parametrize("path", ["/login", "/create-account"])
def test_the_sign_in_and_sign_up_pages_as_served_turn_autocomplete_off(anon_client, stub_crm, path):
    body = anon_client.get(path).get_data(as_text=True)
    field = re.search(r'<input[^>]*type="password"[^>]*>', body).group(0)
    form = body[body.rfind("<form", 0, body.index(field)):]
    form = form[: form.index(">") + 1]
    assert 'autocomplete="off"' in form
    assert 'autocomplete="off"' in field


def test_accepting_the_cookie_banner_sets_an_httponly_secure_cookie(anon_client, stub_crm):
    resp = anon_client.post("/cookie-consent")

    assert resp.status_code == 204
    header = resp.headers["Set-Cookie"]
    assert header.startswith("cookiePrompt=on")
    assert "HttpOnly" in header and "Secure" in header


def test_the_page_tells_the_banner_whether_it_was_accepted(anon_client, stub_crm):
    before = anon_client.get("/offer/anything").get_data(as_text=True)
    anon_client.post("/cookie-consent")
    after = anon_client.get("/offer/anything").get_data(as_text=True)

    assert 'id="cookieWarning"' in before and 'data-accepted="0"' in before
    assert 'data-accepted="1"' in after


@pytest.mark.parametrize("call", ['createCookie("cookiePrompt"', 'document.cookie = "cookiePrompt'])
def test_the_banner_script_no_longer_sets_the_cookie_itself(call):
    assert call not in INDEX_JS.read_text(encoding="utf-8")


def test_the_affiliate_cookie_is_httponly_and_secure(anon_client, stub_crm):
    resp = anon_client.get("/?a=8003&c=15646")
    header = next(h for h in resp.headers.getlist("Set-Cookie") if h.startswith("abc="))
    assert "HttpOnly" in header and "Secure" in header


def test_every_cookie_the_site_sets_is_httponly_and_secure(client, stub_crm):
    """A sweep over the pages a visitor and a signed-in customer reach first."""
    offenders = []
    for path in ("/", "/?a=1&c=2", "/login", "/create-account", "/lottery-tickets", "/account", "/cart", "/faqs"):
        for header in client.get(path).headers.getlist("Set-Cookie"):
            if "HttpOnly" not in header or "Secure" not in header:
                offenders.append(f"{path}: {header.split(';')[0].split('=')[0]}")
    assert not offenders, offenders
