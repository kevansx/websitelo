"""The emails the old site sent, now sent by the new one, and the sign-up journey around the gift packs
(lo_txmail.py, lo_journey.py; Joey, 19 Oct 2026). Plus the Denmark rule, which nothing enforced until now."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import lo_journey
import lo_mail
import lo_packs
import lo_txmail
from crm_api import CRMClient
from test_cart_checkout import VALID_ADD

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
NEW = {"id": 501, "email": "new@example.com", "first_name": "Nia", "country": "IN",
       "notification": {"is_allow_marketing_email": True}}
ACCOUNT_FORM = {"title": "Ms", "first_name": "Nia", "last_name": "Test", "email": "new@example.com",
                "password": "Str0ngPassw0rd!", "currency": "EUR", "country": "IN", "accept_terms": "1"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)


def _outbox() -> list[str]:
    box = lo_mail.outbox()
    return [p.read_text(encoding="utf-8") for p in sorted(box.glob("*.txt"))] if box.exists() else []


def _subjects() -> list[str]:
    return [m.split("Subject: ", 1)[1].split("\n", 1)[0] for m in _outbox()]


def _no_jackpots(code):
    return None


# ------------------------------------------------------------------ Denmark
def test_a_danish_account_is_never_emailed():
    assert lo_mail.send_template("dk@example.com", "welcome", {"first_name": "A"}, country="DK") == "blocked"
    assert _outbox() == []


def test_a_danish_address_is_recognised_from_the_contact_record():
    """The scheduled jobs only have an address: the country remembered with it decides."""
    lo_mail.remember_contact({"id": 9, "email": "Dk@Example.com", "country": "DK"})
    assert lo_mail.send_template("dk@example.com", "jackpot_alert", {"lottery_name": "X"}) == "blocked"
    assert lo_mail.marketing_contacts() == []
    assert _outbox() == []


def test_everyone_else_is_still_emailed():
    assert lo_mail.send_template("ie@example.com", "welcome", {"first_name": "A"}, country="IE") == "outbox"


# ------------------------------------------------------------------ sign-up
def test_signing_up_sends_the_welcome_email(anon_client, stub_crm):
    anon_client.post("/create-account", data=ACCOUNT_FORM)
    assert _subjects() == ["Welcome to LottosOnline"]


def test_the_sign_up_marketing_tick_is_saved_to_the_crm(anon_client, stub_crm, monkeypatch):
    """The form always asked; nothing saved the answer."""
    sent = []
    monkeypatch.setattr(CRMClient, "customer_update", lambda self, token, payload: sent.append(payload) or {})
    anon_client.post("/create-account", data={**ACCOUNT_FORM, "marketing_opt_in": "on"})
    assert sent and sent[0]["notification"]["is_allow_marketing_email"] is True


def test_no_tick_saves_nothing(anon_client, stub_crm, monkeypatch):
    sent = []
    monkeypatch.setattr(CRMClient, "customer_update", lambda self, token, payload: sent.append(payload) or {})
    anon_client.post("/create-account", data=ACCOUNT_FORM)
    assert sent == []


def test_the_welcome_email_goes_once():
    lo_txmail.send_welcome(NEW)
    lo_txmail.send_welcome(NEW)
    assert len(_outbox()) == 1


# ------------------------------------------------------------------ order confirmation
def test_an_order_sends_its_confirmation(client, stub_crm):
    client.post("/cart/add", data=VALID_ADD)
    client.post("/checkout")
    subjects = _subjects()
    assert any(s.startswith("Your order confirmation: ") for s in subjects), subjects


def test_the_confirmation_carries_the_tickets_and_the_total():
    items = [{"kind": "single", "product_code": "LO-USPOW-3W", "game_code": "powerball", "game_name": "US Powerball",
              "ticket_mode": "multi_draw", "lines": [{"main": "1,2,3,4,5", "powerball": "6"}]}]
    order = {"id": 77, "currency": "EUR", "total_cents": 1170,
             "tickets": [{"game_code": "powerball", "draw_date": "2026-10-21T03:00:00Z"}]}
    lo_txmail.send_order_confirmation(NEW, order_id=77, items=items, order=order)
    mail = _outbox()[0]
    assert "Subject: Your order confirmation: 77" in mail
    assert "€11.70" in mail and "US Powerball" in mail and "3 weeks of draws from Wed 21 Oct 2026" in mail


def test_a_pack_earned_by_the_order_is_in_its_confirmation():
    pack = {"pack_id": "abc123", "state": "sealed", "tier": "premium"}
    lo_txmail.send_order_confirmation(NEW, order_id=78, items=[], pack=pack)
    page = next(lo_mail.outbox().glob("*.html")).read_text(encoding="utf-8")
    assert "/packs/abc123" in page and "gold one" in page


def test_line_balls_put_the_main_numbers_first():
    assert lo_txmail.line_balls({"main": "4,12", "powerball": "7"}) == [{"n": 4}, {"n": 12}, {"n": 7, "bonus": True}]


# ------------------------------------------------------------------ the journey: nudges
def test_a_sign_up_with_no_order_is_nudged_on_day_1_and_day_5():
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW)
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=12))
    assert _outbox() == []
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=1, hours=1))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=2))
    assert _subjects() == ["Your first order comes with a gift pack"]
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=5, hours=1))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=6))
    assert _subjects()[-1] == "Your first gift pack is still waiting for you" and len(_outbox()) == 2


def test_no_nudge_without_marketing_consent():
    quiet = {**NEW, "notification": {"is_allow_marketing_email": False}}
    lo_mail.remember_contact(quiet)
    lo_journey.on_registered(quiet, now=NOW)
    out = lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=1, hours=1))
    assert _outbox() == [] and out["skipped_consent"] == 1


def test_ordering_stops_the_nudges():
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW)
    lo_journey.on_order(NEW, order_id=1, items=[], now=NOW + timedelta(hours=2))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=1, hours=1))
    assert not any("gift pack" in s for s in _subjects())


def test_the_nudge_features_an_open_draw():
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW)
    jp = {"display": "€300 Million", "cutoff_iso": (NOW + timedelta(days=3)).isoformat()}
    lo_journey.run(jackpot=lambda code: jp if code == "powerball" else None, now=NOW + timedelta(days=1, hours=1))
    assert "€300 Million" in _outbox()[0] and "US Powerball" in _outbox()[0]


# ------------------------------------------------------------------ the journey: day 2
def _first_order(draw_in: timedelta):
    lo_mail.remember_contact(NEW)
    lo_journey.on_registered(NEW, now=NOW)
    order = {"tickets": [{"game_code": "powerball", "draw_date": (NOW + draw_in).isoformat()}]}
    lo_journey.on_order(NEW, order_id=11, items=[{"game_code": "powerball", "game_name": "US Powerball"}],
                        order=order, now=NOW)


def test_the_day_after_the_first_order_says_which_draw_they_are_in():
    _first_order(timedelta(days=3))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=21))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=30))
    day2 = [s for s in _subjects() if s.startswith("You're in")]
    assert day2 == ["You're in the US Powerball draw on Thu 22 Oct 2026"]


def test_never_about_a_draw_that_has_happened():
    _first_order(timedelta(hours=10))
    out = lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=21))
    assert not any(s.startswith("You're in") for s in _subjects()) and out["skipped_late"] == 1


def test_day_2_does_not_need_marketing_consent():
    """It is about their order, not a promotion."""
    quiet = {**NEW, "notification": {"is_allow_marketing_email": False}}
    lo_mail.remember_contact(quiet)
    lo_journey.on_registered(quiet, now=NOW)
    lo_journey.on_order(quiet, order_id=12, items=[{"game_code": "powerball"}],
                        order={"tickets": [{"game_code": "powerball", "draw_date": (NOW + timedelta(days=3)).isoformat()}]},
                        now=NOW)
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=21))
    assert any(s.startswith("You're in") for s in _subjects())


def test_a_customer_from_the_old_site_gets_no_day_2():
    """Day 2 is for the first order after signing up here, not for every existing customer's next order."""
    lo_mail.remember_contact(NEW)
    lo_journey.on_order(NEW, order_id=13, items=[{"game_code": "powerball"}], now=NOW)
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(hours=21))
    assert _outbox() == []


# ------------------------------------------------------------------ the journey: gift packs
def _sealed_pack(earned: datetime, tier: str = "standard") -> str:
    with lo_packs._db() as c:
        c.execute("""INSERT INTO packs (pack_id, customer_id, type, tier, state, earned_at, expires_at, idempotency_key,
                     order_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                  ("p1", NEW["id"], "first_play", tier, "sealed", lo_packs._iso(earned),
                   lo_packs._iso(earned + timedelta(days=14)), "pack-p1", "11"))
    return "p1"


def test_a_sealed_pack_is_reminded_on_day_3_7_and_10():
    lo_mail.remember_contact(NEW)
    _sealed_pack(NOW)
    for d in (1, 3, 4, 7, 8, 10, 11, 13):
        lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=d, hours=1))
    # outbox files written in the same second sort by name, not by time: compare what was sent, not the order
    assert sorted(_subjects()) == ["Still sealed: Your gift pack is waiting", "Your gift pack is waiting",
                                   "Your gift pack is waiting"]


def test_a_missed_job_sends_one_reminder_not_three():
    lo_mail.remember_contact(NEW)
    _sealed_pack(NOW)
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=10, hours=1))
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=11))
    assert len(_outbox()) == 1


def test_day_10_is_skipped_for_someone_who_has_ordered_since():
    lo_mail.remember_contact(NEW)
    _sealed_pack(NOW)
    lo_journey.on_order(NEW, order_id=14, items=[], now=NOW + timedelta(days=8))
    out = lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=10, hours=1))
    assert _outbox() == [] and out["skipped_ordered"] == 1


def test_pack_reminders_need_marketing_consent():
    lo_mail.remember_contact({**NEW, "notification": {"is_allow_marketing_email": False}})
    _sealed_pack(NOW)
    lo_journey.run(jackpot=_no_jackpots, now=NOW + timedelta(days=3, hours=1))
    assert _outbox() == []


def test_a_pack_that_opens_itself_says_what_is_inside():
    lo_mail.remember_contact(NEW)
    pack = {"pack_id": "p9", "customer_id": NEW["id"],
            "gift": {"card": {"title": "BonoLoto", "sub": "5 free lines", "expiry": "Entered in the next draw"}}}
    lo_journey.pack_opened_email(pack)
    lo_journey.pack_opened_email(pack)
    assert _subjects() == ["We opened your gift pack: 5 free lines on BonoLoto"]


# ------------------------------------------------------------------ funds added
def test_a_top_up_on_its_own_confirms_the_funds(client, stub_crm, monkeypatch):
    monkeypatch.setattr(CRMClient, "wallet_topup_status",
                        lambda self, token, intent_id: {"status": "succeeded", "intent": {"amount_cents": 2500}})
    client.get("/wallet/topup/success?intent_id=i-55")
    assert any(s.startswith("LottosOnline deposit confirmation: i-55") for s in _subjects())


def test_a_top_up_page_opened_by_hand_sends_nothing(client, stub_crm, monkeypatch):
    monkeypatch.setattr(CRMClient, "wallet_topup_status", lambda self, token, intent_id: {"status": "pending"})
    client.get("/wallet/topup/success?intent_id=i-56")
    assert not any("deposit" in s for s in _subjects())
