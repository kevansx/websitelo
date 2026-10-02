"""Weekly syndicate memberships (lo_members.py, brief 2 part 5) and the shared sender (lo_mail.py)."""
from datetime import datetime, timedelta, timezone

import pytest

import fake_crm
import lo_lotteries
import lo_mail
import lo_members
from crm_api import CRMClient, CRMError

GAMES = [fake_crm._game(l) for l in lo_lotteries.LOTTERIES if l.sells]


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.delenv("SMTP_HOST", raising=False)


@pytest.fixture
def crm(monkeypatch, client, stub_crm):
    """An in-memory CRM for memberships, with one saved card."""
    state = {"subs": [], "checkouts": []}
    eng = dict(client.application.config["LO_ENGINE"])
    eng["store_games_cached"] = lambda: GAMES
    monkeypatch.setitem(client.application.config, "LO_ENGINE", eng)
    monkeypatch.setattr(CRMClient, "wallet_cards", lambda self, *a, **k: {"cards": [{"id": 42, "brand": "Visa", "last4": "1111", "status": "active"}]})

    def checkout(self, token, payload, *a, **k):
        state["checkouts"].append(payload)
        sub = {"id": 77, "status": "active", "product_code": payload["items"][0]["product_code"], "game_code": "powerball",
               "next_amount_cents": 390, "next_charge_at": "2026-10-09T12:00:00Z"}
        state["subs"].append(sub)
        return {"order_id": 1, "subscription": sub}

    def act(status):
        def f(self, token, sid, *a, **k):
            s = next(x for x in state["subs"] if str(x["id"]) == str(sid))
            if status == "paused" and s["status"] != "active":
                raise CRMError("CRM HTTP 409: only an active membership can pause", status_code=409, payload={"message": "Only an active membership can pause."})
            s["status"] = status
            state.setdefault("calls", []).append((status, a))
            return {"subscription": dict(s)}
        return f

    monkeypatch.setattr(CRMClient, "checkout", checkout)
    monkeypatch.setattr(CRMClient, "subscriptions", lambda self, token: {"subscriptions": [dict(s) for s in state["subs"]]})
    monkeypatch.setattr(CRMClient, "subscription_pause", act("paused"))
    monkeypatch.setattr(CRMClient, "subscription_resume", act("active"))
    monkeypatch.setattr(CRMClient, "subscription_cancel", act("cancelled"))
    return state


def _csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf_token"]


def _outbox():
    box = lo_mail.outbox()
    return sorted(p.read_text(encoding="utf-8") for p in box.glob("*.txt")) if box.exists() else []


# ------------------------------------------------------------------ the share page
def test_share_page_states_the_terms_before_the_button(client, crm):
    html = client.get("/syndicates/us-powerball").get_data(as_text=True)
    form = html.split('id="join"')[1]
    assert "€3.90" in html and "1/40th of any prize" in html and "18+" in html
    assert form.index("renewing every week until you cancel") < form.index('type="submit"')
    assert "€99.99" not in html               # never price_in_base_cents for a subscription


def test_only_three_lotteries_have_a_share_page(client, crm):
    assert client.get("/syndicates/bonoloto").status_code == 404
    offers = lo_members.offers_for(GAMES, ["powerball", "megamillions", "euromillions-at", "bonoloto"])
    assert [(o["slug"], o["cents"]) for o in offers] == [("us-powerball", 390), ("mega-millions", 500), ("euromillions", 295)]


# ------------------------------------------------------------------ check 7: join, list, pause, resume, cancel
def test_check7_join_list_pause_resume_cancel(client, crm):
    token = _csrf(client)
    r = client.post("/syndicates/us-powerball/join", data={"csrf_token": token, "saved_card_id": "42", "agree": "1"})
    assert r.status_code == 302 and "/account/memberships" in r.headers["Location"]
    sent = crm["checkouts"][0]
    assert sent == {"saved_card_id": 42, "use_wins": False,
                    "items": [{"kind": "syndicate", "ticket_mode": "subscription", "product_code": "LO-USPOW-W", "shares": 1}]}
    page = client.get("/account/memberships").get_data(as_text=True)
    assert "US Powerball syndicate" in page and "€3.90" in page
    client.post("/account/memberships/77/pause", data={"csrf_token": token, "weeks": "4"})
    assert crm["subs"][0]["status"] == "paused" and crm["calls"][-1] == ("paused", (4,))
    client.post("/account/memberships/77/resume", data={"csrf_token": token})
    assert crm["subs"][0]["status"] == "active"
    client.post("/account/memberships/77/cancel", data={"csrf_token": token})
    assert crm["subs"][0]["status"] == "cancelled"
    mails = _outbox()
    assert any("You're in: US Powerball syndicate, €3.90 a week" in m for m in mails)
    assert any("is cancelled" in m and "Nothing more will be taken" in m for m in mails)


def test_join_needs_the_agreement_and_a_card(client, crm):
    token = _csrf(client)
    client.post("/syndicates/us-powerball/join", data={"csrf_token": token, "saved_card_id": "42"})
    client.post("/syndicates/us-powerball/join", data={"csrf_token": token, "agree": "1"})
    assert crm["checkouts"] == []


def test_pause_weeks_must_be_1_to_12(client, crm):
    token = _csrf(client)
    client.post("/syndicates/us-powerball/join", data={"csrf_token": token, "saved_card_id": "42", "agree": "1"})
    client.post("/account/memberships/77/pause", data={"csrf_token": token, "weeks": "13"})
    assert crm["subs"][0]["status"] == "active"


def test_past_due_shows_update_your_card(client, crm):
    crm["subs"].append({"id": 9, "status": "past_due", "game_code": "megamillions", "next_amount_cents": 500})
    html = client.get("/account/memberships").get_data(as_text=True)
    assert "Payment failed" in html and "Update your card" in html


# ------------------------------------------------------------------ emails
def test_renewal_reminder_receipt_and_failures_are_sent_once():
    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    due = {"id": 1, "status": "active", "email": "a@example.com", "product_code": "LO-USPOW-W", "next_amount_cents": 390,
           "next_charge_at": (now + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    failed = {"id": 2, "status": "past_due", "email": "b@example.com", "product_code": "LO-EUEUR-W", "next_amount_cents": 295,
              "last_charge_id": "c9", "last_charge_status": "declined", "last_charge_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}

    class C:
        def subscriptions_due(self, **k):
            return {"subscriptions": [due, failed]}

    first = lo_members.run_emails(C(), now)
    again = lo_members.run_emails(C(), now)
    later = lo_members.run_emails(C(), now + timedelta(days=2, hours=1))
    assert (first["renewal_due"], first["charge_failed"]) == (1, 1)
    assert (again["renewal_due"], again["charge_failed"]) == (0, 0)
    assert later["charge_failed"] == 1                       # the 2-day reminder
    mails = _outbox()
    assert any("renews tomorrow: €3.90" in m and "/account/memberships?cancel=1" in m for m in mails)
    assert any("could not take your EuroMillions syndicate payment" in m for m in mails)


def test_the_sender_writes_to_the_outbox_without_smtp():
    assert lo_mail.send("x@example.com", "Hi", "Body") == "outbox"
    assert "18+ only" in _outbox()[0]


def test_share_offer_shows_in_the_cart(client, crm, monkeypatch):
    with client.session_transaction() as s:
        s["cart_items"] = [{"kind": "single", "product_code": "LO-USPOW", "game_code": "powerball", "game_name": "Powerball",
                            "lines": [{"main": "1,2,3,4,5", "powerball": 6}] * 3, "options": {}}]
    html = client.get("/cart").get_data(as_text=True)
    assert "10 lines in every US Powerball draw for €3.90 a week" in html
