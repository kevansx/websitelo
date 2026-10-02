/* Lotto Express — shared number-board engine
 *
 * The play page and the cart both let a customer pick numbers for one line, and
 * they must look and behave identically: the legacy stylesheet only dresses one
 * shape of markup (`.leLineWrapper > .lines`, grids under `#lowerTicketSection`,
 * the `.showTicket` full-screen state below 768px), so both pages render that
 * shape and share the logic here rather than growing a second picker.
 *
 * Exposed as window.LELineCore. Load before play_picker.js / cart_line_editor.js.
 */

(function () {
  var MOBILE_EDITOR_MAX_WIDTH = 767;

  function uniqSortedInts(arr) {
    var s = {};
    (arr || []).forEach(function (n) {
      var i = parseInt(n, 10);
      if (!isNaN(i)) s[i] = true;
    });
    return Object.keys(s)
      .map(function (k) { return parseInt(k, 10); })
      .sort(function (a, b) { return a - b; });
  }

  function toIntArray(v) {
    if (Array.isArray(v)) return uniqSortedInts(v);
    if (typeof v === "number") return uniqSortedInts([v]);
    if (typeof v === "string") {
      var parts = String(v).split(/[\s,]+/);
      var out = [];
      for (var i = 0; i < parts.length; i++) {
        if (!parts[i]) continue;
        var n = parseInt(parts[i], 10);
        if (!isNaN(n)) out.push(n);
      }
      return uniqSortedInts(out);
    }
    return [];
  }

  function pickRandomInts(min, max, count) {
    var chosen = {};
    var out = [];
    var limit = Math.max(1, (max - min + 1));
    if (count > limit) count = limit;
    while (out.length < count) {
      var n = Math.floor(Math.random() * limit) + min;
      if (chosen[n]) continue;
      chosen[n] = true;
      out.push(n);
    }
    out.sort(function (a, b) { return a - b; });
    return out;
  }

  function quickPickLine(groups) {
    var line = {};
    (groups || []).forEach(function (g) {
      line[g.name] = pickRandomInts(parseInt(g.min, 10), parseInt(g.max, 10), parseInt(g.count, 10));
    });
    return line;
  }

  function defaultEmptyLine(groups) {
    var obj = {};
    (groups || []).forEach(function (g) {
      obj[g.name] = [];
    });
    return obj;
  }

  /* A schema arrives as a list of groups, as {groups: [...]}, or as a map of
     name -> spec, depending on the tenant. */
  function schemaGroups(product) {
    var ls = product ? product.line_schema : null;
    if (Array.isArray(ls)) return ls;
    if (ls && typeof ls === "object") {
      if (Array.isArray(ls.groups)) return ls.groups;
      var out = [];
      Object.keys(ls).forEach(function (name) {
        var spec = ls[name];
        if (!spec || typeof spec !== "object") return;
        out.push({ name: name, min: spec.min, max: spec.max, count: spec.count });
      });
      return out;
    }
    return [];
  }

  function isLineComplete(line, groups) {
    try {
      for (var i = 0; i < groups.length; i++) {
        var g = groups[i];
        var sel = uniqSortedInts((line || {})[g.name] || []);
        if (sel.length !== parseInt(g.count, 10)) return false;
      }
      return true;
    } catch (e) {
      return false;
    }
  }

  /* A stored line arrives in whatever shape the CRM accepts — ints, arrays or
     comma strings — so normalise it before it drives a grid. */
  function lineFromEditPayload(rawLine, groups) {
    var line = defaultEmptyLine(groups);
    var src = (rawLine && typeof rawLine === "object") ? rawLine : {};
    (groups || []).forEach(function (g) {
      var vals = toIntArray(src[g.name]);
      var need = parseInt(g.count, 10) || 0;
      if (need > 0 && vals.length > need) vals = vals.slice(0, need);
      line[g.name] = vals;
    });
    return line;
  }

  /* The shape the CRM takes: one number for single-pick groups, a comma string
     otherwise. */
  function linePayload(line, groups) {
    var out = {};
    (groups || []).forEach(function (g) {
      var sel = uniqSortedInts((line || {})[g.name] || []);
      if (!sel.length) return;
      if ((parseInt(g.count, 10) || 0) === 1) out[g.name] = sel[0];
      else out[g.name] = sel.join(",");
    });
    return out;
  }

  // Readable names for bonus-ball groups, as each lottery calls them.
  var BONUS_NAMES = {
    powerball: "Powerball", megaball: "Mega Ball", mega: "Mega number", star: "Star Ball",
    stars: "Lucky Stars", euro: "Euro numbers", key: "Key number", "super": "Superzahl",
    chance: "Chance number", thunderball: "Thunderball", millionaire: "Millionaire Ball",
    bonus: "Bonus number", supplementary: "Supplementary"
  };
  function groupLabel(g) {
    var n = parseInt(g.count, 10) || 0;
    if (g.name === "main") return "Choose " + n + " number" + (n === 1 ? "" : "s");
    var name = BONUS_NAMES[g.name] || (String(g.name).charAt(0).toUpperCase() + String(g.name).slice(1));
    return "Choose " + n + " " + name;
  }

  function renderGroupsInto(lineEl, groups, lineState) {
    var holder = lineEl.querySelector(".leGroups");
    if (!holder) return;
    holder.innerHTML = "";

    groups.forEach(function (g) {
      var p = document.createElement("p");
      p.textContent = groupLabel(g);
      holder.appendChild(p);

      var ul = document.createElement("ul");
      ul.className = "leNumberGrid";
      ul.setAttribute("data-group", g.name);
      ul.setAttribute("data-min", String(g.min));
      ul.setAttribute("data-max", String(g.max));
      ul.setAttribute("data-count", String(g.count));
      holder.appendChild(ul);

      var min = parseInt(g.min, 10) || 1;
      var max = parseInt(g.max, 10) || min;
      for (var n = min; n <= max; n++) {
        var li = document.createElement("li");
        li.textContent = String(n);
        li.setAttribute("data-num", String(n));
        li.className = (g.name === "main") ? "ticketNumber" : "bonusTicketNumber";
        ul.appendChild(li);
      }
    });

    updateLineUI(lineEl, groups, lineState);
  }

  function updateLineUI(lineEl, groups, lineState) {
    var chosenEl = lineEl.querySelector("#choosenNumber");
    if (chosenEl) {
      chosenEl.innerHTML = "";
      groups.forEach(function (g) {
        var sel = uniqSortedInts((lineState || {})[g.name] || []);
        sel.forEach(function (n) {
          var sp = document.createElement("span");
          sp.className = (g.name === "main" ? "ticketNumber" : "bonusTicketNumber") + " selectedNumber";
          sp.textContent = String(n);
          chosenEl.appendChild(sp);
        });
      });
    }

    groups.forEach(function (g) {
      var sel = uniqSortedInts((lineState || {})[g.name] || []);
      var ul = lineEl.querySelector("ul.leNumberGrid[data-group=\"" + g.name + "\"]");
      if (!ul) return;
      var needed = parseInt(ul.getAttribute("data-count") || "0", 10) || 0;
      if (g.name === "main") {
        if (needed && sel.length === needed) ul.classList.add("availableNumbersComplete");
        else ul.classList.remove("availableNumbersComplete");
      } else {
        if (needed && sel.length === needed) ul.classList.add("availableBonusNumbersComplete");
        else ul.classList.remove("availableBonusNumbersComplete");
      }
      var lis = ul.querySelectorAll("li[data-num]");
      for (var i = 0; i < lis.length; i++) {
        var li = lis[i];
        var n = parseInt(li.getAttribute("data-num") || "", 10);
        if (sel.indexOf(n) >= 0) li.classList.add("selectedNumber");
        else li.classList.remove("selectedNumber");
      }
    });

    var complete = lineEl.querySelector(".ticketCompleteImage");
    var incomplete = lineEl.querySelector(".ticketIncompleteImage");
    var ok = isLineComplete(lineState, groups);
    var linesRoot = lineEl.querySelector(".lines");
    if (linesRoot) {
      if (ok) linesRoot.classList.add("ticketComplete");
      else linesRoot.classList.remove("ticketComplete");
    }
    if (complete) complete.style.display = ok ? "inline" : "none";
    if (incomplete) incomplete.style.display = ok ? "none" : "inline";
  }

  /* Toggling one number on a grid, with the legacy rule that a full group
     replaces its oldest pick rather than refusing the tap. */
  function toggleNumber(lineState, group, count, num) {
    var arr = uniqSortedInts((lineState || {})[group] || []);
    var pos = arr.indexOf(num);
    if (pos >= 0) {
      arr.splice(pos, 1);
    } else {
      if (count && arr.length >= count) arr.shift();
      arr.push(num);
    }
    lineState[group] = uniqSortedInts(arr);
    return lineState;
  }

  /* Full-screen line editor (mobile only)
   *
   * Below 768px the stylesheet collapses a line to a single row and hides
   * #lowerTicketSection, so the only way to change a selection is to open the
   * line over the page. The classes used here are the ones mobile.css already
   * styles for that state.
   */

  function isMobileEditorViewport() {
    try {
      var w = window.innerWidth || document.documentElement.clientWidth || 0;
      return w > 0 && w <= MOBILE_EDITOR_MAX_WIDTH;
    } catch (e) {
      return false;
    }
  }

  function hideWhileEditing(el) {
    if (!el || el.getAttribute("data-le-hidden") !== null) return;
    el.setAttribute("data-le-hidden", el.style.display || "");
    el.style.display = "none";
  }

  function restoreAfterEditing() {
    var hidden = document.querySelectorAll("[data-le-hidden]");
    for (var i = 0; i < hidden.length; i++) {
      var el = hidden[i];
      // An empty value hands display back to the stylesheet, so nothing that was
      // already hidden (an undismissed cookie prompt, a verified account banner)
      // gets revealed on the way out.
      el.style.display = el.getAttribute("data-le-hidden") || "";
      el.removeAttribute("data-le-hidden");
    }
  }

  function openLineEditor(lineEl, opts) {
    if (!lineEl || !isMobileEditorViewport()) return;
    closeLineEditor();
    var o = opts || {};

    if (o.siblingSelector) {
      var siblings = document.querySelectorAll(o.siblingSelector);
      for (var i = 0; i < siblings.length; i++) {
        if (siblings[i] !== lineEl) hideWhileEditing(siblings[i]);
      }
    }
    if (o.chromeSelector) {
      var chrome = document.querySelectorAll(o.chromeSelector);
      for (var j = 0; j < chrome.length; j++) hideWhileEditing(chrome[j]);
    }

    lineEl.classList.add("showTicket");
    var section = o.section || document.getElementById("tickets_section");
    if (section) section.classList.add("mobileLinesSection");
    var backdrop = document.getElementById("mobileTicketWindow");
    if (backdrop) backdrop.style.display = "block";
    document.body.classList.add("leEditingLine");
    try { window.scrollTo(0, 0); } catch (e) {}
    syncLineEditor();
  }

  function closeLineEditor() {
    var open = document.querySelector(".leLineWrapper.showTicket");
    if (open) open.classList.remove("showTicket");
    restoreAfterEditing();
    var sections = document.querySelectorAll(".mobileLinesSection");
    for (var i = 0; i < sections.length; i++) sections[i].classList.remove("mobileLinesSection");
    var backdrop = document.getElementById("mobileTicketWindow");
    if (backdrop) {
      backdrop.style.display = "none";
      backdrop.classList.remove("mobileTicketWindowComplete");
    }
    document.body.classList.remove("leEditingLine");
  }

  function syncLineEditor() {
    var open = document.querySelector(".leLineWrapper.showTicket");
    var backdrop = document.getElementById("mobileTicketWindow");
    if (backdrop) {
      if (open && open.querySelector(".lines.ticketComplete")) {
        backdrop.classList.add("mobileTicketWindowComplete");
      } else {
        backdrop.classList.remove("mobileTicketWindowComplete");
      }
    }
    if (!open) return;
    var clearBtn = open.querySelector("#mobileUpperTicketSection .clearButton");
    if (clearBtn) {
      if (open.querySelector(".leGroups .selectedNumber")) clearBtn.classList.remove("unclickableButton");
      else clearBtn.classList.add("unclickableButton");
    }
  }

  /* The control a tap landed on, so a click on an icon inside a button still
     resolves to the button's action. */
  function findActionEl(startNode, stopNode) {
    var n = startNode;
    while (n && n !== stopNode) {
      try {
        if (typeof n.getAttribute === "function" && n.getAttribute("data-action")) return n;
      } catch (e) {}
      n = n.parentElement;
    }
    return null;
  }

  window.LELineCore = {
    MOBILE_EDITOR_MAX_WIDTH: MOBILE_EDITOR_MAX_WIDTH,
    uniqSortedInts: uniqSortedInts,
    toIntArray: toIntArray,
    pickRandomInts: pickRandomInts,
    quickPickLine: quickPickLine,
    defaultEmptyLine: defaultEmptyLine,
    schemaGroups: schemaGroups,
    isLineComplete: isLineComplete,
    lineFromEditPayload: lineFromEditPayload,
    linePayload: linePayload,
    renderGroupsInto: renderGroupsInto,
    updateLineUI: updateLineUI,
    toggleNumber: toggleNumber,
    isMobileEditorViewport: isMobileEditorViewport,
    hideWhileEditing: hideWhileEditing,
    restoreAfterEditing: restoreAfterEditing,
    openLineEditor: openLineEditor,
    closeLineEditor: closeLineEditor,
    syncLineEditor: syncLineEditor,
    findActionEl: findActionEl
  };
})();
