"""
Tests for the account page's Orders tab: the Order History expanded item rows
must show real ticket data from the order detail endpoint (game, numbers,
lines, draw date, winnings) instead of placeholder dashes, and the Legacy
Orders accordion must follow the visibility rules.
"""

from __future__ import annotations

from typing import Any

from crm_api import CRMClient


def _patch_account_crm(monkeypatch, *, legacy_list: Any = None) -> None:
    def fake_legacy_orders(self, token, *, page=1, per_page=25):
        if isinstance(legacy_list, Exception):
            raise legacy_list
        if legacy_list is not None:
            return legacy_list
        return {"success": True, "page": 1, "per_page": 25, "total": 0, "orders": []}

    monkeypatch.setattr(CRMClient, "legacy_orders", fake_legacy_orders)
    monkeypatch.setattr(
        CRMClient,
        "customer_me",
        lambda self, token: {"customer": {"id": 1, "first_name": "Test", "last_name": "User", "email": "t@example.com"}},
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet",
        lambda self, token: {"wallet": {"currency": "USD", "balance_cents": 10000, "withdrawable_cents": 10000}},
    )
    monkeypatch.setattr(
        CRMClient,
        "wallet_transactions",
        lambda self, token, *, page=1, per_page=25: {"transactions": []},
    )
    monkeypatch.setattr(
        CRMClient,
        "winnings_tickets",
        lambda self, token, **kwargs: {"tickets": []},
    )
    monkeypatch.setattr(
        CRMClient,
        "orders",
        lambda self, token, *, page=1, per_page=25: {
            "orders": [
                {
                    "id": 7,
                    "status": "completed",
                    "created_at": "2026-01-31T01:52:15",
                    "currency": "USD",
                    "total_cents": 753,
                    "tickets_count": 1,
                }
            ]
        },
    )
    monkeypatch.setattr(
        CRMClient,
        "order",
        lambda self, token, order_id: {
            "order": {
                "id": order_id,
                "status": "completed",
                "currency": "USD",
                "total_cents": 753,
                "tickets": [
                    {
                        "id": 91,
                        "game_name": "Powerball",
                        "game_code": "powerball",
                        "product_code": "PB_SINGLE",
                        "status": "completed",
                        "draw_date": "2026-02-01",
                        "lines_count": 2,
                        "boards_display": "1, 2, 3, 4, 5 + 6",
                        "catalog_wheel": None,
                        "winnings_total_cents": 500,
                        "customer_currency": "USD",
                    }
                ],
                "items": [],
            }
        },
    )


def test_account_order_history_shows_real_ticket_details(client, monkeypatch):
    _patch_account_crm(monkeypatch)
    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # Order row still renders.
    assert "2026-01-31T01:52:15" in html
    assert "USD 7.53" in html
    # Expanded item row shows real detail instead of placeholder dashes.
    assert "Powerball" in html
    assert "1, 2, 3, 4, 5 + 6" in html
    assert "2026-02-01" in html
    assert "USD 5.00" in html


def test_account_order_history_survives_detail_fetch_failure(client, monkeypatch):
    _patch_account_crm(monkeypatch)

    def boom(self, token, order_id):
        raise RuntimeError("detail unavailable")

    monkeypatch.setattr(CRMClient, "order", boom)
    resp = client.get("/account")
    assert resp.status_code == 200
    # The order list row still renders even though detail enrichment failed.
    assert b"USD 7.53" in resp.data


# --- Legacy Orders accordion on the account page ---

LEGACY_LIST = {
    "success": True,
    "page": 1,
    "per_page": 25,
    "total": 1,
    "orders": [
        {
            "id": "legacy-order-guid",
            "display_number": "12345",
            "order_number": "ORD-12345",
            "status": "completed",
            "currency": "GBP",
            "total_cents": 2500,
            "placed_at": "2024-02-10T14:30:00",
            "product_labels": ["EuroMillions"],
            "tickets_count": 1,
        }
    ],
}


def test_account_shows_legacy_orders_section_when_history_exists(client, monkeypatch):
    _patch_account_crm(monkeypatch, legacy_list=LEGACY_LIST)
    resp = client.get("/account")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Legacy Orders" in html
    assert "12345" in html
    assert "EuroMillions" in html
    assert "GBP 25.00" in html
    assert 'href="/legacy-orders/legacy-order-guid"' in html


def test_account_hides_legacy_orders_section_when_none(client, monkeypatch):
    # Spec behavior (override off): total == 0 hides the section entirely.
    _patch_account_crm(monkeypatch)
    resp = client.get("/account")
    assert resp.status_code == 200
    assert b"Legacy Orders" not in resp.data


def test_account_shows_empty_legacy_orders_section_with_override(client, monkeypatch):
    monkeypatch.setenv("LEGACY_ORDERS_SHOW_EMPTY", "1")
    _patch_account_crm(monkeypatch)
    resp = client.get("/account")
    assert resp.status_code == 200
    assert b"Legacy Orders" in resp.data
    assert b"No legacy orders" in resp.data


def test_account_hides_legacy_orders_section_on_fetch_failure(client, monkeypatch):
    monkeypatch.setenv("LEGACY_ORDERS_SHOW_EMPTY", "0")
    _patch_account_crm(monkeypatch, legacy_list=RuntimeError("legacy endpoint unavailable"))
    resp = client.get("/account")
    assert resp.status_code == 200
    # Page still renders; section hidden but failure isn't proof of no history.
    assert b"USD 7.53" in resp.data
    assert b"Legacy Orders" not in resp.data
