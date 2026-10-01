from __future__ import annotations

import pytest

import crm_sync
from app import app as flask_app
from crm_api import CRMClient, CRMError
from crm_cache import CacheConfig, CRMCache


@pytest.fixture
def own_cache(tmp_path):
    """
    A cache belonging to this test alone.

    These tests write real draws and real sync watermarks. On the shared session
    cache that would leave September's results, and a satisfied fetch stamp,
    behind for everything that ran afterwards.
    """
    original = flask_app.config["CRM_CACHE"]
    cache = CRMCache(CacheConfig(db_path=str(tmp_path / "cache.sqlite"), brand=original.cfg.brand))
    cache.init_db()
    flask_app.config["CRM_CACHE"] = cache
    try:
        yield cache
    finally:
        flask_app.config["CRM_CACHE"] = original


@pytest.fixture
def instant_retries(monkeypatch):
    """`run_with_backoff` sleeps between attempts, so five failures is 15 seconds."""
    monkeypatch.setattr(crm_sync.time, "sleep", lambda *_a, **_k: None)


def _draw(draw_id: str, game_code: str, draw_date: str, main: list[int] | None = None) -> dict:
    return {
        "id": draw_id,
        "game_code": game_code,
        "draw_date": draw_date,
        "status": "completed",
        "currency": "USD",
        "numbers": {"main": main or [1, 2, 3, 4, 5], "powerball": [6]},
    }


class _NoCRM:
    """A CRM that fails the test if it is asked for anything."""

    def _request(self, method, path, *args, **kwargs):
        raise AssertionError(f"should not have called the CRM: {method} {path}")


# --- product prices: the job that was aborting the pass ---


def test_product_prices_skips_when_the_cache_has_nowhere_to_store_them(own_cache):
    """
    The snapshot is a nice-to-have that nothing currently reads, so a cache
    without a place to put it is not an error. This used to raise AttributeError
    and take the rest of the sync pass with it.
    """
    assert not hasattr(own_cache, "upsert_product_prices"), "fixture assumes the method is still absent"

    out = crm_sync.sync_product_prices_once(_NoCRM(), own_cache)

    assert out["products"] == 0
    assert out["skipped"]
    # Stamped, so the job drops to its normal interval rather than asking the
    # CRM for a games list on every pass only to throw the answer away.
    assert own_cache.get_state("last_product_prices_fetch_at")


def test_product_prices_are_stored_when_the_cache_can_hold_them(own_cache, monkeypatch):
    stored: list[dict] = []

    def upsert(rows):
        stored.extend(rows)
        return len(stored)

    monkeypatch.setattr(own_cache, "upsert_product_prices", upsert, raising=False)

    class Client:
        def _request(self, method, path, *args, **kwargs):
            return {"games": [{"game_code": "powerball", "products": [{"product_code": "PB_SINGLE"}]}]}

    out = crm_sync.sync_product_prices_once(Client(), own_cache)

    assert out["products"] == 1
    assert stored[0]["product_code"] == "PB_SINGLE"
    assert stored[0]["game_code"] == "powerball"
    assert own_cache.get_state("last_product_prices_fetch_at")


# --- one broken job no longer silences the rest of the loop ---


def test_a_failing_job_no_longer_stops_the_jobs_after_it(own_cache, monkeypatch, instant_retries):
    """
    The regression this whole change exists for.

    Product prices called a cache method that did not exist. `run_with_backoff`
    re-raises once its attempts are spent, so that one AttributeError ended the
    pass before draw results — last in the list — ever ran. Winning numbers sat
    a month behind while jackpots and policies, which run earlier, kept updating.
    """

    def boom(*_a, **_k):
        raise AttributeError("'CRMCache' object has no attribute 'upsert_product_prices'")

    monkeypatch.setattr("app.sync_product_prices_once", boom)

    def fake_request(self, method, path, *args, **kwargs):
        if str(path).endswith("/store/games"):
            return {"games": []}
        if "/draw-results" in str(path):
            return {"draws": [_draw("d-1", "powerball", "2026-09-07")], "has_more": False}
        raise CRMError(f"unexpected {method} {path}", status_code=404)

    monkeypatch.setattr(CRMClient, "_request", fake_request)

    flask_app.extensions["crm_sync_once"]()

    assert [d["draw_date"] for d in own_cache.get_draw_results_for_game("powerball")] == ["2026-09-07"]
    # The failure is still recorded rather than quietly dropped.
    assert "upsert_product_prices" in (own_cache.get_state("product_prices_last_error") or "")


# --- draw results can catch up on their own ---


def test_draw_results_drain_every_page_the_crm_still_has(own_cache, monkeypatch):
    """
    The bulk endpoint is ordered oldest-updated-first, so taking a single page
    per interval can only crawl forwards through history. A cursor left in July
    could never reach September that way.
    """
    pages = [
        {"draws": [_draw("d-1", "powerball", "2026-07-21")], "has_more": True, "next_cursor": "c-1"},
        {"draws": [_draw("d-2", "powerball", "2026-08-15")], "has_more": True, "next_cursor": "c-2"},
        {"draws": [_draw("d-3", "powerball", "2026-09-07")], "has_more": False, "next_cursor": "c-3"},
    ]
    seen: list[str | None] = []

    class Client:
        def _request(self, method, path, *args, **kwargs):
            seen.append((kwargs.get("params") or {}).get("cursor"))
            return pages[len(seen) - 1]

    own_cache.set_state("last_draw_results_cursor", "c-0")

    out = crm_sync.sync_draw_results_incremental(
        Client(), own_cache, backfill_all_pages=True, sleep_seconds=0
    )

    assert out["pages"] == 3
    assert out["has_more"] is False
    assert seen == ["c-0", "c-1", "c-2"]
    assert own_cache.get_state("last_draw_results_cursor") == "c-3"
    assert [d["draw_date"] for d in own_cache.get_draw_results_for_game("powerball")][0] == "2026-09-07"


def test_a_run_that_stops_on_its_page_budget_reports_more_to_come(own_cache):
    class Client:
        def _request(self, method, path, *args, **kwargs):
            return {"draws": [_draw("d-1", "powerball", "2026-07-21")], "has_more": True, "next_cursor": "c-1"}

    out = crm_sync.sync_draw_results_incremental(
        Client(), own_cache, backfill_all_pages=True, max_pages=1, sleep_seconds=0
    )

    assert out["pages"] == 1
    assert out["has_more"] is True


def test_the_sync_comes_straight_back_while_draw_results_are_behind(own_cache, monkeypatch, instant_retries):
    """
    `sync_draw_results_incremental` stamps its fetch time whether or not it
    finished, so without a separate flag a backfill that stopped on its page
    budget would wait out the twelve-hour interval before resuming.
    """
    calls = {"n": 0}

    def fake_request(self, method, path, *args, **kwargs):
        if str(path).endswith("/store/games"):
            return {"games": []}
        if "/draw-results" in str(path):
            calls["n"] += 1
            return {"draws": [_draw(f"d-{calls['n']}", "powerball", "2026-07-21")], "has_more": True, "next_cursor": "c"}
        raise CRMError(f"unexpected {method} {path}", status_code=404)

    monkeypatch.setattr(CRMClient, "_request", fake_request)
    monkeypatch.setattr("app._DRAW_RESULTS_PAGES_PER_RUN", 1)

    flask_app.extensions["crm_sync_once"]()
    assert own_cache.get_state("draw_results_caught_up") == "0"

    # The stamp is fresh now, so only the flag can bring it back this soon.
    before = calls["n"]
    flask_app.extensions["crm_sync_once"]()
    assert calls["n"] > before


def test_a_drained_run_settles_back_onto_its_interval(own_cache, monkeypatch, instant_retries):
    def fake_request(self, method, path, *args, **kwargs):
        if str(path).endswith("/store/games"):
            return {"games": []}
        if "/draw-results" in str(path):
            return {"draws": [_draw("d-1", "powerball", "2026-09-07")], "has_more": False}
        raise CRMError(f"unexpected {method} {path}", status_code=404)

    monkeypatch.setattr(CRMClient, "_request", fake_request)

    flask_app.extensions["crm_sync_once"]()

    assert own_cache.get_state("draw_results_caught_up") == "1"


# --- the results page can show the newest draw ---


def test_the_results_page_windows_its_live_fetch_by_draw_date(own_cache, anon_client, full_catalog, monkeypatch):
    """
    Asking for a plain page of a long-running game returns the oldest draws,
    because the endpoint is ordered by update time for the incremental sync.
    A draw-date window is what makes the newest draw reachable.
    """
    asked: list[dict] = []

    def fake_draw_results(self, **kwargs):
        asked.append(kwargs)
        return {"draws": []}

    monkeypatch.setattr(CRMClient, "draw_results", fake_draw_results)

    assert anon_client.get("/results/powerball").status_code == 200

    assert asked, "the results page never asked the CRM"
    assert asked[0]["draw_date_from"], "the live fetch is still unwindowed"


def test_the_results_page_answers_from_the_cache(own_cache, anon_client, full_catalog, monkeypatch):
    """
    The page used to return the live payload directly, which is how it could
    show a different latest result than the homepage and nav — those read the
    cache. Whatever the CRM's windowed, update-ordered page happens to contain,
    the page shows the newest draw the site knows about.
    """
    own_cache.upsert_draw_results_page(
        [_draw("newest", "powerball", "2026-09-07", main=[11, 22, 33, 44, 55])],
        include_prize_tiers=False,
    )

    def fake_draw_results(self, **kwargs):
        # The oldest-first page the CRM would really hand back.
        return {"draws": [_draw("oldest", "powerball", "2026-08-10", main=[1, 2, 3, 4, 5])]}

    monkeypatch.setattr(CRMClient, "draw_results", fake_draw_results)

    body = anon_client.get("/results/powerball").get_data(as_text=True)

    assert "Sep 07" in body
    assert "Sep 2026" in body
