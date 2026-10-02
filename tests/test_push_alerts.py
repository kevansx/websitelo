"""Web push (lo_push.py) and jackpot alerts (lo_alerts.py)."""
import pytest

import lo_alerts
import lo_packs
import lo_push

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("LO_PACKS_DB_PATH", str(tmp_path / "packs.sqlite"))
    monkeypatch.setenv("LO_VAPID_PUBLIC_KEY", "BPUBLIC")
    monkeypatch.setenv("LO_VAPID_PRIVATE_KEY", "PRIVATE")


def _csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s.get("csrf_token")


def _cid(client):
    with client.session_transaction() as s:
        return int(s["customer"]["id"])


# ------------------------------------------------------------------ push
def test_subscribe_and_unsubscribe(client, stub_crm):
    token = _csrf(client)
    r = client.post("/push/subscribe", json=SUB, headers={"X-CSRF-Token": token})
    assert r.get_json() == {"ok": True} and lo_push.has_subscription(_cid(client))
    client.post("/push/unsubscribe", json={"endpoint": SUB["endpoint"]}, headers={"X-CSRF-Token": token})
    assert not lo_push.has_subscription(_cid(client))


def test_subscribe_needs_a_login(anon_client, stub_crm):
    assert anon_client.post("/push/subscribe", json=SUB, headers={"X-CSRF-Token": _csrf(anon_client)}).status_code == 401


def test_subscribe_needs_the_token_and_an_https_endpoint(client, stub_crm):
    assert client.post("/push/subscribe", json=SUB, headers={"X-CSRF-Token": "nope"}).status_code == 400
    bad = dict(SUB, endpoint="http://evil.example/x")
    assert client.post("/push/subscribe", json=bad, headers={"X-CSRF-Token": _csrf(client)}).status_code == 400


def test_the_private_key_never_reaches_the_browser(anon_client, stub_crm):
    page = anon_client.get("/").get_data(as_text=True)
    assert 'name="lo-push-key" content="BPUBLIC"' in page and "PRIVATE" not in page
    assert anon_client.get("/push/key").get_json() == {"enabled": True, "key": "BPUBLIC"}


def test_no_keys_no_push(anon_client, stub_crm, monkeypatch):
    monkeypatch.delenv("LO_VAPID_PRIVATE_KEY")
    assert 'name="lo-push-key"' not in anon_client.get("/").get_data(as_text=True)
    assert lo_push.send([1], {"title": "x"})["skipped"]


def test_send_drops_subscriptions_the_browser_has_retired():
    lo_push.subscribe(5, SUB)
    lo_push.subscribe(5, dict(SUB, endpoint="https://web.push.apple.com/gone"))

    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def fake(subscription_info, **k):
        if "apple" in subscription_info["endpoint"]:
            raise Gone()
    res = lo_push.send([5], {"title": "t"}, webpush=fake)
    assert res == {"sent": 1, "failed": 0, "removed": 1}


def test_service_worker_shows_and_opens_notifications(anon_client, stub_crm):
    sw = anon_client.get("/sw.js").get_data(as_text=True)
    assert "'push'" in sw and "notificationclick" in sw and "caches" not in sw


# ------------------------------------------------------------------ alerts
def _played(cid, game="euromillions"):
    lo_packs.on_order_placed(customer_id=cid, order_id=f"o-{game}", items=[{"game_code": game}])


def jp(amount, draw="2026-10-03", currency="EUR"):
    return {"amount": amount, "currency": currency, "draw_date": draw, "display": f"€{amount / 1e6:g} Million", "closed": False}


def test_played_lotteries_are_followed_at_twice_the_base():
    _played(7, "euromillions")
    alerts = lo_alerts.customer_alerts(7)
    assert [(a["game_code"], a["threshold"]) for a in alerts] == [("euromillions", 34_000_000)]


def test_remove_change_and_add():
    _played(7, "euromillions")
    lo_alerts.unfollow(7, "euromillions")
    assert lo_alerts.customer_alerts(7) == []
    lo_alerts.follow(7, "powerball", 150_000_000)
    assert [(a["game_code"], a["threshold"], a["custom"]) for a in lo_alerts.customer_alerts(7)] == [("powerball", 150_000_000, True)]


def test_watcher_fires_once_per_lottery_per_draw():
    _played(7, "euromillions")
    sent = []
    send = lambda ids, payload: (sent.append((ids, payload)), {"sent": 1})[1]
    fmt = lambda a, c: f"€{a / 1e6:g} Million"
    run = lambda amount, draw: lo_alerts.run_watcher(customers=[7], jackpot=lambda g: jp(amount, draw), fmt=fmt, send=send)
    assert run(30_000_000, "2026-10-03")["fired"] == 0          # under €34M
    assert run(40_000_000, "2026-10-03")["fired"] == 1
    assert run(45_000_000, "2026-10-03")["fired"] == 0          # same draw: never twice
    assert run(60_000_000, "2026-10-07")["fired"] == 1          # next draw
    ids, payload = sent[0]
    assert ids == [7] and payload["url"] == "/lottery-tickets/euromillions"
    assert "passed €34 Million" in payload["body"] and "win" not in payload["body"].lower()


def test_alerts_page_and_form(client, stub_crm):
    cid = _cid(client)
    _played(cid, "euromillions")
    html = client.get("/account/alerts").get_data(as_text=True)
    assert "EuroMillions" in html and 'value="34"' in html
    token = _csrf(client)
    client.post("/account/alerts", data={"csrf_token": token, "game_code": "euromillions", "threshold_millions": "50", "action": "save"})
    assert lo_alerts.customer_alerts(cid)[0]["threshold"] == 50_000_000
    client.post("/account/alerts", data={"csrf_token": token, "game_code": "euromillions", "action": "remove"})
    assert lo_alerts.customer_alerts(cid) == []
    assert client.post("/account/alerts", data={"csrf_token": "x", "game_code": "euromillions"}).status_code == 400
