/* LottosOnline play page: the layer on top of the engine picker (play_picker.js).
 *
 *  - "How many lines?" chips (3 / 5 / 7 / 10 / 15 / 25, after theLotter) and "Pick my own numbers" (our wording),
 *    on the same page: they call window.LOPicker, which updates the engine's state, so the cart payload is
 *    unchanged.
 *  - Slot-reel quick pick (after theLotter): each ball holds a strip of 6-8 numbers that slides up, overshoots
 *    3px and settles, 1.05-1.3s each, cubic-bezier(.21,.62,.42,.9), so the balls land one after another.
 *  - Price per line on the right of each line (after LottoGo).
 *  - Desktop: lines are compact rows; Edit opens that line's number grid in place (phones use the engine's
 *    full-screen editor).
 *  - Sticky total bar on phones (after theLotter): "Total (5 lines) EUR 26.00  [Play Now]".
 * Respects prefers-reduced-motion. No dependencies.
 */
(function () {
  "use strict";
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var MOBILE = function () { return window.innerWidth <= 767; };
  var EASE = "cubic-bezier(0.21, 0.62, 0.42, 0.9)";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function groupRange(isBonus) {
    var groups = (window.LOPicker && window.LOPicker.groups()) || [];
    var g = groups.filter(function (x) { return isBonus ? x.name !== "main" : x.name === "main"; })[0];
    return g ? [parseInt(g.min, 10) || 1, parseInt(g.max, 10) || 49] : [1, 49];
  }

  /* ---- slot reel ---- */
  function reelBall(ball, delayMs) {
    var finalText = ball.textContent;
    if (!finalText || ball.querySelector(".lo-reel")) return;
    var isBonus = ball.classList.contains("bonusTicketNumber");
    var range = groupRange(isBonus);
    var n = 6 + Math.floor(Math.random() * 3);               // 6..8 numbers in the strip
    var strip = document.createElement("span");
    strip.className = "lo-reel";
    for (var i = 0; i < n - 1; i++) {
      var p = document.createElement("span");
      p.textContent = String(range[0] + Math.floor(Math.random() * (range[1] - range[0] + 1)));
      strip.appendChild(p);
    }
    var last = document.createElement("span");
    last.textContent = finalText;
    strip.appendChild(last);
    var size = ball.getBoundingClientRect().height || 30;
    strip.style.setProperty("--reel-to", (-(n - 1) * size) + "px");
    strip.style.setProperty("--reel-size", size + "px");
    var durMs = Math.round((1.05 + Math.random() * 0.25) * 1000);
    strip.style.animation = "lo-reel " + durMs + "ms " + EASE + " " + (delayMs || 0) + "ms both";
    ball.textContent = "";
    ball.classList.add("lo-reeling");
    ball.appendChild(strip);
    var done = false;
    function settle() {
      if (done) return;
      done = true;
      ball.classList.remove("lo-reeling");
      ball.textContent = finalText;
    }
    strip.addEventListener("animationend", settle, { once: true });
    // Safety net: a background tab never runs the animation, so never leave a ball without its number.
    setTimeout(settle, durMs + (delayMs || 0) + 150);
  }

  function animateLine(lineEl, lineDelay) {
    if (REDUCED || !lineEl) return;
    $all("#choosenNumber > span", lineEl).forEach(function (ball) { reelBall(ball, lineDelay || 0); });
  }

  function animateLines(detail) {
    // run after the engine has re-rendered the chosen numbers
    setTimeout(function () {
      var lines = $all("#linesContainer .leLineWrapper");
      if (detail && typeof detail.index === "number") {
        animateLine(lines[detail.index], 0);
      } else {
        lines.forEach(function (l, i) { animateLine(l, Math.min(i, 8) * 60); });
      }
      decorateLines();
    }, 16);
  }

  /* ---- per-line price + desktop edit/done buttons ---- */
  function priceText() {
    var p = window.LOPicker && window.LOPicker.unitPrice();
    if (!p || isNaN(p.cents)) return "";
    return window.LOPicker.currencySymbol(p.currency) + (p.cents / 100).toFixed(2);
  }

  function decorateLines() {
    var price = priceText();
    $all("#linesContainer .leLineWrapper").forEach(function (w, i) {
      var upper = $("#upperTicketSection", w);
      if (!upper) return;
      var num = $(".lo-linenum", upper);
      if (!num) {
        num = document.createElement("span");
        num.className = "lo-linenum";
        upper.insertBefore(num, upper.firstChild);
      }
      num.textContent = String(i + 1);
      var tag = $(".lo-lineprice", upper);
      if (!tag) {
        tag = document.createElement("span");
        tag.className = "lo-lineprice";
        upper.appendChild(tag);
      }
      tag.textContent = price;
      var web = $("#webUpperTicketSection", w);
      if (web && !$("[data-lo-edit]", web)) {
        var edit = document.createElement("button");
        edit.type = "button";
        edit.setAttribute("data-lo-edit", "");
        edit.className = "lo-iconaction";
        edit.setAttribute("aria-label", "Edit numbers");
        edit.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
        web.insertBefore(edit, web.firstChild);
      }
    });
    syncChips();
  }

  function setEditing(wrapper, on) {
    $all("#linesContainer .leLineWrapper.lo-editing").forEach(function (w) { if (w !== wrapper) w.classList.remove("lo-editing"); });
    if (wrapper) wrapper.classList.toggle("lo-editing", on);
  }

  /* ---- chips ---- */
  function syncChips() {
    var n = window.LOPicker ? window.LOPicker.lineCount() : 0;
    $all("[data-lo-lines]").forEach(function (c) {
      c.setAttribute("aria-pressed", String(parseInt(c.getAttribute("data-lo-lines"), 10) === n));
    });
  }

  /* ---- sticky bar ---- */
  function syncBar() {
    var bar = $("#loStickyBar");
    if (!bar) return;
    var total = $("#leTotalAmount"), cur = $("#leCurrencySymbolTotal"), count = $("#linesDrawsCount");
    $("[data-lo-bar-total]", bar).textContent = (cur ? cur.textContent : "") + (total ? total.textContent : "0.00");
    var lines = count ? (count.textContent.match(/^(\d+)/) || [0, 0])[1] : 0;
    $("[data-lo-bar-lines]", bar).textContent = "Total (" + lines + (lines === "1" ? " line" : " lines") + ")";
    var btn = $("#placeBetButton");
    $("[data-lo-bar-play]", bar).disabled = btn ? btn.disabled : false;
  }

  function init() {
    if (!window.LOPicker) return;
    decorateLines();

    document.addEventListener("lopicker:quickpicked", function (e) { animateLines(e.detail || {}); });
    document.addEventListener("lopicker:own", function (e) {
      setTimeout(function () {
        decorateLines();
        var lines = $all("#linesContainer .leLineWrapper");
        var target = lines[(e.detail && typeof e.detail.index === "number") ? e.detail.index : 0];
        if (!MOBILE()) setEditing(target, true);
      }, 16);
    });

    // chips + own numbers + shuffle + add line
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      var chip = t.closest && t.closest("[data-lo-lines]");
      if (chip) { ev.preventDefault(); window.LOPicker.setLineCount(chip.getAttribute("data-lo-lines")); return; }
      if (t.closest && t.closest("[data-lo-own]")) { ev.preventDefault(); window.LOPicker.ownNumbers(); return; }
      if (t.closest && t.closest("[data-lo-shuffle-all]")) { ev.preventDefault(); window.LOPicker.shuffleAll(); return; }
      if (t.closest && t.closest("[data-lo-add-line]")) { ev.preventDefault(); window.LOPicker.addLine(true); return; }
      if (t.closest && t.closest("[data-lo-play]")) { ev.preventDefault(); var f = $("#singlePlayBetForm"); if (f) (f.requestSubmit ? f.requestSubmit() : f.submit()); return; }
    });

    // per-line controls inside the engine's line markup (capture: runs before the engine's own handler)
    var host = $("#linesContainer");
    host.addEventListener("click", function (ev) {
      var t = ev.target;
      var w = t.closest && t.closest(".leLineWrapper");
      if (!w) return;
      var lines = $all("#linesContainer .leLineWrapper");
      var idx = lines.indexOf(w);
      if (t.closest("[data-lo-edit]")) {
        ev.preventDefault(); ev.stopPropagation();
        setEditing(w, !w.classList.contains("lo-editing"));
        return;
      }
      var qp = t.closest('[data-action="quickpick"]');
      if (qp) { setTimeout(function () { animateLines({ index: idx }); }, 0); }
      var trash = t.closest('[data-action="trash"]');
      if (trash) { setTimeout(decorateLines, 0); }
      // a tap on a collapsed desktop row opens it
      if (!MOBILE() && !t.closest("button, a, li") && !w.classList.contains("lo-editing")) setEditing(w, true);
    }, true);

    // engine re-renders (number taps, refresh) can drop our decorations: put them back
    new MutationObserver(function () { decorateLines(); }).observe(host, { childList: true });

    var watch = ["#leTotalAmount", "#linesDrawsCount"].map(function (s) { return $(s); }).filter(Boolean);
    var mo = new MutationObserver(syncBar);
    watch.forEach(function (el) { mo.observe(el, { childList: true, characterData: true, subtree: true }); });
    var btn = $("#placeBetButton");
    if (btn) new MutationObserver(syncBar).observe(btn, { attributes: true, attributeFilter: ["disabled"] });
    syncBar();

    // first paint: the three default quick picks spin in
    animateLines({ all: true });
  }

  if (window.LOPicker) init();
  else document.addEventListener("lopicker:ready", init, { once: true });
})();
