/* Lotto Express — edit a cart line without leaving the cart
 *
 * The cart used to send the customer back to /play to change one line, which
 * lost their place and re-rendered a whole ticket to edit a single row. This
 * mounts the play page's own number board (line_editor_core.js) into the line
 * being edited: expanded in place on desktop, and full screen over the page
 * below 768px, where the stylesheet hides the grids otherwise.
 *
 * Saving posts the line to /cart/update-line, so the CRM re-quotes the cart and
 * the totals on the page stay the CRM's.
 */

(function () {
  var core = window.LELineCore;
  if (!core) return;

  var KEEP_TAGS = { SCRIPT: 1, STYLE: 1, LINK: 1, NOSCRIPT: 1, TEMPLATE: 1 };

  function schemas() {
    var el = document.getElementById("leCartLineSchemas");
    if (!el) return {};
    try {
      var v = JSON.parse(el.textContent || "{}");
      return (v && typeof v === "object") ? v : {};
    } catch (e) {
      return {};
    }
  }

  function closestEl(node, selector) {
    var n = node;
    while (n && n.nodeType === 1) {
      if (n.matches && n.matches(selector)) return n;
      n = n.parentElement;
    }
    return null;
  }

  /* Everything that isn't the open line, hidden so it has the screen to itself.
     Walking up from the line covers the header, the other lines, the other
     items, the totals and the footer without naming any of them — the page it
     is walking is the cart, which changes shape with the customer's basket. */
  function hideAllButPath(fromEl) {
    var node = fromEl;
    while (node && node !== document.body) {
      var parent = node.parentElement;
      if (!parent) break;
      for (var i = 0; i < parent.children.length; i++) {
        var sib = parent.children[i];
        // The backdrop is what the line sits on, so it has to stay.
        if (sib === node || KEEP_TAGS[sib.tagName] || sib.id === "mobileTicketWindow") continue;
        core.hideWhileEditing(sib);
      }
      node = parent;
    }
  }

  function init() {
    var host = document.getElementById("leCartLineEditor");
    var form = document.getElementById("leCartLineForm");
    if (!host || !form) return;

    var wrapper = host.querySelector(".leLineWrapper");
    var section = host.querySelector("#tickets_section");
    var itemIdxEl = form.querySelector('input[name="item_idx"]');
    var lineIdxEl = form.querySelector('input[name="line_idx"]');
    if (!wrapper || !itemIdxEl || !lineIdxEl) return;

    var parkedNextTo = host.parentElement;
    var bySku = schemas();
    var open = null; // { lineEl, groups, line }

    function close() {
      core.closeLineEditor();
      host.classList.remove("is-open");
      if (parkedNextTo) parkedNextTo.appendChild(host);
      open = null;
    }

    function sync() {
      if (!open) return;
      core.updateLineUI(wrapper, open.groups, open.line);
      core.syncLineEditor();
    }

    function openFor(lineEl) {
      var code = String(lineEl.getAttribute("data-product-code") || "").trim().toUpperCase();
      var groups = bySku[code];
      if (!Array.isArray(groups) || !groups.length) return false;

      var slot = lineEl.querySelector(".leCartLineSlot");
      if (!slot) return false;

      var stored = {};
      try {
        stored = JSON.parse(lineEl.getAttribute("data-line-json") || "{}") || {};
      } catch (e) {
        stored = {};
      }

      close();
      open = {
        lineEl: lineEl,
        groups: groups,
        line: core.lineFromEditPayload(stored, groups)
      };
      itemIdxEl.value = String(lineEl.getAttribute("data-item-idx") || "");
      lineIdxEl.value = String(lineEl.getAttribute("data-line-idx") || "");

      core.renderGroupsInto(wrapper, groups, open.line);
      slot.appendChild(host);
      host.classList.add("is-open");

      if (core.isMobileEditorViewport()) {
        core.openLineEditor(wrapper, { section: section });
        hideAllButPath(host);
      }
      sync();
      return true;
    }

    function save() {
      if (!open) return;
      if (!core.isLineComplete(open.line, open.groups)) {
        core.syncLineEditor();
        return;
      }
      // /cart/update-line reads one field per group; the line keeps the shape
      // the CRM accepts (a single number, or a comma string).
      var payload = core.linePayload(open.line, open.groups);
      var existing = form.querySelectorAll('input[data-le-field="1"]');
      for (var i = 0; i < existing.length; i++) existing[i].parentNode.removeChild(existing[i]);
      Object.keys(payload).forEach(function (group) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = "field__" + group;
        input.value = String(payload[group]);
        input.setAttribute("data-le-field", "1");
        form.appendChild(input);
      });
      // The page furniture has to come back before the form takes the page with
      // it, or a cached back-navigation shows a half-hidden cart.
      core.restoreAfterEditing();
      form.submit();
    }

    // Edit buttons post to /play as a no-JS fallback; with the picker up, the
    // board opens here instead.
    var lines = document.querySelectorAll(".leCartLine");
    for (var i = 0; i < lines.length; i++) {
      (function (lineEl) {
        var summary = lineEl.querySelector(".leCartLineSummary");
        if (!summary) return;
        summary.addEventListener("click", function (ev) {
          var trigger = core.findActionEl(ev.target, summary);
          var isEdit = trigger && trigger.getAttribute("data-action") === "cart-edit";
          // A phone's whole row is the line, so tapping it opens the numbers —
          // except on the remove control, which must still submit.
          var isRow = !trigger && core.isMobileEditorViewport() && !closestEl(ev.target, ".cart-line-remove-btn");
          if (!isEdit && !isRow) return;
          if (openFor(lineEl)) {
            ev.preventDefault();
            try { ev.stopPropagation(); } catch (e) {}
          }
        });
      })(lines[i]);
    }

    host.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !open) return;

      var btn = core.findActionEl(t, host);
      if (btn) {
        ev.preventDefault();
        try { ev.stopPropagation(); } catch (e) {}
        var action = btn.getAttribute("data-action");
        if (action === "cancel") {
          close();
        } else if (action === "save") {
          save();
        } else if (action === "clear") {
          open.line = core.defaultEmptyLine(open.groups);
          sync();
        } else if (action === "quickpick") {
          open.line = core.quickPickLine(open.groups);
          sync();
        }
        return;
      }

      if (t.tagName === "LI" && t.getAttribute("data-num")) {
        var ul = t.parentElement;
        if (!ul) return;
        var group = ul.getAttribute("data-group");
        var count = parseInt(ul.getAttribute("data-count") || "0", 10) || 0;
        var num = parseInt(t.getAttribute("data-num") || "", 10);
        if (!group || isNaN(num)) return;
        open.line = core.toggleNumber(open.line, group, count, num);
        sync();
      }
    });

    // Keep the accordion's own toggle from collapsing the item under the editor.
    host.addEventListener("click", function (ev) {
      try { ev.stopPropagation(); } catch (e) {}
    });

    window.addEventListener("resize", function () {
      if (open && !core.isMobileEditorViewport()) {
        // Rotating to a wider viewport leaves the hidden page furniture
        // stranded; hand it back but keep the board expanded in place.
        core.closeLineEditor();
        host.classList.add("is-open");
      }
    });
    document.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.keyCode === 27) && open) close();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
