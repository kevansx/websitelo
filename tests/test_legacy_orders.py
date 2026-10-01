"""
Focused tests for the read-only Legacy Orders feature.

Covers the acceptance checks from the Legacy Orders brief:
- Tab visibility (only shown after a successful legacy list response with total > 0;
  hidden for total == 0; a failed check hides the tab but is not cached as "no history").
- Legacy list rendering + pagination from the response's page/per_page/total.
- API failure surfaced through the site's normal flash error reporting.
- Empty response never renders an empty Legacy Orders tab.
- Detail 404 renders the site's normal not-found page.
- Legacy records expose no transactional action controls.

The site is server-rendered (Flask + Jinja), so the "loading" requirement — keeping
the tab hidden while the initial legacy request is in flight — is inherent: the page
HTML is only produced after the legacy check has completed.
"""

from __future__ import annotations

from typing import Any

from crm_api import CRMClient, CRMError

LEGACY_LIST_ORDER = {
    "id": "legacy-order-guid",
    "is_legacy": True,
    "order_number": "ORD-12345",
    "display_number": "12345",
    "status": "completed",
    "source_status": "Completed",
    "currency": "GBP",
    "total_cents": 2500,
    "placed_at": "2024-02-10T14:30:00",
    "created_at": "2024-02-10T14:30:00",
    "is_paid": True,
    "name": "Order 12345",
    "description": None,
    "promo_code": None,
    "account_manager": None,
    "product_labels": ["EuroMillions"],
    "tickets_count": 1,
    "has_tickets": True,
}


def _legacy_list_response(*, total: int, page: int = 1, per_page: int = 25, orders: list | None = None) -> dict:
    if orders is None:
        orders = [LEGACY_LIST_ORDER] if total > 0 else []
    return {"success": True, "page": page, "per_page": per_page, "total": total, "orders": orders}


def _patch_crm(
    monkeypatch,
    *,
    current_orders: dict | None = None,
    legacy_list: Any = None,
    legacy_detail: Any = None,
) -> dict:
    """Stub the CRM client's order methods. Pass an Exception instance to make a call fail."""
    calls: dict[str, list] = {"orders": [], "legacy_orders": [], "legacy_order": []}

    def fake_orders(self, token, *, page=1, per_page=25):
        calls["orders"].append({"token": token, "page": page, "per_page": per_page})
        return current_orders if current_orders is not None else {"orders": []}

    def fake_legacy_orders(self, token, *, page=1, per_page=25):
        calls["legacy_orders"].append({"token": token, "page": page, "per_page": per_page})
        if isinstance(legacy_list, Exception):
            raise legacy_list
        return legacy_list if legacy_list is not None else _legacy_list_response(total=0)

    def fake_legacy_order(self, token, legacy_order_id):
        calls["legacy_order"].append({"token": token, "legacy_order_id": legacy_order_id})
        if isinstance(legacy_detail, Exception):
            raise legacy_detail
        return legacy_detail

    monkeypatch.setattr(CRMClient, "orders", fake_orders)
    monkeypatch.setattr(CRMClient, "legacy_orders", fake_legacy_orders)
    monkeypatch.setattr(CRMClient, "legacy_order", fake_legacy_order)
    return calls


# --- Tab visibility on the current-orders page ---


def test_tab_hidden_when_total_is_zero(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=0))
    resp = client.get("/orders")
    assert resp.status_code == 200
    assert b"Legacy Orders" not in resp.data


def test_tab_shown_when_customer_has_legacy_history(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=1))
    resp = client.get("/orders")
    assert resp.status_code == 200
    assert b"Legacy Orders" in resp.data
    assert b'href="/legacy-orders"' in resp.data


def _panel_header(body: str, header_id: str) -> str:
    """The opening tag of one accordion header, where `active` lives."""
    return body.split(f'id="{header_id}"')[1].split(">")[0]


def test_the_orders_tab_opens_on_the_orders_placed_here(client, monkeypatch, stub_crm):
    """
    Two panels sit on this tab and the accordion opens whichever is marked
    `active`. It was the imported AS400 list, so a customer clicking Orders
    was shown a history that stops before everything they bought on this
    site - and support were being asked where the recent orders had gone.
    """
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=3))
    body = client.get("/account").get_data(as_text=True)
    assert "active" in _panel_header(body, "orderHistoryDropDown")


def test_the_imported_history_stays_closed_until_it_is_asked_for(client, monkeypatch, stub_crm):
    """
    Still one click away, and still listed, because customers who bought by
    post do come looking for it.
    """
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=3))
    body = client.get("/account").get_data(as_text=True)
    assert "Legacy Orders" in body
    assert "active" not in _panel_header(body, "legacyOrderHistoryDropDown")


def test_only_one_order_panel_is_open_to_begin_with(client, monkeypatch, stub_crm):
    """
    The accordion closes siblings on click but not on load, so two panels
    marked open in the markup would both render open.
    """
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=3))
    body = client.get("/account").get_data(as_text=True)
    opened = [
        header_id
        for header_id in ("orderHistoryDropDown", "legacyOrderHistoryDropDown")
        if "active" in _panel_header(body, header_id)
    ]
    assert opened == ["orderHistoryDropDown"]


def test_tab_hidden_when_legacy_check_fails_but_current_orders_still_render(client, monkeypatch):
    current = {"orders": [{"id": 777, "status": "paid", "created_at": "2026-01-01", "currency": "EUR", "total_cents": 1000, "tickets_count": 2}]}
    _patch_crm(monkeypatch, current_orders=current, legacy_list=CRMError("CRM HTTP 503: down", status_code=503))
    resp = client.get("/orders")
    assert resp.status_code == 200
    # Current orders behave as before.
    assert b"#777" in resp.data
    # A failed check hides the tab for this render...
    assert b"Legacy Orders" not in resp.data


def test_failed_check_is_not_cached_as_no_history(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=CRMError("CRM HTTP 503: down", status_code=503))
    client.get("/orders")
    # Once the CRM recovers, the tab appears again without a new login.
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=1))
    resp = client.get("/orders")
    assert b"Legacy Orders" in resp.data


# --- Legacy list page ---


def test_legacy_list_renders_expected_fields(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=1))
    resp = client.get("/legacy-orders")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # display_number is the customer-visible order number (not the raw id / order_number).
    assert "#12345" in html
    assert "ORD-12345" not in html
    assert "2024-02-10T14:30:00" in html
    assert "EuroMillions" in html
    assert "GBP 25.00" in html
    assert "completed" in html
    # Detail link uses the string id.
    assert 'href="/legacy-orders/legacy-order-guid"' in html


def test_legacy_list_has_no_action_controls(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=1))
    html = client.get("/legacy-orders").data.decode("utf-8")
    for forbidden in ("Refund", "Reorder", "Cancel", "Retry", "Pay now"):
        assert forbidden not in html


def test_legacy_list_pagination_uses_response_metadata(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=60, page=2, per_page=25))
    resp = client.get("/legacy-orders?page=2")
    html = resp.data.decode("utf-8")
    assert "Page 2 of 3" in html
    assert 'href="/legacy-orders?page=1"' in html
    assert 'href="/legacy-orders?page=3"' in html


def test_legacy_list_requests_page_from_query_string(client, monkeypatch):
    calls = _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=60, page=3, per_page=25))
    client.get("/legacy-orders?page=3")
    assert calls["legacy_orders"] == [{"token": "test-token", "page": 3, "per_page": 25}]


def test_legacy_list_empty_redirects_to_current_orders(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=0))
    resp = client.get("/legacy-orders")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/orders")


def test_legacy_list_api_failure_uses_normal_error_reporting(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_list=CRMError("CRM HTTP 503: down", status_code=503))
    resp = client.get("/legacy-orders", follow_redirects=True)
    assert resp.status_code == 200
    assert b"temporarily unavailable" in resp.data


# --- Legacy detail page ---


def _legacy_detail_response() -> dict:
    # Per API.md the detail response carries the same header fields as the list
    # endpoint at the top level, plus items[] and tickets[].
    return {
        "success": True,
        **LEGACY_LIST_ORDER,
        "items": [
            {
                "id": 1,
                "product_description": "EuroMillions - Single Play",
                "lottery_name": "EuroMillions",
                "sku": "EM-SINGLE",
                "quantity": 1,
                "amount_cents": 2500,
                "unit_price_cents": 2500,
                "ordinal": 1,
            },
        ],
        "tickets": [
            {
                "id": "legacy-ticket-1",
                "line_item_ids": [1],
                "ticket_index": 1,
                "lottery_name": "EuroMillions",
                "status": "completed",
                "draw_date": "2024-02-13",
                "board": "05-11-23-38-44 + 02-07",
                "board_data": {"main": [5, 11, 23, 38, 44], "lucky_stars": [2, 7]},
                "currency": "GBP",
                "cost_cents": 2500,
                "serial_number": "SN-0001",
                "ltech_ticket_id": None,
            },
            {
                "id": "legacy-ticket-2",
                "line_item_ids": [1],
                "ticket_index": 2,
                "lottery_name": "EuroMillions",
                "status": "completed",
                "draw_date": "2024-02-16",
                "board": "01-02-03-04-05 + 01-02",
                "board_data": None,
                "currency": "GBP",
                "cost_cents": 2500,
                "serial_number": "SN-0002",
                "ltech_ticket_id": None,
            },
        ],
    }


def test_legacy_detail_renders_header_items_and_tickets(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_detail=_legacy_detail_response())
    resp = client.get("/legacy-orders/legacy-order-guid")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "#12345" in html
    assert "GBP 25.00" in html
    # Items use the documented fields.
    assert "EuroMillions - Single Play" in html
    assert "EM-SINGLE" in html
    # Tickets use the documented fields.
    assert "SN-0001" in html
    # Structured board_data is rendered when present...
    assert "5, 11, 23, 38, 44" in html
    assert "2, 7" in html
    # ...and the plain board string is used when board_data is null.
    assert "01-02-03-04-05 + 01-02" in html


def test_legacy_detail_tolerates_order_wrapper(client, monkeypatch):
    detail = _legacy_detail_response()
    wrapped = {"success": True, "order": {k: v for k, v in detail.items() if k != "success"}}
    _patch_crm(monkeypatch, legacy_detail=wrapped)
    resp = client.get("/legacy-orders/legacy-order-guid")
    assert resp.status_code == 200
    assert b"#12345" in resp.data


def test_legacy_detail_is_read_only(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_detail=_legacy_detail_response())
    html = client.get("/legacy-orders/legacy-order-guid").data.decode("utf-8")
    for forbidden in ("Refund", "Reorder", "Cancel", "Retry", "Pay now", "Refresh ticket scan"):
        assert forbidden not in html


def test_legacy_detail_404_shows_not_found_page(client, monkeypatch):
    _patch_crm(monkeypatch, legacy_detail=CRMError("CRM HTTP 404: not found", status_code=404))
    resp = client.get("/legacy-orders/unknown-guid")
    assert resp.status_code == 404


def test_legacy_detail_other_failure_redirects_with_error(client, monkeypatch):
    _patch_crm(
        monkeypatch,
        legacy_list=_legacy_list_response(total=1),
        legacy_detail=CRMError("CRM HTTP 502: bad gateway", status_code=502),
    )
    resp = client.get("/legacy-orders/legacy-order-guid", follow_redirects=True)
    assert resp.status_code == 200
    assert b"temporarily unavailable" in resp.data


# --- Verification override: LEGACY_ORDERS_SHOW_EMPTY ---


def test_override_shows_tab_even_with_no_legacy_history(client, monkeypatch):
    monkeypatch.setenv("LEGACY_ORDERS_SHOW_EMPTY", "1")
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=0))
    resp = client.get("/orders")
    assert resp.status_code == 200
    assert b"Legacy Orders" in resp.data


def test_override_renders_empty_legacy_list_page(client, monkeypatch):
    monkeypatch.setenv("LEGACY_ORDERS_SHOW_EMPTY", "1")
    _patch_crm(monkeypatch, legacy_list=_legacy_list_response(total=0))
    resp = client.get("/legacy-orders")
    assert resp.status_code == 200
    assert b"No legacy orders." in resp.data


# --- Auth ---


def test_legacy_routes_require_login(monkeypatch):
    from app import app as flask_app

    _patch_crm(monkeypatch)
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as anon:
        for path in ("/legacy-orders", "/legacy-orders/legacy-order-guid"):
            resp = anon.get(path)
            assert resp.status_code == 302
            assert "/login" in resp.headers["Location"]
