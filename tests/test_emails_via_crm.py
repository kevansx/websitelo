"""The 13 emails that move off the website (lo_crm_emails.py; plan of 18 Nov 2026, section 4).

Switch off: the website sends as before. Switch on: 11 are posted as email_requested events (the CRM or the
Marketing Module sends them), the CRM's own two are neither sent nor posted, and a test fire on www1 runs the real
job for one test account."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import lo_crm_emails
import lo_journey
import lo_mail
import lo_packs
import lo_recover
import lo_referral
import lo_txmail
from app import app as flask_app
from crm_api import CRMClient

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
NEW = {"id": 501, "email": "new@example.com", "first_name": "Nia", "country": "IN",
       "notification": {"is_allow_marketing_email": True}}
WWW1 = "https://www1.lottosonline.com"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("LO_EMAILS_VIA_CRM", raising=False)
    monkeypatch.delenv("LO_TEST_CUSTOMER_IDS", raising=False)


@pytest.fixture
def posted(monkeypatch):
    """Every event the website posts to the CRM, in order."""
    out: list[dict] = []
    monkeypatch.setattr(lo_crm_emails, "_post", lambda payload: out.append(payload))
    return out


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("LO_EMAILS_VIA_CRM", "1")


def _outbox() -> list[str]:
    box = lo_mail.outbox()
    return [p.read_text(encoding="utf-8") for p in sorted(box.glob("*.txt"))] if box.exists() else []


def _no_jackpots(code):
    return None


# ------------------------------------------------------------------ the switch
def test_the_switch_is_off_in_env_example():
    text = (Path(__file__).resolve().parents[1] / "env.example").read_text(encoding="utf-8")
    assert "\nLO_EMAILS_VIA_CRM=0\n" in text and "\nLO_TEST_CUSTOMER_IDS=\n" in text


def test_off_the_website_sends_its_own_copy_and_posts_nothing(posted):
    lo_mail.remember_contact(NEW)
    assert lo_mail.send_template("new@example.com", "pack_waiting", {"final": False}, customer_id=501) == "outbox"
    assert len(_outbox()) == 1 and posted == []


def test_the_plan_lists_eleven_posted_and_two_crm_own():
    assert len(lo_crm_emails.POSTED) == 11 and set(lo_crm_emails.CRM_OWN) == {"welcome_friend", "homescreen_free_line"}
    assert {k for k, a in lo_crm_emails.POSTED.items() if a == "marketing"} == {
        "jackpot_alert", "cart_reminder", "cart_last_call", "first_order_nudge", "pack_waiting"}
    assert lo_crm_emails.POSTED["withdrawal_request_staff"] == "staff"
    assert lo_crm_emails.POSTED["refer_friend_invite"] == "invite"
    import lo_emails
    assert set(lo_crm_emails.POSTED) | set(lo_crm_emails.CRM_OWN) == set(lo_emails.WEBSITE_EVENTS)


# ------------------------------------------------------------------ on: the event
def test_on_every_one_of_the_eleven_is_posted_not_sent(on, posted):
    lo_mail.remember_contact(NEW)
    for key in lo_crm_emails.POSTED:
        assert lo_mail.send_template("new@example.com", key, {"first_name": "Nia"}, customer_id=501,
                                     unique=f"u-{key}") == "requested"
    assert _outbox() == []
    assert [e["metadata"]["template"] for e in posted] == list(lo_crm_emails.POSTED)
    for e in posted:
        key = e["metadata"]["template"]
        assert e["event_type"] == "email_requested" and e["customer_id"] == 501
        assert e["event_id"] == f"web:lottosonline:email_requested:{key}:u-{key}"
        assert e["metadata"]["audience"] == lo_crm_emails.POSTED[key]
        assert e["occurred_at"].endswith("Z")


def test_the_customer_address_is_never_in_the_event(on, posted):
    lo_mail.send_template("support@lottosonline.com", "withdrawal_request_staff",
                          {"reference": "W7", "customer_id": 1, "customer_email": "x@example.com", "amount": "€30.00"},
                          customer_id=1, unique="W7")
    data = posted[0]["metadata"]["data"]
    assert "customer_email" not in data and data["reference"] == "W7"
    assert "x@example.com" not in str(posted[0]) and "to" not in posted[0]["metadata"]


def test_the_invite_names_the_friend_in_metadata_to(on, posted):
    lo_mail.remember_contact(NEW)
    assert lo_referral.invite(501, "Nia", "friend@example.com", "Join me", now=NOW) == "sent"
    e = posted[0]
    assert e["metadata"]["template"] == "refer_friend_invite" and e["metadata"]["to"] == "friend@example.com"
    assert e["customer_id"] == 501 and e["metadata"]["audience"] == "invite"
    assert "friend@example.com" not in str(e["metadata"]["data"])


def test_the_crm_own_two_are_neither_sent_nor_posted(on, posted):
    assert lo_txmail.send_welcome_friend(NEW, referrer_first_name="Sam") == "crm"
    assert lo_mail.send_template("new@example.com", "homescreen_free_line", {}, customer_id=501) == "crm"
    assert posted == [] and _outbox() == []


def test_a_danish_customer_is_never_asked_for(on, posted):
    assert lo_mail.send_template("dk@example.com", "pack_waiting", {}, country="DK", customer_id=9) == "blocked"
    assert posted == []


def test_the_staff_copy_goes_whatever_the_country(on, posted):
    lo_mail.remember_contact({"id": 9, "email": "dk@example.com", "country": "DK"})
    assert lo_mail.send_template("support@lottosonline.com", "withdrawal_request_staff", {"reference": "W9"},
                                 country="DK", customer_id=9, unique="W9") == "requested"
    assert len(posted) == 1


def test_one_event_id_is_posted_once(on, posted):
    args = ("new@example.com", "pack_opened", {"gift_title": "x"})
    assert lo_mail.send_template(*args, customer_id=501, unique="p1") == "requested"
    assert lo_mail.send_template(*args, customer_id=501, unique="p1") == "duplicate"
    assert len(posted) == 1


def test_a_post_the_crm_did_not_take_is_posted_again_with_the_same_event_id(on, monkeypatch):
    def down(payload):
        raise RuntimeError("CRM unavailable")
    monkeypatch.setattr(lo_crm_emails, "_post", down)
    assert lo_mail.send_template("new@example.com", "pack_opened", {"gift_title": "x"}, customer_id=501,
                                 unique="p2") == "queued"
    later: list[dict] = []
    monkeypatch.setattr(lo_crm_emails, "_post", lambda payload: later.append(payload))
    assert lo_crm_emails.retry_pending() == {"posted": 1, "still_pending": 0}
    assert later[0]["event_id"] == "web:lottosonline:email_requested:pack_opened:p2"
    assert lo_crm_emails.retry_pending() == {"posted": 0, "still_pending": 0}


def test_the_post_uses_the_service_key_and_no_customer_token(on, monkeypatch):
    seen = []
    monkeypatch.setattr(CRMClient, "_request", lambda self, m, path, **k: seen.append((m, path, k)) or {})
    with flask_app.test_request_context("/"):
        lo_mail.send_template("new@example.com", "pack_opened", {}, customer_id=501, unique="p3")
    (m, path, k), = seen
    assert (m, path) == ("POST", "/api/v1/marketing/events") and k["service_key"] is True and not k.get("token")
    assert k["json"]["event_id"].endswith(":pack_opened:p3")


# ------------------------------------------------------------------ on: the real jobs
def test_the_nudges_post_one_event_each_day(on, posted):
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW)
    for d in (1, 2, 5, 6):
        lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=d, hours=1))
    assert [e["event_id"].rsplit(":", 1)[1] for e in posted] == ["501-day1", "501-day5"]
    assert [e["metadata"]["data"]["final"] for e in posted] == [False, True]


def _sealed_pack(cid: int, earned: datetime, pid: str = "p1") -> None:
    with lo_packs._db() as c:
        c.execute("""INSERT INTO packs (pack_id, customer_id, type, tier, state, earned_at, expires_at, idempotency_key,
                     order_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (pid, cid, "first_play", "standard", "sealed", lo_packs._iso(earned),
                   lo_packs._iso(earned + timedelta(days=14)), f"pack-{pid}", "11"))


def test_pack_waiting_posts_days_3_7_and_10(on, posted):
    lo_mail.remember_contact(NEW)
    _sealed_pack(501, NOW)
    for d in (3, 7, 10):
        lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=d, hours=1))
    assert [e["event_id"].rsplit(":", 1)[1] for e in posted] == ["p1-day3", "p1-day7", "p1-day10"]
    assert posted[-1]["metadata"]["data"]["final"] is True


def test_the_cart_reminders_post_from_the_real_job(on, posted):
    lo_mail.remember_contact(NEW)
    cart = [{"game_code": "powerball", "game_name": "US Powerball", "lines": [{"main": "1,2,3,4,5", "powerball": 6}]}]
    lo_recover.cart_seen(501, cart, now=NOW)
    jp = lambda code: {"cutoff_iso": (NOW + timedelta(days=3)).isoformat(), "display": "$100 Million"}
    kw = dict(jackpot=jp, resume_url=lambda c: "https://www.lottosonline.com/cart/resume/x",
              push=lambda ids, p: {}, has_push=lambda c: False)
    lo_recover.run(now=NOW + timedelta(minutes=31), **kw)
    lo_recover.run(now=NOW + timedelta(hours=25), **kw)
    assert [e["metadata"]["template"] for e in posted] == ["cart_reminder", "cart_last_call"]
    assert posted[0]["event_id"].endswith("-30m") and posted[1]["event_id"].endswith("-24h")


# ------------------------------------------------------------------ test fire
@pytest.fixture
def tester(monkeypatch, client):
    monkeypatch.setenv("LO_EMAILS_VIA_CRM", "1")
    monkeypatch.setenv("LO_TEST_CUSTOMER_IDS", "1, 77")
    lo_mail.remember_contact({"id": 1, "email": "test@example.com", "notification": {"is_allow_marketing_email": True}})
    from conftest import TEST_CUSTOMER
    for base in (WWW1, "https://www.lottosonline.com", "https://lottosonline.com"):
        with client.session_transaction(base_url=base) as s:       # cookies are per host
            s["crm_token"], s["csrf_token"] = "test-token", "tok-test-fire"
            s["customer"] = {**TEST_CUSTOMER, "notification": {"is_allow_marketing_email": True}}   # marketing consent
    monkeypatch.setitem(flask_app.jinja_env.globals, "lo_jackpot",
                        lambda code: {"cutoff_iso": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                                      "display": "$100 Million"})
    return client


def _fire(client, name, base=WWW1):
    return client.post("/account/email-test-fire", data={"csrf_token": "tok-test-fire", "fire": name}, base_url=base)


def test_the_test_fire_is_not_there_while_the_switch_is_off(client, monkeypatch):
    monkeypatch.setenv("LO_TEST_CUSTOMER_IDS", "1")
    assert client.get("/account/email-test-fire", base_url=WWW1).status_code == 404


@pytest.mark.parametrize("base", ["https://www.lottosonline.com", "https://lottosonline.com"], ids=["www", "apex"])
def test_the_test_fire_is_never_on_the_production_site(tester, base):
    assert tester.get("/account/email-test-fire", base_url=base).status_code == 404
    assert _fire(tester, "nudge_day1", base=base).status_code == 404


def test_the_test_fire_is_for_test_accounts_only(tester, monkeypatch):
    monkeypatch.setenv("LO_TEST_CUSTOMER_IDS", "77")
    assert tester.get("/account/email-test-fire", base_url=WWW1).status_code == 404


def test_the_test_fire_needs_the_form_token(tester):
    r = tester.post("/account/email-test-fire", data={"fire": "nudge_day1"}, base_url=WWW1)
    assert r.status_code == 400


def test_firing_the_nudges_posts_what_the_timer_would(tester, posted):
    me = {"id": 1, "email": "test@example.com", "first_name": "Test", "notification": {"is_allow_marketing_email": True}}
    lo_journey.on_registered(me)
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW - timedelta(days=30))        # a real customer, long due: never touched
    assert tester.get("/account/email-test-fire", base_url=WWW1).status_code == 200
    assert _fire(tester, "nudge_day1").status_code == 200
    assert _fire(tester, "nudge_day5").status_code == 200
    assert [e["event_id"].rsplit(":", 1)[1] for e in posted] == ["1-day1", "1-day5"]
    assert all(e["customer_id"] == 1 for e in posted)
    page = tester.get("/account/email-test-fire", base_url=WWW1).get_data(as_text=True)
    assert "web:lottosonline:email_requested:first_order_nudge:1-day5" in page


def test_firing_the_pack_days_and_the_auto_open(tester, posted, monkeypatch):
    lo_journey.on_order({"id": 1}, order_id=5, items=[], now=datetime.now(timezone.utc))
    _sealed_pack(1, datetime.now(timezone.utc), pid="t1")
    _sealed_pack(501, NOW - timedelta(days=20), pid="real")              # someone else's pack stays as it is
    for d in (3, 7, 10):
        assert _fire(tester, f"pack_day{d}").status_code == 200
    assert [e["event_id"].rsplit(":", 1)[1] for e in posted] == ["t1-day3", "t1-day7", "t1-day10"]
    assert posted[-1]["metadata"]["data"]["final"] is True               # day 10 is not skipped as "ordered since"

    def fake_open(pid, **k):
        with lo_packs._db() as c:
            c.execute("UPDATE packs SET state='opened' WHERE pack_id=?", (pid,))
        return {"pack_id": pid, "customer_id": 1, "gift": {"card": {"title": "BonoLoto", "sub": "5 free lines"}}}
    monkeypatch.setattr(lo_packs, "open_pack", fake_open)
    assert _fire(tester, "pack_autoopen").status_code == 200
    assert posted[-1]["event_id"] == "web:lottosonline:email_requested:pack_opened:t1"
    with lo_packs._db() as c:
        assert c.execute("SELECT state FROM packs WHERE pack_id='real'").fetchone()[0] == "sealed"


def test_firing_the_cart_reminders(tester, posted):
    cart = [{"game_code": "powerball", "game_name": "US Powerball", "lines": [{"main": "1,2,3,4,5", "powerball": 6}]}]
    lo_recover.cart_seen(1, cart)
    page = _fire(tester, "cart_24h").get_data(as_text=True)
    assert "fire the 30-minute one" in page and posted == []
    _fire(tester, "cart_30m")
    _fire(tester, "cart_24h")
    assert [e["metadata"]["template"] for e in posted] == ["cart_reminder", "cart_last_call"]


def test_firing_the_day_after_the_first_order(tester, posted):
    me = {"id": 1, "email": "test@example.com", "first_name": "Test"}
    lo_journey.on_registered(me)
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    lo_journey.on_order(me, order_id=42, items=[{"game_code": "powerball", "game_name": "US Powerball"}],
                        order={"tickets": [{"game_code": "powerball", "draw_date": soon}]})
    assert _fire(tester, "day2").status_code == 200
    assert [e["event_id"].rsplit(":", 1)[1] for e in posted] == ["1-42"]
    assert posted[0]["metadata"]["template"] == "first_draw_day2"
