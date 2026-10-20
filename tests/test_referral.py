"""Refer a friend (lo_referral.py; Joey, 20 Oct 2026): a gift pack each on the friend's first order of €5 or more, no
cap on friends, safeguards against abuse instead."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import lo_mail
import lo_packs
import lo_referral

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
REFERRER = {"id": 10, "email": "sam@example.com", "first_name": "Sam", "country": "IE"}
ACCOUNT_FORM = {"title": "Ms", "first_name": "Nia", "last_name": "Test", "email": "new@example.com",
                "password": "Str0ngPassw0rd!", "currency": "EUR", "country": "IN", "accept_terms": "1"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)


def _subjects() -> list[str]:
    box = lo_mail.outbox()
    return sorted(p.read_text(encoding="utf-8").split("Subject: ", 1)[1].split("\n", 1)[0]
                  for p in box.glob("*.txt")) if box.exists() else []


def _referrer_code() -> str:
    lo_mail.remember_contact(REFERRER)
    return lo_referral.code_for(REFERRER["id"], REFERRER["first_name"])


def _friend(n: int = 1) -> dict:
    return {"id": 100 + n, "email": f"friend{n}@example.com", "first_name": f"Friend{n}", "country": "IN"}


def _signed_up(n: int = 1, ip: str | None = "203.0.113.9") -> dict:
    f = _friend(n)
    lo_mail.remember_contact(f)
    lo_referral.on_signup(f, _referrer_code(), ip, now=NOW)
    return f


# ------------------------------------------------------------------ the link
def test_the_refer_page_shows_the_customers_link(client, stub_crm):
    body = client.get("/account/refer").get_data(as_text=True)
    assert "/r/" in body and "first order of €5 or more" in body


def test_the_refer_page_needs_an_account(anon_client, stub_crm):
    assert "/login" in anon_client.get("/account/refer").headers["Location"]


def test_a_link_is_remembered_on_the_way_to_sign_up(anon_client, stub_crm):
    code = _referrer_code()
    resp = anon_client.get(f"/r/{code.lower()}")
    assert resp.headers["Location"].endswith("/create-account")
    with anon_client.session_transaction() as s:
        assert s["lo_ref"]["code"] == code


def test_an_unknown_code_is_ignored(anon_client, stub_crm):
    anon_client.get("/r/NOPE234")
    with anon_client.session_transaction() as s:
        assert "lo_ref" not in s


def test_signing_up_through_a_link_records_the_friend_and_sends_their_welcome(anon_client, stub_crm):
    code = _referrer_code()
    anon_client.get(f"/r/{code}")
    anon_client.post("/create-account", data=ACCOUNT_FORM)
    assert lo_referral.referrals_of(REFERRER["id"])
    assert _subjects() == ["Welcome to LottosOnline: Sam sent you"]


# ------------------------------------------------------------------ the reward
def test_a_first_order_under_5_euros_earns_nothing_yet():
    f = _signed_up()
    assert lo_referral.on_order(f["id"], order_id=1, total_cents=390, currency="EUR", now=NOW) == "too_small"
    assert lo_referral.get(f["id"])["status"] == "pending"


def test_a_first_order_of_5_euros_gives_both_a_gift_pack():
    f = _signed_up()
    assert lo_referral.on_order(f["id"], order_id=2, total_cents=500, currency="EUR", now=NOW) == "rewarded"
    for cid in (f["id"], REFERRER["id"]):
        packs = lo_packs.customer_packs(cid)["sealed"]
        assert len(packs) == 1 and packs[0]["type"] == "friend"
    assert _subjects() == ["Friend1 played: your gift pack is here", "Your friend gift pack is here"]


def test_the_reward_is_paid_once():
    f = _signed_up()
    lo_referral.on_order(f["id"], order_id=2, total_cents=900, currency="EUR", now=NOW)
    assert lo_referral.on_order(f["id"], order_id=3, total_cents=900, currency="EUR", now=NOW) == "already"
    assert len(lo_packs.customer_packs(REFERRER["id"])["sealed"]) == 1


def test_other_currencies_are_compared_in_euros():
    f = _signed_up()
    assert lo_referral.on_order(f["id"], order_id=2, total_cents=520, currency="USD", now=NOW) == "too_small"   # ~€4.78
    assert lo_referral.on_order(f["id"], order_id=3, total_cents=580, currency="USD", now=NOW) == "rewarded"    # ~€5.34


# ------------------------------------------------------------------ safeguards
def test_using_your_own_link_is_refused():
    code = _referrer_code()
    assert lo_referral.on_signup({**REFERRER, "id": 11, "email": "Sam+2@Example.com"}, code, None, now=NOW) is None


def test_gmail_dots_and_tags_count_as_the_same_address():
    assert lo_referral.normal_email("S.a.m+lotto@gmail.com") == lo_referral.normal_email("sam@googlemail.com")


def test_a_friend_on_the_referrers_connection_is_held_for_the_team():
    _referrer_code()
    lo_referral.note_ip(REFERRER["id"], "198.51.100.7", now=NOW)
    f = _signed_up(ip="198.51.100.7")
    assert lo_referral.get(f["id"])["status"] == "held"
    assert lo_referral.on_order(f["id"], order_id=5, total_cents=900, currency="EUR", now=NOW) == "held"
    assert lo_packs.customer_packs(REFERRER["id"])["sealed"] == []
    assert lo_referral.approve(f["id"], now=NOW)
    assert len(lo_packs.customer_packs(REFERRER["id"])["sealed"]) == 1


def test_no_cap_but_a_burst_is_held():
    """Five rewards in a week go straight through; the sixth waits for the team."""
    results = []
    for n in range(1, 7):
        f = _signed_up(n)
        results.append(lo_referral.on_order(f["id"], order_id=n, total_cents=800, currency="EUR", now=NOW))
    assert results == ["rewarded"] * 5 + ["held"]
    later = _signed_up(7)
    assert lo_referral.on_order(later["id"], order_id=7, total_cents=800, currency="EUR",
                                now=NOW + timedelta(days=8)) == "rewarded"


def test_a_refused_referral_never_pays():
    f = _signed_up()
    assert lo_referral.refuse(f["id"])
    assert lo_referral.on_order(f["id"], order_id=2, total_cents=900, currency="EUR", now=NOW) == "none"


# ------------------------------------------------------------------ invitations
def test_inviting_a_friend_by_email():
    _referrer_code()
    assert lo_referral.invite(REFERRER["id"], "Sam", "pal@example.com", "Fancy a go?", now=NOW) == "sent"
    assert _subjects() == ["Sam is thinking of you"]


def test_invitations_are_limited_per_day_and_checked():
    _referrer_code()
    assert lo_referral.invite(REFERRER["id"], "Sam", "not-an-email", None, now=NOW) == "bad_email"
    assert lo_referral.invite(REFERRER["id"], "Sam", "SAM@example.com", None, now=NOW) == "self"
    sent = [lo_referral.invite(REFERRER["id"], "Sam", f"p{i}@example.com", None, now=NOW) for i in range(11)]
    assert sent.count("sent") == 10 and sent[-1] == "limit"
