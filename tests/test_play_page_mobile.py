"""
Below 768px the stylesheet collapses a line to a single row and hides the number
grids (mobile.css: `#lowerTicketSection { display:none }`), so a phone can only
change a selection if the line's edit control opens it over the page.

Those `.showTicket` styles are inherited from the legacy site and are easy to
leave orphaned, which is exactly what happened: the markup carried no edit
handler, no Done and no close, so numbers were unreachable on mobile. These
tests pin the controls, the picker wiring and the stylesheet hook together.
"""

from __future__ import annotations


def _line_template(body: str) -> str:
    """The per-line markup the picker clones for every line."""
    assert '<template id="leLineTemplate">' in body
    return body.split('<template id="leLineTemplate">', 1)[1].split("</template>", 1)[0]


def test_a_line_carries_edit_done_and_close_controls(client, stub_crm):
    resp = client.get("/lottery-tickets/us-powerball")
    assert resp.status_code == 200
    tpl = _line_template(resp.get_data(as_text=True))

    assert 'data-action="edit"' in tpl
    assert 'data-action="done"' in tpl
    assert 'data-action="close-editor"' in tpl
    # mobile.css styles the close control and Done by these hooks.
    assert 'id="closeTicketWindow"' in tpl
    assert 'class="done"' in tpl


def test_the_page_has_the_backdrop_the_open_line_sits_on(client, stub_crm):
    resp = client.get("/lottery-tickets/us-powerball")
    assert 'id="mobileTicketWindow"' in resp.get_data(as_text=True)


def test_the_picker_opens_and_closes_the_full_screen_editor(client):
    js = client.get("/resources/js/play_picker.js").get_data(as_text=True)
    core = client.get("/resources/js/line_editor_core.js").get_data(as_text=True)

    assert 'action === "edit"' in js
    assert 'action === "done" || action === "close-editor"' in js
    # State the legacy stylesheet keys the full-screen layout off. It lives in
    # the shared engine, which the cart's line editor opens the same way.
    assert "showTicket" in core
    assert "mobileLinesSection" in core
    assert "mobileTicketWindow" in core
    assert "leEditingLine" in core


def test_the_play_page_loads_the_shared_engine_first(client, stub_crm):
    """play_picker.js reads window.LELineCore at load, so order matters."""
    body = client.get("/lottery-tickets/us-powerball").get_data(as_text=True)
    assert body.index("line_editor_core.js") < body.index("play_picker.js")


def test_page_furniture_is_restored_rather_than_blanket_shown(client):
    """Legacy closed the editor with jQuery .show() on everything it had hidden,
    which resurrected things like a dismissed cookie prompt."""
    core = client.get("/resources/js/line_editor_core.js").get_data(as_text=True)
    assert "data-le-hidden" in core
    assert "restoreAfterEditing" in core


def test_lines_arrive_quick_picked(client):
    """An empty line shows nothing in the collapsed mobile row and prices at
    zero, so the page opens on a playable ticket."""
    js = client.get("/resources/js/play_picker.js").get_data(as_text=True)
    assert "state.lines.push(quickPickLine(state.groups))" in js


def test_the_open_line_stays_in_flow_for_tall_grids(client):
    """The legacy rule pins the open line to 540px, which clips games with two
    large grids; the editor overrides it instead of relying on per-game heights."""
    css = client.get("/resources/css/mobile.css").get_data(as_text=True)
    assert "body.leEditingLine" in css
    assert "body.leEditingLine #main #tickets_section .showTicket .lines { height:auto" in css
