"""
Custom offer links: /o/<code>, /o/<code>/done and /o/<code>/t (docs/custom-offer-links-spec.md, v2).

A supervisor's offer, paid from one link with no login. These walk every state the pages
show against fake_crm.FakeCustomOffers, the switch that keeps it all off until the brand is
on the CRM, the hand-over to the existing payment flow, the tracking relay, the rate limit,
and what the page must never contain: third-party scripts, card fields, cookies.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest
import requests

from app import app as flask_app
from crm_api import CRMClient, CRMConfig
from fake_crm import FakeCustomOffers as F

SITE = Path(__file__).resolve().parent.parent
TEMPLATE = SITE / "templates" / "lo" / "custom_offer.html"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PUBLIC_IP = {"X-Forwarded-For": "86.48.8.213"}


@pytest.fixture
def crm(monkeypatch, tmp_path):
    monkeypatch.setitem(flask_app.config, "CUSTOM_OFFERS_ENABLED", True)
    monkeypatch.setitem(flask_app.config, "CUSTOM_OFFERS_INLINE_EVENTS", True)
    monkeypatch.setitem(flask_app.config, "CUSTOM_OFFERS_DB_PATH", str(tmp_path / "custom_offers.sqlite"))
    return F().patch(monkeypatch.setattr)


@pytest.fixture
def web(anon_client, crm):
    return anon_client


def _calls(crm, kind):
    return [c for k, c in crm.calls if k == kind]


def _h1(body: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def _markup(body: str) -> str:
    """The page without its script, which names every element it may touch."""
    return body.split("<script>")[0]


# --------------------------------------------------------------------------- the switch
@pytest.mark.parametrize(
    "method, path",
    [("get", "/o/{c}"), ("get", "/o/{c}/done"), ("get", "/o/{c}/status"), ("post", "/o/{c}/pay"),
     ("post", "/o/{c}/t"), ("post", "/o/{c}/call")],
)
def test_everything_is_404_until_custom_offers_are_switched_on(anon_client, monkeypatch, tmp_path, method, path):
    fake = F().patch(monkeypatch.setattr)
    monkeypatch.setitem(flask_app.config, "CUSTOM_OFFERS_ENABLED", False)

    resp = getattr(anon_client, method)(path.format(c=F.OPEN))

    assert resp.status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize("value, want", [(None, False), ("", False), ("0", False), ("no", False), ("1", True), ("true", True)])
def test_the_switch_is_off_unless_the_environment_turns_it_on(monkeypatch, value, want):
    import lo_custom_offers

    if value is None:
        monkeypatch.delenv("CUSTOM_OFFERS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CUSTOM_OFFERS_ENABLED", value)
    assert lo_custom_offers.switched_on_in_env() is want


def test_the_servers_example_settings_keep_it_off():
    assert "\nCUSTOM_OFFERS_ENABLED=0" in (SITE / "env.example").read_text(encoding="utf-8").replace("\r\n", "\n")


# --------------------------------------------------------------------------- the offer page
def test_an_open_offer_shows_everything_the_customer_needs(web, crm):
    resp = web.get(f"/o/{F.OPEN}")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Hi Ahmed, here is the offer we discussed" in body
    assert "Powerball, 10 lines for the next 4 draws" in body
    assert '<p class="amount">US$150.00</p>' in body
    assert ">Pay US$150.00</button>" in body
    assert "This will show on your statement as LOTTOSONLINE.COM." in body
    assert "Paying adds US$150.00 to your Lottos Online account; your agent will place your tickets." in body
    assert "+357 22 000254" in body and "support@lottosonline.com" in body
    assert "Ask us to call you" in body
    assert "Your card will be charged" not in body


def test_a_charge_in_another_currency_is_spelled_out(web):
    body = web.get(f"/o/{F.OPEN_FX}").get_data(as_text=True)

    assert '<p class="amount">€100.00</p>' in body
    assert "Your card will be charged US$116.50." in body


def test_one_request_id_per_page_load_goes_with_the_call(web, crm):
    web.get(f"/o/{F.OPEN}")
    web.get(f"/o/{F.OPEN}")

    first, second = _calls(crm, "get")
    assert first["view"] == "page"
    assert UUID.match(first["request_id"]) and UUID.match(second["request_id"])
    assert first["request_id"] != second["request_id"]


def test_the_crm_call_carries_the_request_id_header_and_the_customers_browser(monkeypatch):
    sent = {}
    monkeypatch.setattr(CRMClient, "_request", lambda self, method, path, **kw: sent.update(path=path, **kw) or {})
    client = CRMClient(CRMConfig(base_url="https://crm.invalid", service_key="k"))

    client.custom_offer_get("abc", "page", "rid-1", "86.48.8.213", "UA", "en-GB")
    assert sent["path"] == "/api/v1/custom-offers/abc"
    assert sent["extra_headers"] == {"X-Request-Id": "rid-1"}
    assert sent["params"] == {"view": "page", "client_ip": "86.48.8.213", "user_agent": "UA", "accept_language": "en-GB"}
    assert sent["timeout_seconds"] == 10

    client.custom_offer_pay("abc", "https://lottosonline.com/o/abc/done", "rid-1", None, "UA", None)
    assert sent["path"] == "/api/v1/custom-offers/abc/pay"
    assert sent["json"] == {"return_url": "https://lottosonline.com/o/abc/done", "user_agent": "UA"}
    assert sent["timeout_seconds"] == 25

    client.custom_offer_events("abc", "rid-1", "86.48.8.213", "UA", [{"event": "pay_clicked"}] * 60)
    assert sent["path"] == "/api/v1/custom-offers/abc/events"
    assert len(sent["json"]["events"]) == 50


def test_the_request_id_header_reaches_the_wire(monkeypatch):
    seen = {}

    class Answer:
        ok, status_code = True, 200

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(requests.Session, "request", lambda self, m, url, **kw: seen.update(kw) or Answer())
    CRMClient(CRMConfig(base_url="https://crm.invalid", service_key="k")).custom_offer_get(
        "abc", "page", "rid-9", None, None, None
    )
    assert seen["headers"]["X-Request-Id"] == "rid-9"
    assert seen["headers"]["X-CRM-API-Key"] == "k"


def test_a_paid_offer_says_thank_you_with_no_pay_button(web):
    body = web.get(f"/o/{F.PAID}").get_data(as_text=True)

    assert _h1(body) == "Payment received, thank you."
    assert 'id="paybtn"' not in body and "/pay" not in _markup(body)


@pytest.mark.parametrize("code, status", [(F.EXPIRED, 200), (F.CANCELLED, 200), ("UnknownCode00000000000", 404)])
def test_expired_cancelled_and_unknown_codes_all_get_the_same_page(web, code, status):
    resp = web.get(f"/o/{code}")
    body = resp.get_data(as_text=True)

    assert resp.status_code == status
    assert _h1(body) == "This offer is no longer available."
    assert "Please contact us and we'll send you a new one." in body
    assert "Ask us to call you" in body
    assert 'id="paybtn"' not in body


def test_a_code_with_characters_no_link_has_never_reaches_the_crm(web, crm):
    resp = web.get("/o/abc%22%3E%3Cscript%3E")

    assert resp.status_code == 404
    assert _calls(crm, "get") == []


def test_a_crm_that_does_not_answer_gets_an_error_page_with_a_reference(web, crm):
    resp = web.get(f"/o/{F.SLOW}")
    body = resp.get_data(as_text=True)

    rid = _calls(crm, "get")[0]["request_id"]
    assert resp.status_code == 503
    assert f"Reference: {rid[:6].upper()}" in body


def test_crm_unreachable_is_kept_and_sent_once_the_crm_answers_again(web, crm):
    web.get(f"/o/{F.SLOW}")
    assert [e for e in crm.events if e["event"] == "crm_unreachable"] == []

    web.get(f"/o/{F.OPEN}")

    (kept,) = [e for e in crm.events if e["event"] == "crm_unreachable"]
    assert kept["code"] == F.SLOW
    assert kept["detail"]["call"] == "5.1" and kept["detail"]["reason"] == "timeout"


def test_the_pages_are_kept_out_of_search_and_referrers(web):
    resp = web.get(f"/o/{F.OPEN}")

    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert '<meta name="referrer" content="no-referrer">' in resp.get_data(as_text=True)


@pytest.mark.parametrize("path", ["/o/{c}", "/o/{c}?a=8003&c=15646&src=x&tid=y", "/o/{c}/done"])
def test_no_page_sets_a_cookie_even_for_a_visitor_with_a_session(client, crm, path):
    resp = client.get(path.format(c=F.OPEN))

    assert resp.headers.getlist("Set-Cookie") == []


# --------------------------------------------------------------------------- what the page may load
def test_the_template_stands_alone_and_loads_nothing_from_anywhere_else():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "{% extends" not in html and "{% include" not in html
    assert "<script src" not in html
    assert not re.search(r"""(?:src|href)=["']https?://""", html.replace("https://wa.me/", ""))
    for third_party in ("googletagmanager", "gtag(", "fbq(", "facebook.net", "hotjar", "clarity", "fonts.googleapis"):
        assert third_party not in html


def test_the_rendered_page_has_no_card_field_and_no_third_party_request(web):
    body = web.get(f"/o/{F.OPEN}").get_data(as_text=True)

    for field in ("card_number", "cardnumber", "cvv", "cvc", "exp_month", "exp_year", "cc-number", "cc-csc"):
        assert field not in body.lower()
    assert re.findall(r"""<script[^>]+src=""", body) == []
    for url in re.findall(r"""(?:src|href|action)=["']([^"']+)""", body):
        assert url.startswith(("/", "tel:", "mailto:", "https://wa.me/")), url


def test_the_page_and_everything_it_loads_is_under_150_kb(web):
    body = web.get(f"/o/{F.OPEN}").get_data()
    assets = sum(
        (SITE / "static" / p.split("/static/", 1)[1]).stat().st_size
        for p in re.findall(r'src="(/static/[^"]+)"', body.decode())
    )
    assert len(body) + assets < 150 * 1024


# --------------------------------------------------------------------------- paying
def test_pay_hands_over_to_the_processor_page_with_the_customers_own_ip(web, crm):
    resp = web.post(f"/o/{F.OPEN}/pay", data={}, headers={**PUBLIC_IP, "User-Agent": "Phone/1.0",
                                                          "Accept-Language": "en-GB"})

    (paid,) = _calls(crm, "pay")
    assert resp.status_code == 302
    assert resp.headers["Location"] == paid["return_url"]  # the fake's processor returns straight away
    assert paid["client_ip"] == "86.48.8.213"
    assert paid["user_agent"] == "Phone/1.0" and paid["accept_language"] == "en-GB"


@pytest.mark.parametrize("forwarded, want", [("86.48.8.213", "86.48.8.213"), ("2001:db8::1", None), ("10.0.0.4", None)])
def test_client_ip_is_the_payment_links_public_ipv4_rule(web, crm, forwarded, want):
    web.get(f"/o/{F.OPEN}", headers={"X-Forwarded-For": forwarded})
    web.post(f"/o/{F.OPEN}/pay", data={}, headers={"X-Forwarded-For": forwarded})

    assert _calls(crm, "get")[0]["client_ip"] == want
    assert _calls(crm, "pay")[0]["client_ip"] == want


def test_client_ip_comes_from_the_engines_payment_link_helper(web, crm, monkeypatch):
    """The same function object the payment link uses, not a copy of its rule."""
    import lo_custom_offers  # noqa: F401

    engine = flask_app.config["LO_ENGINE"]
    assert engine["payment_link_client_ip"].__name__ == "_payment_link_client_ip"
    gate = flask_app.view_functions["custom_offer_pay"]
    cells = [c.cell_contents for c in (gate.__closure__ or ()) if callable(getattr(c, "cell_contents", None))]
    holder = next(f for f in cells if getattr(f, "__name__", "") == "_customer")
    assert engine["payment_link_client_ip"] in [c.cell_contents for c in holder.__closure__]


@pytest.mark.parametrize("host, want", [
    ("www1.lottosonline.com", "https://www1.lottosonline.com/o/{c}/done"),
    ("lottosonline.com", "https://lottosonline.com/o/{c}/done"),
    ("localhost:8010", "http://localhost:8010/o/{c}/done"),
])
def test_the_processor_sends_the_customer_back_to_the_site_they_came_from(web, crm, host, want):
    web.post(f"/o/{F.OPEN}/pay", data={}, base_url=f"http://{host}")

    assert _calls(crm, "pay")[0]["return_url"] == want.format(c=F.OPEN)


def test_pay_reuses_the_pages_request_id(web, crm):
    web.get(f"/o/{F.OPEN}")
    rid = _calls(crm, "get")[0]["request_id"]

    web.post(f"/o/{F.OPEN}/pay", data={"rid": rid})

    assert _calls(crm, "pay")[0]["request_id"] == rid


def test_a_refused_payment_shows_the_crms_words_and_the_reference(web, crm):
    resp = web.post(f"/o/{F.REFUSED}/pay", data={})
    body = resp.get_data(as_text=True)

    rid = _calls(crm, "pay")[0]["request_id"]
    assert "We can&#39;t take a payment from your country with this offer." in body
    assert f"Reference: {rid[:6].upper()}" in body
    assert 'id="paybtn"' in body  # the offer is still there to pay


def test_paying_an_offer_already_paid_says_so(web):
    body = web.post(f"/o/{F.PAID}/pay", data={}).get_data(as_text=True)

    assert _h1(body) == "Payment received, thank you."


def test_a_processor_form_is_posted_from_the_bare_page_not_the_site_layout(web):
    body = web.post(f"/o/{F.FORM_POST}/pay", data={}).get_data(as_text=True)

    assert '<form id="handover" method="get" action="https://www.lottosonline.com/o/' in body or 'id="handover"' in body
    assert 'name="fake" value="1"' in body
    assert "googletagmanager" not in body and "lePages" not in body


def test_pay_with_nothing_to_pay_with_is_an_error_with_a_reference(web, crm, monkeypatch):
    monkeypatch.setattr(crm, "pay", lambda *a, **k: {"ok": True, "next": {"mode": "options"}})

    resp = web.post(f"/o/{F.OPEN}/pay", data={})

    assert resp.status_code == 502
    assert "You have not been charged." in resp.get_data(as_text=True)
    assert "Reference: " in resp.get_data(as_text=True)


def test_pay_timing_out_is_an_error_page_and_is_recorded_later(web, crm, monkeypatch):
    def slow(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(crm, "pay", slow)
    resp = web.post(f"/o/{F.OPEN}/pay", data={})
    assert resp.status_code == 503

    web.get(f"/o/{F.OPEN}")
    (kept,) = [e for e in crm.events if e["event"] == "crm_unreachable"]
    assert kept["detail"]["call"] == "5.2"


def test_the_redirect_is_recorded_with_the_host_only(web, crm, monkeypatch):
    monkeypatch.setattr(crm, "pay", lambda *a, **k: {"ok": True, "next": {
        "redirect_url": "https://pay.example.com/hpp?session=SECRET&code=" + F.OPEN}})

    web.post(f"/o/{F.OPEN}/pay", data={})

    (redirected,) = [e for e in crm.events if e["event"] == "redirected"]
    assert redirected["detail"] == {"host": "pay.example.com"}


# --------------------------------------------------------------------------- the return page
def test_the_done_page_checks_with_the_crm_until_the_bank_answers(web, crm):
    web.post(f"/o/{F.OPEN}/pay", data={})

    body = web.get(f"/o/{F.OPEN}/done").get_data(as_text=True)
    assert "Checking your payment with your bank…" in body
    assert "<title>Lottos Online</title>" in body
    assert _calls(crm, "get")[-1]["view"] == "done"

    states = [web.get(f"/o/{F.OPEN}/status?rid=x").get_json()["state"] for _ in range(3)]
    assert states == ["in_progress", "succeeded", "succeeded"]
    assert {c["view"] for c in _calls(crm, "get")[1:]} == {"poll"}


def test_the_done_page_says_thank_you_once_paid(web):
    body = web.get(f"/o/{F.PAID}/done").get_data(as_text=True)

    assert "<title>Payment received | Lottos Online</title>" in body

    assert _h1(body) == "Payment received, thank you."
    assert "Your agent will confirm your tickets shortly." in body


def test_a_decline_says_why_that_nothing_was_charged_and_offers_another_go(web):
    body = web.get(f"/o/{F.DECLINED}/done").get_data(as_text=True)

    assert "Your bank declined the payment because of insufficient funds. You have not been charged." in body
    assert _markup(body).count("You have not been charged.") == 1
    assert 'href="/o/' + F.DECLINED + '">Try again</a>' in body
    assert "Reference: " in body and "support@lottosonline.com" in body


def test_a_technical_failure_that_cannot_be_retried_offers_a_call_instead(web):
    body = web.get(f"/o/{F.TECH_FAIL}/done").get_data(as_text=True)

    assert "Something went wrong connecting to the payment provider." in body
    assert "Try again</a>" not in body
    assert "Ask us to call you" in body


def test_the_processors_return_parameters_are_never_believed(web):
    body = web.get(f"/o/{F.DECLINED}/done?status=success&result=APPROVED").get_data(as_text=True)

    assert "insufficient funds" in body
    assert "Payment received" not in body


def test_coming_back_without_paying_says_nothing_was_charged(web):
    body = web.get(f"/o/{F.OPEN}/done").get_data(as_text=True)

    assert _h1(body) == "Your payment wasn't completed."
    assert "You have not been charged." in body


def test_polling_is_capped_per_page_load(web):
    answers = [web.get(f"/o/{F.OPEN}/status?rid=00000000-0000-4000-8000-000000000001").status_code for _ in range(27)]

    assert answers[:25] == [200] * 25
    assert answers[25:] == [429, 429]


# --------------------------------------------------------------------------- tracking
def test_the_tracking_relay_keeps_only_known_events_and_fields(web, crm):
    beacon = {"request_id": "00000000-0000-4000-8000-0000000000aa", "events": [
        {"event": "pay_clicked", "at": "2026-11-12T14:03:22.120Z", "detail": {"ms": 812, "card": "4111111111111111"}},
        {"event": "page_rendered", "detail": {"ms": 400, "in_app": "WhatsApp", "email": "a@b.c"}},
        {"event": "paid", "detail": {}},
        {"event": "drop_tables", "detail": {"x": 1}},
        "nonsense",
    ]}

    resp = web.post(f"/o/{F.OPEN}/t", data=json.dumps(beacon), content_type="text/plain",
                    headers={**PUBLIC_IP, "User-Agent": "Phone/1.0"})

    assert resp.status_code == 204
    assert [e["event"] for e in crm.events] == ["pay_clicked", "page_rendered"]
    assert crm.events[0]["detail"] == {"ms": 812}
    assert crm.events[1]["detail"] == {"ms": 400, "in_app": "WhatsApp"}
    (relay,) = _calls(crm, "events")
    assert relay["client_ip"] == "86.48.8.213" and relay["user_agent"] == "Phone/1.0"
    assert relay["request_id"] == beacon["request_id"]


@pytest.mark.parametrize("body", ["", "not json", "[]", json.dumps({"events": "x"}), "x" * 40000],
                         ids=["empty", "text", "list", "events-not-a-list", "too-big"])
def test_a_broken_beacon_is_dropped_quietly(web, crm, body):
    assert web.post(f"/o/{F.OPEN}/t", data=body, content_type="text/plain").status_code == 204
    assert crm.events == []


def test_events_that_cannot_reach_the_crm_wait_and_go_later(web, crm):
    beacon = json.dumps({"events": [{"event": "left_page", "detail": {"last_state": "pay_clicked"}}]})
    crm.unreachable = True
    web.post(f"/o/{F.OPEN}/t", data=beacon, content_type="text/plain")
    assert crm.events == []

    crm.unreachable = False
    web.get(f"/o/{F.OPEN}")

    assert [e["event"] for e in crm.events] == ["left_page"]


def test_the_page_script_reports_what_the_spec_asks_and_reads_no_form_or_query():
    html = TEMPLATE.read_text(encoding="utf-8")
    script = html[html.index("<script>"): html.index("</script>")]

    for event in ("page_rendered", "js_error", "pay_clicked", "left_page", "callback_requested"):
        assert f'"{event}"' in script
    assert "sendBeacon" in script and "pagehide" in script and "errs>=5" in script
    for forbidden in ("location.search", "location.href", "URLSearchParams", ".value", "FormData"):
        assert forbidden not in script
    assert len(script.encode()) < 6 * 1024


def test_ask_us_to_call_you_works_without_javascript(web, crm):
    resp = web.post(f"/o/{F.EXPIRED}/call", data={"rid": "x", "state": "unavailable"})

    assert _h1(resp.get_data(as_text=True)) == "Thanks, we'll call you shortly."
    (event,) = crm.events
    assert event["event"] == "callback_requested" and event["detail"] == {"state": "unavailable"}


# --------------------------------------------------------------------------- rate limits
def test_thirty_a_minute_per_ip(web):
    answers = [web.get(f"/o/{F.OPEN}", headers=PUBLIC_IP).status_code for _ in range(31)]

    assert answers[:30] == [200] * 30
    assert answers[30] == 429


def test_unknown_codes_count_double(web):
    answers = [web.get("/o/UnknownCode00000000000", headers=PUBLIC_IP).status_code for _ in range(16)]

    assert answers[:15] == [404] * 15
    assert answers[15] == 429


def test_the_limit_is_per_ip(web):
    for _ in range(30):
        web.get(f"/o/{F.OPEN}", headers=PUBLIC_IP)

    assert web.get(f"/o/{F.OPEN}", headers={"X-Forwarded-For": "86.48.8.214"}).status_code == 200


# --------------------------------------------------------------------------- nothing else changed
def test_the_existing_payment_link_page_is_untouched(anon_client, stub_crm):
    resp = anon_client.get("/wallet/topup/pay?token=abc.def&mode=bitolo", follow_redirects=True)

    assert resp.status_code == 200
    assert "Complete Your Payment" in resp.get_data(as_text=True)
