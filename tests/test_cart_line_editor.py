"""
Editing a cart line used to POST to /cart/edit-line and land the customer back
on /play, which lost their place in the cart and rebuilt a whole ticket to
change one row. The cart now mounts the play page's own number board in the line
itself: expanded in place on desktop, full screen below 768px.

These tests pin the three things that make that work — the board's markup, the
schema the grids are built from, and the save path back into the cart — since
each is invisible from the other side.
"""

from __future__ import annotations

from tests.test_cart_checkout import VALID_ADD


def _cart_with_item(client):
    client.post("/cart/add", data=VALID_ADD)
    resp = client.get("/cart")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_the_cart_carries_the_play_pages_line_markup(client, stub_crm):
    """The legacy stylesheet only dresses this shape, and the full-screen state
    below 768px is keyed off `#main #tickets_section .showTicket`."""
    html = _cart_with_item(client)

    assert 'id="leCartLineEditor"' in html
    assert 'id="tickets_section"' in html
    assert 'class="leLineWrapper"' in html
    assert 'class="leGroups"' in html
    # The backdrop the open line sits on, and the mobile bar's controls.
    assert 'id="mobileTicketWindow"' in html
    assert 'id="closeTicketWindow"' in html
    assert 'class="done primaryFormButton"' in html
    assert 'data-action="quickpick"' in html
    assert 'data-action="save"' in html
    assert 'data-action="cancel"' in html


def test_each_line_offers_its_numbers_and_product_to_the_editor(client, stub_crm):
    html = _cart_with_item(client)

    assert 'class="leCartLine"' in html
    assert 'data-item-idx="0"' in html
    assert 'data-line-idx="0"' in html
    assert 'data-product-code="PB_SINGLE"' in html
    # The stored line is what the grids open on.
    assert "data-line-json=" in html


def test_the_page_ships_the_board_layout_for_every_sku_in_the_cart(client, stub_crm):
    """Grids are built from the product's line_schema; without it the line has
    no editor at all."""
    html = _cart_with_item(client)
    assert 'id="leCartLineSchemas"' in html
    schemas = html.split('id="leCartLineSchemas" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "PB_SINGLE" in schemas
    assert '"main"' in schemas


def test_the_editor_saves_through_the_cart_rather_than_the_play_page(client, stub_crm):
    html = _cart_with_item(client)
    editor = html.split('id="leCartLineEditor"', 1)[1].split("</form>", 1)[0]
    assert 'action="/cart/update-line"' in editor
    # The no-JS fallback still exists on the row itself.
    assert 'action="/cart/edit-line"' in html


def test_a_saved_line_replaces_the_numbers_and_drops_the_stale_quote(client, stub_crm):
    client.post("/cart/add", data=VALID_ADD)
    with client.session_transaction() as s:
        s["checkout_quote_id"] = 4242
        before = s["cart_items"][0]["lines"][0]
    assert before["main"] != "7,8,9,10,11"

    resp = client.post(
        "/cart/update-line",
        data={"item_idx": "0", "line_idx": "0", "field__main": "7,8,9,10,11", "field__power": "3"},
    )
    assert resp.status_code == 302
    assert "open_item_idx=0" in resp.headers["Location"]
    with client.session_transaction() as s:
        line = s["cart_items"][0]["lines"][0]
        assert line["main"] == "7,8,9,10,11"
        assert str(line["power"]) == "3"
        # The cart must be re-priced by the CRM, not against the old quote.
        assert not s.get("checkout_quote_id")


def test_the_cart_editor_opens_in_place_instead_of_navigating(client):
    js = client.get("/resources/js/cart_line_editor.js").get_data(as_text=True)

    # The Edit button is a form submit as a no-JS fallback, so the picker has to
    # take the click for the board to open in the cart.
    assert "ev.preventDefault()" in js
    assert 'data-action") === "cart-edit"' in js
    assert "core.openLineEditor" in js
    assert "field__" in js


def test_hovering_the_open_board_cannot_resize_it(client, stub_crm):
    """The play page grows a line on hover. In the cart that pulls the card out
    from under the pointer, the hover drops, it shrinks back — a flicker that
    leaves the controls unclickable, so hover is pinned to the base geometry."""
    html = _cart_with_item(client)
    assert ".leCartEditor #main #tickets_section .lines,\n  .leCartEditor #main #tickets_section .lines:hover" in html


def test_the_boards_page_wrapper_does_not_bring_its_background(client, stub_crm):
    """`#main` is the play page's wrapper and carries the site's dark blue; in
    the cart it is only a styling hook."""
    html = _cart_with_item(client)
    assert ".leCartEditor #main {" in html
    assert "background: transparent !important;" in html
    # Floated tiles need containing, or the grid falls out of the white card.
    assert ".leCartEditor #main #tickets_section .lines ul {" in html


def test_quick_pick_survives_the_pointer_on_a_finished_line(client, stub_crm):
    """style.css hides Quick Pick on a complete tile under `:hover`, with
    `!important`. In the cart the button is on screen from the start, so that
    rule took it away as the customer moved to click it."""
    html = _cart_with_item(client)
    assert (
        ".leCartEditor #main #tickets_section .lines.ticketComplete:hover "
        "#webUpperTicketSection button.quickPickButton {\n    display: inline-block !important;"
    ) in html


def test_the_editors_controls_escape_the_panels_button_sizing(client, stub_crm):
    """`.processOrderContent button` is 191x67 !important, which swallows Clear,
    Quick Pick and Done."""
    html = _cart_with_item(client)
    assert ".processOrderContent .leCartEditor button {" in html


def test_the_cart_loads_the_shared_engine_before_its_editor(client, stub_crm):
    html = _cart_with_item(client)
    assert html.index("line_editor_core.js") < html.index("cart_line_editor.js")


def test_an_empty_cart_ships_no_editor(client, stub_crm):
    html = client.get("/cart").get_data(as_text=True)
    assert 'id="leCartLineEditor"' not in html
    assert "cart_line_editor.js" not in html
