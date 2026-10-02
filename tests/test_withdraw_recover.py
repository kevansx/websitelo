"""Withdraw winnings (lo_withdraw.py), abandoned-checkout recovery (lo_recover.py), contacts and consent (lo_mail.py)."""
from datetime import datetime, timedelta, timezone

import pytest

import lo_mail
import lo_recover
from crm_api import CRMClient

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
CART = [{"kind": "single", "product_code": "LO-USPOW", "game_code": "powerball", "game_name": "US Powerball",
         "lines": [{"main": "1,2,3,4,5", "powerball": 6}]}]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)


def _outbox():
    box = lo_mail.outbox()
    return [p.read_text(encoding="utf-8") for p in sorted(box.glob("*.txt"))] if box.exists() else []


def _csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf_token"]


# ------------------------------------------------------------------ consent
def test_marketing_consent_comes_from_the_crm_customer():
    assert lo_mail.marketing_allowed({"notification": {"is_allow_marketing_email": True}})
    assert not lo_mail.marketing_allowed({"notification": {"is_allow_marketing_email": False}})
    assert not lo_mail.marketing_allowed({"email": "a@b.c"})       # unknown means no


# ------------------------------------------------------------------ withdrawals
@pytest.fixture
def winnings(monkeypatch, stub_crm):
    monkeypatch.setattr(CRMClient, "wallet", lambda self, *a, **k: {"wallet": {"currency": "EUR", "winnings_cents": 4200}})


def test_withdrawals_are_off_until_the_business_decides(client, winnings):
    html = client.get("/account/withdraw").get_data(as_text=True)
    assert "€42.00" in html and "contact our support team" in html and 'name="amount"' not in html
    assert client.post("/account/withdraw", data={"csrf_token": _csrf(client), "amount": "10", "method": "bank",
                                                   "details": "x"}).status_code == 404
    assert _outbox() == []


def test_a_request_emails_support_and_moves_no_money(client, winnings, monkeypatch):
    monkeypatch.setenv("LO_WITHDRAWALS_ON", "1")
    monkeypatch.setenv("LO_WITHDRAWAL_DAYS", "5")
    calls = []
    monkeypatch.setattr(CRMClient, "_request", lambda self, m, path, *a, **k: calls.append((m, path)) or {})
    r = client.post("/account/withdraw", data={"csrf_token": _csrf(client), "amount": "30.00", "method": "bank",
                                                "details": "J Smith, IE00BANK0000000000"})
    html = r.get_data(as_text=True)
    assert "Request received." in html and "within 5 working days" in html
    mails = _outbox()
    assert any(m.startswith("To: support@lottosonline.com") and "Amount: €30.00" in m and "Customer id: 1" in m for m in mails)
    assert any("We'll pay it within 5 working days" in m for m in mails)
    assert not [c for c in calls if c[0] in ("POST", "PATCH", "PUT")]        # nothing debited or paid by the site


def test_cannot_withdraw_more_than_the_winnings(client, winnings, monkeypatch):
    monkeypatch.setenv("LO_WITHDRAWALS_ON", "1")
    monkeypatch.setenv("LO_WITHDRAWAL_DAYS", "5")
    client.post("/account/withdraw", data={"csrf_token": _csrf(client), "amount": "50", "method": "bank", "details": "x"})
    assert _outbox() == []


# ------------------------------------------------------------------ abandoned checkout
def _run(now, *, jp_cutoff=NOW + timedelta(days=2), push_ids=(), closed=False):
    pushed = []
    jp = lambda g: {"cutoff_iso": jp_cutoff.isoformat(), "display": "€300 Million", "closed": closed} if jp_cutoff else None
    res = lo_recover.run(jackpot=jp, resume_url=lambda c: f"https://www.lottosonline.com/cart/resume/t{c}",
                         push=lambda ids, p: pushed.append((ids, p)) or {"sent": 1},
                         has_push=lambda c: c in push_ids, now=now)
    return res, pushed


def _consent(cid=1, ok=True):
    lo_mail.remember_contact({"id": cid, "email": "a@example.com", "notification": {"is_allow_marketing_email": ok}})


def test_30_minutes_then_24_hours_then_nothing():
    _consent()
    lo_recover.cart_seen(1, CART, now=NOW)
    assert _run(NOW + timedelta(minutes=20))[0]["first"] == 0
    assert _run(NOW + timedelta(minutes=31))[0]["first"] == 1
    assert _run(NOW + timedelta(hours=25))[0]["second"] == 1
    assert _run(NOW + timedelta(hours=60))[0] == {"first": 0, "second": 0, "skipped_closed": 0, "skipped_consent": 0}
    mails = _outbox()
    first = [m for m in mails if "still in your cart" in m]
    second = [m for m in mails if "last reminder" in m]
    assert len(mails) == 2 and len(first) == len(second) == 1
    assert "1 2 3 4 5 + 6" in first[0] and "/cart/resume/t1" in first[0]
    assert "€300 Million" in second[0]


def test_a_purchase_stops_the_reminders():
    _consent()
    lo_recover.cart_seen(1, CART, now=NOW)
    lo_recover.order_completed(1, now=NOW + timedelta(minutes=10))
    assert _run(NOW + timedelta(hours=1))[0]["first"] == 0 and _outbox() == []


def test_no_marketing_consent_no_email():
    _consent(ok=False)
    lo_recover.cart_seen(1, CART, now=NOW)
    assert _run(NOW + timedelta(minutes=31))[0]["skipped_consent"] == 1 and _outbox() == []


def test_push_subscribers_get_the_30_minute_reminder_by_push():
    _consent()
    lo_recover.cart_seen(1, CART, now=NOW)
    res, pushed = _run(NOW + timedelta(minutes=31), push_ids=(1,))
    assert pushed and pushed[0][0] == [1] and _outbox() == []


def test_never_a_reminder_for_a_closed_draw():
    _consent()
    lo_recover.cart_seen(1, CART, now=NOW)
    _run(NOW + timedelta(minutes=31))
    res, _ = _run(NOW + timedelta(hours=25), jp_cutoff=NOW + timedelta(hours=10))     # that draw closed already
    assert res["second"] == 0 and res["skipped_closed"] == 1 and len(_outbox()) == 1


def test_resume_link_puts_the_lines_back(client, stub_crm):
    with client.session_transaction() as s:
        cid = int(s["customer"]["id"])
    lo_recover.cart_seen(cid, CART, now=NOW)
    from itsdangerous import URLSafeTimedSerializer
    token = URLSafeTimedSerializer(client.application.secret_key, salt="lo-cart-resume").dumps({"c": cid})
    with client.session_transaction() as s:
        s["cart_items"] = []
    r = client.get(f"/cart/resume/{token}")
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s["cart_items"][0]["product_code"] == "LO-USPOW"
    assert client.get("/cart/resume/forged").status_code == 302


def test_jackpot_alerts_email_customers_without_push(client, stub_crm, monkeypatch):
    _consent(cid=5)
    deliver = client.application.config["LO_ALERTS_DELIVER"]
    monkeypatch.setenv("LO_VAPID_PUBLIC_KEY", "x")
    monkeypatch.setenv("LO_VAPID_PRIVATE_KEY", "y")
    res = deliver([5], {"title": "EuroMillions: €40 Million", "body": "The jackpot you follow has passed €34 Million.",
                        "url": "/lottery-tickets/euromillions", "tag": "t"})
    assert res.get("emailed") == 1 and "EuroMillions: €40 Million" in _outbox()[0]
