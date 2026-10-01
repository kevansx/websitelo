/*
 * Number picker for Marketing Module offer landing pages.
 *
 * A bundle is a fixed set of tickets that can span several lotteries, so every
 * board here is built from its own bundle item and the headers count across the
 * whole bundle. Winnow's page does neither — it takes one lottery for the page
 * and numbers each ticket on its own — which is why its SuperEnalotto + Mega
 * Millions + Powerball offer draws three Mega Millions boards labelled
 * "Ticket 1 of 1" three times.
 *
 * Requires window.LELineCore (line_editor_core.js), loaded first.
 */
(function () {
  var core = window.LELineCore;
  if (!core) return;

  /* Page furniture the full-screen editor hides on a phone, so the open board
     has the screen to itself. Same idea as the play page's list; the offer
     page's own chrome differs, and the site header and footer are shared. */
  var EDITOR_CHROME_SELECTOR = [
    ".navbar-default",
    ".verificationBanner",
    ".banner",
    "#cookie-prompt",
    "#cookieWarning",
    ".leOfferMasthead",
    ".leOfferHero",
    ".leOfferGames",
    ".leOfferAssurances",
    ".leOfferBuildHead",
    ".leOfferSummary",
    "footer"
  ].join(",");

  function readJson(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try {
      var parsed = JSON.parse(el.textContent || "null");
      return parsed === null || parsed === undefined ? fallback : parsed;
    } catch (e) {
      return fallback;
    }
  }

  function boot() {
    var host = document.getElementById("leOfferTickets");
    var tpl = document.getElementById("leLineTemplate");
    var form = document.getElementById("leOfferForm");
    if (!host || !tpl || !form) return;

    var tickets = readJson("leOfferTicketsJson", []);
    var products = readJson("leOfferProducts", []);
    if (!Array.isArray(tickets) || !tickets.length) return;

    var groupsByCode = {};
    (Array.isArray(products) ? products : []).forEach(function (p) {
      if (!p || !p.code) return;
      groupsByCode[String(p.code).toUpperCase()] = core.schemaGroups(p) || [];
    });

    var linesInput = document.getElementById("leOfferLinesJson");
    var submitBtn = document.getElementById("leOfferSubmit");
    var statusEl = document.getElementById("leOfferStatus");

    var state = tickets.map(function (t) {
      var groups = groupsByCode[String((t && t.product_code) || "").toUpperCase()] || [];
      return { ticket: t || {}, groups: groups, line: core.defaultEmptyLine(groups), el: null };
    });

    function refresh() {
      var outstanding = 0;
      state.forEach(function (s) {
        if (s.el) core.updateLineUI(s.el, s.groups, s.line);
        var done = s.groups.length && core.isLineComplete(s.line, s.groups);
        if (!done) outstanding++;
        // The card carries the state as well as the board, so a customer
        // scanning a twelve-ticket offer can see which ones still need numbers
        // without reading every grid.
        if (s.card) {
          if (done) s.card.classList.add("isComplete");
          else s.card.classList.remove("isComplete");
        }
        if (s.stateEl) s.stateEl.textContent = done ? "Ready" : "Pick numbers";
      });

      if (linesInput) {
        linesInput.value = JSON.stringify(
          state.map(function (s) {
            return core.linePayload(s.line, s.groups);
          })
        );
      }
      var closed = !!(submitBtn && submitBtn.hasAttribute("data-offer-closed"));
      if (submitBtn) submitBtn.disabled = closed || outstanding > 0;
      if (closed) {
        if (statusEl) statusEl.textContent = "This offer has ended.";
      } else if (statusEl) {
        statusEl.textContent = outstanding
          ? "Choose numbers for " + outstanding + " more ticket" + (outstanding === 1 ? "" : "s") + "."
          : "";
      }
      core.syncLineEditor();
    }

    function make(tag, className, text) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (text) node.textContent = text;
      return node;
    }

    /* What the board in front of them is asking for, read off the schema rather
       than a per-game table that would go stale the day the CRM adds a
       lottery. */
    function boardSummary(groups) {
      return (groups || [])
        .map(function (g) {
          // The extra group's range is on the grid's own label a few lines down,
          // so repeating it here only costs the header a second line.
          return g.name === "main"
            ? "Pick " + g.count + " of " + g.min + "-" + g.max
            : "+" + g.count + " " + g.name;
        })
        .join(", ");
    }

    function openEditor(wrapper) {
      if (!core.isMobileEditorViewport()) return;
      core.openLineEditor(wrapper, { chromeSelector: EDITOR_CHROME_SELECTOR, section: host });
      // The other cards have to go too, not just their boards: hiding the
      // boards alone would leave a column of empty bordered shells behind the
      // editor. This runs after openLineEditor because that closes any open
      // editor first, which restores everything hidden so far.
      var cards = document.querySelectorAll(".leOfferTicket");
      for (var i = 0; i < cards.length; i++) {
        if (!cards[i].contains(wrapper)) core.hideWhileEditing(cards[i]);
      }
    }

    function attach(s, index) {
      var el = s.el;
      el.addEventListener("click", function (ev) {
        var target = ev.target;
        if (!target) return;

        var action = core.findActionEl(target, el);
        if (action) {
          ev.preventDefault();
          try { ev.stopPropagation(); } catch (e) {}
          var name = action.getAttribute("data-action");
          if (name === "edit") {
            openEditor(el);
            return;
          }
          if (name === "done" || name === "close-editor") {
            core.closeLineEditor();
            return;
          }
          if (name === "clear") {
            s.line = core.defaultEmptyLine(s.groups);
            refresh();
            return;
          }
          if (name === "quickpick") {
            s.line = core.quickPickLine(s.groups);
            refresh();
            return;
          }
          return;
        }

        // On a phone the collapsed row is the whole ticket, so tapping it
        // anywhere opens the numbers rather than doing nothing.
        if (core.isMobileEditorViewport() && !el.classList.contains("showTicket")) {
          openEditor(el);
          return;
        }

        if (target.tagName === "LI" && target.getAttribute("data-num")) {
          var grid = target.parentElement;
          if (!grid) return;
          var group = grid.getAttribute("data-group");
          var count = parseInt(grid.getAttribute("data-count") || "0", 10) || 0;
          var num = parseInt(target.getAttribute("data-num") || "", 10);
          if (!group || isNaN(num)) return;
          s.line = core.toggleNumber(s.line || {}, group, count, num);
          refresh();
        }
      });
      el.setAttribute("data-line-index", String(index));
    }

    state.forEach(function (s, index) {
      var ticket = s.ticket || {};
      var card = make("article", "leOfferTicket");
      var head = make("div", "leOfferTicketHead");

      if (ticket.logo_url) {
        var logo = make("img", "leOfferTicketLogo");
        logo.src = ticket.logo_url;
        logo.alt = "";
        head.appendChild(logo);
      }

      var text = make("div", "leOfferTicketText");
      text.appendChild(
        make(
          "p",
          "leOfferTicketCount",
          "Ticket " + (ticket.position || index + 1) + " of " + (ticket.total || state.length)
        )
      );
      var name = String(ticket.game_name || ticket.product_code || "").trim();
      if (name) text.appendChild(make("p", "leOfferTicketGame", name));
      var summary = boardSummary(s.groups);
      if (summary) text.appendChild(make("p", "leOfferTicketBoard", summary));
      head.appendChild(text);

      s.stateEl = make("span", "leOfferTicketState", "Pick numbers");
      head.appendChild(s.stateEl);
      card.appendChild(head);

      // A multi-draw bundle is still one board. Saying how long it runs for is
      // the whole difference between "one ticket" and "twelve draws".
      if (ticket.schedule) {
        card.appendChild(make("p", "leOfferTicketSchedule", ticket.schedule));
      }

      var frag = tpl.content.cloneNode(true);
      var wrapper = frag.querySelector(".leLineWrapper");
      if (!wrapper) return;
      card.appendChild(frag);
      host.appendChild(card);

      s.card = card;
      s.el = wrapper;
      core.renderGroupsInto(wrapper, s.groups, s.line);
      attach(s, index);
    });

    var quickPickAll = document.getElementById("leOfferQuickPickAll");
    if (quickPickAll) {
      quickPickAll.addEventListener("click", function (ev) {
        ev.preventDefault();
        state.forEach(function (s) {
          s.line = core.quickPickLine(s.groups);
        });
        refresh();
      });
    }

    window.addEventListener("resize", function () {
      if (!core.isMobileEditorViewport()) core.closeLineEditor();
    });

    refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
