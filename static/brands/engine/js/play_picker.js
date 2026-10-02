/* Number picker (engine shared with Lotto Express; LottosOnline draw days and time zones added)
 *
 * - Reads product `line_schema` from a JSON script tag rendered by Flask
 * - Renders legacy-compatible markup (tickets_section / lines / available numbers)
 * - Builds `lines_json` + `options_json` and posts to /cart/add (Flask)
 *
 * This intentionally does NOT call any legacy PHP endpoints.
 */

(function () {
  var DEFAULT_LINES_ON_LOAD = 3;
  var MAX_WEEKS = 52;

  // The number boards, and the full-screen state they open into on a phone, are
  // shared with the cart's line editor (line_editor_core.js) so the two pages
  // cannot drift apart.
  var core = window.LELineCore || {};
  var uniqSortedInts = core.uniqSortedInts;
  var pickRandomInts = core.pickRandomInts;
  var quickPickLine = core.quickPickLine;
  var defaultEmptyLine = core.defaultEmptyLine;
  var schemaGroups = core.schemaGroups;
  var isLineComplete = core.isLineComplete;
  var lineFromEditPayload = core.lineFromEditPayload;
  var renderGroupsInto = core.renderGroupsInto;
  var updateLineUI = core.updateLineUI;
  var isMobileEditorViewport = core.isMobileEditorViewport;
  var closeLineEditor = core.closeLineEditor;
  var syncLineEditor = core.syncLineEditor;

  function currencySymbol(code) {
    var c = String(code || "").trim().toUpperCase();
    var map = { USD: "$", EUR: "€", GBP: "£", AUD: "A$", CAD: "C$", NZD: "NZ$", JPY: "¥", ZAR: "R" };
    return map[c] || (c || "€");
  }

  function fmtMoney(cents, currencyCode) {
    var n = parseInt(cents || 0, 10);
    if (isNaN(n)) n = 0;
    var v = (n / 100).toFixed(2);
    return { symbol: currencySymbol(currencyCode), amount: v };
  }

  function addDaysUtc(d, days) {
    var out = new Date(d.getTime());
    out.setUTCDate(out.getUTCDate() + days);
    return out;
  }

  function timeZoneForGame(gameCode) {
    var g = String(gameCode || "").toLowerCase();
    // Keep this intentionally small and brand-specific.
    // Note: CRM provides cutoff timestamps in UTC; weekday labels should match the lottery's local timezone.
    if (g === "megamillions") return "America/New_York";
    if (g === "powerball") return "America/New_York";
    if (g === "euromillions" || g === "euromillions-at") return "Europe/Vienna"; // Austrian game: 18:30 Vienna cut-off
    if (g === "lotto-fr") return "Europe/Paris";
    if (g === "eurojackpot") return "Europe/Berlin";
    if (g === "australianpowerball") return "Australia/Sydney";
    if (g === "sat-lotto-au") return "Australia/Sydney";
    if (g === "oz-lotto-au") return "Australia/Sydney";
    if (g === "superenalotto") return "Europe/Rome";
    if (g === "lotto-6aus49") return "Europe/Berlin";
    if (g === "lotto-ie") return "Europe/Dublin";
    if (g === "powerball-au" || g === "weekday-windfall-au") return "Australia/Sydney";
    if (g === "superlotto-plus-ca-us") return "America/Los_Angeles";
    if (g === "lotto-america") return "America/Chicago";
    if (g === "millionaire-for-life") return "America/New_York"; // daily, cut-off 10:15 PM ET
    if (g === "el-gordo-primitiva" || g === "la-primitiva" || g === "bonoloto") return "Europe/Madrid";
    if (g === "thunderball" || g === "lotto-uk") return "Europe/London";
    return "UTC";
  }

  function weekdayIndexInTz(dateObj, timeZone) {
    // Returns 0..6 where 0=Sunday in the given timezone.
    try {
      var wd = new Intl.DateTimeFormat("en-US", { weekday: "long", timeZone: timeZone }).format(dateObj);
      var map = { Sunday: 0, Monday: 1, Tuesday: 2, Wednesday: 3, Thursday: 4, Friday: 5, Saturday: 6 };
      return (map.hasOwnProperty(wd) ? map[wd] : dateObj.getUTCDay());
    } catch (e) {
      return dateObj.getUTCDay();
    }
  }

  function fmtWeekdayInTz(dateObj, timeZone) {
    try {
      return new Intl.DateTimeFormat("en-US", { weekday: "long", timeZone: timeZone }).format(dateObj);
    } catch (e) {
      return "";
    }
  }

  function fmtShortDateInTz(dateObj, timeZone) {
    try {
      return new Intl.DateTimeFormat("en-US", { month: "short", day: "2-digit", year: "numeric", timeZone: timeZone }).format(dateObj);
    } catch (e) {
      // Fallback to UTC-ish string.
      var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      return months[dateObj.getUTCMonth()] + " " + String(dateObj.getUTCDate()).padStart(2, "0") + " " + dateObj.getUTCFullYear();
    }
  }

  function nextDrawsFromCutoff(baseUtcDate, timeZone, desiredWeekdaysLocal, nWanted) {
    var out = [];
    var seen = {};
    var d = new Date(baseUtcDate.getTime());
    for (var i = 0; i < 40 && out.length < nWanted; i++) {
      var wd = weekdayIndexInTz(d, timeZone);
      if (desiredWeekdaysLocal.indexOf(wd) >= 0 && d.getTime() >= baseUtcDate.getTime()) {
        var t = d.getTime();
        if (!seen[t]) {
          seen[t] = true;
          out.push(new Date(t));
        }
      }
      d = addDaysUtc(d, 1);
    }
    if (!out.length) out.push(new Date(baseUtcDate.getTime()));
    out.sort(function (a, b) { return a.getTime() - b.getTime(); });
    return out.slice(0, nWanted);
  }

  function daysUntilUtc(now, future) {
    var ms = future.getTime() - now.getTime();
    var d = Math.ceil(ms / (24 * 3600 * 1000));
    if (d < 0) d = 0;
    return d;
  }

  // Legacy-style draw-day counter formatting (matches the old react.js behavior for drawdateshort=1).
  function fmtLegacyShortCountdown(targetIso) {
    try {
      var t = new Date(String(targetIso)).getTime();
      if (isNaN(t)) return "To Be Announced";
      var now = Date.now();
      var diff = t - now;
      if (isNaN(diff) || diff < 0) diff = 0;
      var days = Math.floor(diff / (1000 * 60 * 60 * 24));
      var hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
      var minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      var seconds = Math.floor((diff % (1000 * 60)) / 1000);
      if (days > 1) return String(days) + " days";
      if (days === 1) return "1 day";
      return (
        String(hours) +
        ":" +
        (minutes > 9 ? "" : "0") +
        String(minutes) +
        ":" +
        (seconds > 9 ? "" : "0") +
        String(seconds)
      );
    } catch (e) {
      return "To Be Announced";
    }
  }

  function tickDrawDayCounters(drawDaysHost) {
    try {
      if (!drawDaysHost) return;
      var nodes = drawDaysHost.getElementsByClassName("drawDateCountdownCopy");
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (!el || !el.getAttribute) continue;
        var iso = el.getAttribute("data-drawdate");
        if (!iso) continue;
        el.textContent = fmtLegacyShortCountdown(iso);
      }
    } catch (e) {}
  }

  function getJackpot() {
    var el = document.getElementById("leJackpot");
    if (!el) return {};
    return safeParseJson(el.textContent || "{}", {});
  }

  // Website-known draw weekdays. CRM jackpots currently provide only next_cutoff_at_utc, not the full schedule.
  // We derive upcoming draw options from next_cutoff_at_utc + these weekdays.
  function drawWeekdaysForGame(gameCode) {
    var g = String(gameCode || "").toLowerCase();
    // JS Date.getUTCDay(): 0=Sun ... 6=Sat
    if (g === "megamillions") return [2, 5]; // Tue, Fri
    if (g === "powerball") return [1, 3, 6]; // Mon, Wed, Sat
    if (g === "euromillions" || g === "euromillions-at") return [2, 5]; // Tue, Fri
    if (g === "lotto-fr") return [1, 3, 6]; // Mon, Wed, Sat
    if (g === "eurojackpot") return [2, 5]; // Tue, Fri (commonly)
    if (g === "australianpowerball") return [4]; // Thu
    if (g === "sat-lotto-au") return [6]; // Sat
    if (g === "oz-lotto-au") return [2]; // Tue (Oz Lotto AU)
    if (g === "superenalotto") return [2, 4, 5, 6]; // Tue, Thu, Fri, Sat (Friday draw since 2021)
    if (g === "lotto-6aus49") return [3, 6]; // Wed, Sat
    if (g === "lotto-ie") return [3, 6]; // Wed, Sat
    // LottosOnline lotteries (official draw days, in the lottery's own time zone)
    if (g === "powerball-au") return [4]; // Thu
    if (g === "superlotto-plus-ca-us") return [3, 6]; // Wed, Sat
    if (g === "lotto-america") return [1, 3, 6]; // Mon, Wed, Sat
    if (g === "el-gordo-primitiva") return [0]; // Sun
    if (g === "la-primitiva") return [1, 4, 6]; // Mon, Thu, Sat
    if (g === "bonoloto") return [1, 2, 3, 4, 5, 6]; // Mon to Sat
    if (g === "thunderball") return [2, 3, 5, 6]; // Tue, Wed, Fri, Sat
    if (g === "weekday-windfall-au") return [1, 3, 5]; // Mon, Wed, Fri
    if (g === "millionaire-for-life") return [0, 1, 2, 3, 4, 5, 6]; // every day (CRM reply, 2 Oct 2026)
    return []; // unknown
  }

  function safeParseJson(text, fallback) {
    try {
      var v = JSON.parse(text);
      return v === undefined ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  function fmtGroupSelection(name, nums) {
    if (!nums || !nums.length) return "";
    if (nums.length === 1) return name + ": " + nums[0];
    return name + ": " + nums.join(",");
  }

  function getProducts() {
    var el = document.getElementById("lePickerProducts");
    if (!el) return [];
    return safeParseJson(el.textContent || "[]", []);
  }

  function getCartLineEdit() {
    var el = document.getElementById("leCartLineEdit");
    if (!el) return null;
    var v = safeParseJson(el.textContent || "{}", {});
    if (!v || typeof v !== "object") return null;
    // When not editing, the template renders "{}", which is truthy in JS and would
    // incorrectly disable the Add Line button. Only treat as edit context when
    // the expected fields are present.
    try {
      if (!Object.keys(v).length) return null;
    } catch (e) {}
    if (!v.product_code || !v.line) return null;
    return v;
  }

  function getDefaultCurrency() {
    var el = document.getElementById("leDefaultCurrency");
    if (!el) return "";
    return String(el.getAttribute("data-currency") || "").trim().toUpperCase();
  }

  // The CRM saves a retail price per display currency. Pairing a base-currency
  // amount with the customer's currency symbol quotes a price the cart will not
  // honour, so resolve the amount and its currency together.
  function priceForCurrency(priced, currency) {
    var wanted = String(currency || "").trim().toUpperCase();
    var map = priced && priced.prices_by_currency;
    if (!wanted || !map || typeof map !== "object") return null;
    var entry = map[wanted];
    if (!entry || entry.amount_cents == null) return null;
    var cents = parseInt(entry.amount_cents, 10);
    if (isNaN(cents)) return null;
    return { cents: cents, currency: wanted };
  }

  function findProduct(products, code) {
    for (var i = 0; i < products.length; i++) {
      if ((products[i].code || "") === code) return products[i];
    }
    return null;
  }

  function buildLinesPayload(lines, groups) {
    var payload = [];
    for (var i = 0; i < lines.length; i++) {
      var src = lines[i] || {};
      // Keep payload aligned with the displayed total: only submit complete lines.
      if (!isLineComplete(src, groups)) continue;
      var out = {};
      (groups || []).forEach(function (g) {
        var sel = uniqSortedInts(src[g.name] || []);
        if (!sel.length) return;
        if ((g.count || 0) === 1) out[g.name] = sel[0];
        else out[g.name] = sel.join(",");
      });
      payload.push(out);
    }
    return payload;
  }

  /* Page furniture the full-screen editor hides on a phone, so the open line
     has the screen to itself. The editor itself lives in line_editor_core.js. */
  var EDITOR_CHROME_SELECTOR = [
    ".navbar-default",
    ".verificationBanner",
    "#lotteryTabs",
    ".banner",
    "#cookie-prompt",
    "#cookieWarning",
    ".howToPlay",
    ".lotteryBanners",
    "#lotteryHeaders",
    ".ticketSectionFeatures",
    "#addLine",
    ".singleOrderDetails",
    ".lotteryDetails",
    "#lotteryPageCopy",
    "#placeBetButton",
    "footer",
    ".lo-hide-when-editing"
  ].join(",");

  function openLineEditor(lineEl) {
    core.openLineEditor(lineEl, {
      siblingSelector: "#linesContainer .leLineWrapper",
      chromeSelector: EDITOR_CHROME_SELECTOR
    });
  }

  function attachLineHandlers(lineEl, state) {
    lineEl.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t) return;

      // Controls (handle clicks on inner <img> too)
      var btn = core.findActionEl(t, lineEl);
      if (btn) {
        ev.preventDefault();
        try { ev.stopPropagation(); } catch (e) {}
        var action = btn.getAttribute("data-action");
        var idx2 = parseInt(lineEl.getAttribute("data-line-index") || "0", 10) || 0;
        if (action === "edit") {
          openLineEditor(lineEl);
          return;
        }
        if (action === "done" || action === "close-editor") {
          closeLineEditor();
          return;
        }
        if (action === "clear") {
          state.lines[idx2] = defaultEmptyLine(state.groups);
          state.refresh();
          return;
        }
        if (action === "quickpick") {
          state.lines[idx2] = quickPickLine(state.groups);
          state.refresh();
          return;
        }
        if (action === "trash") {
          if (state.lines.length <= 1) {
            state.lines[0] = defaultEmptyLine(state.groups);
          } else {
            state.lines.splice(idx2, 1);
          }
          state.rebuildLines();
          state.refresh();
          return;
        }
        return;
      }

      // On a phone the collapsed row is the whole line, so tapping it anywhere
      // opens the numbers rather than doing nothing.
      if (isMobileEditorViewport() && !lineEl.classList.contains("showTicket")) {
        openLineEditor(lineEl);
        return;
      }

      // Number selection
      if (t.tagName === "LI" && t.getAttribute("data-num")) {
        var ul = t.parentElement;
        if (!ul) return;
        var group = ul.getAttribute("data-group");
        var count = parseInt(ul.getAttribute("data-count") || "0", 10) || 0;
        var num = parseInt(t.getAttribute("data-num") || "", 10);
        if (!group || isNaN(num)) return;

        var idx = parseInt(lineEl.getAttribute("data-line-index") || "0", 10) || 0;
        state.lines[idx] = core.toggleNumber(state.lines[idx] || {}, group, count, num);
        state.refresh();
        return;
      }
    });
  }

  function renderAddons(addons, state) {
    var host = document.getElementById("leAddons");
    if (!host) return;
    host.innerHTML = "";
    if (!Array.isArray(addons) || !addons.length) return;

    var title = document.createElement("p");
    title.className = "formLabels";
    title.textContent = "Add-ons";
    host.appendChild(title);

    addons.forEach(function (a) {
      if (!a || !a.code) return;
      var wrap = document.createElement("label");
      wrap.style.display = "block";
      wrap.style.cursor = "pointer";

      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!state.options[a.code];
      cb.addEventListener("change", function () {
        state.options[a.code] = !!cb.checked;
        state.refresh();
      });
      wrap.appendChild(cb);

      var txt = document.createElement("span");
      var price = "";
      try {
        var shown = priceForCurrency(a, state.defaultCurrency);
        if (!shown && a.pricing && a.pricing.amount_cents != null && a.pricing.currency) {
          shown = { cents: parseInt(a.pricing.amount_cents, 10), currency: a.pricing.currency };
        }
        if (shown && !isNaN(shown.cents)) {
          price = " (+" + (shown.cents / 100).toFixed(2) + " " + shown.currency + " per line)";
        }
      } catch (e) {}
      txt.textContent = " " + (a.label || a.code) + price;
      wrap.appendChild(txt);
      host.appendChild(wrap);
    });
  }

  function init() {
    var products = getProducts();
    var lineEdit = getCartLineEdit();
    var sel = document.getElementById("leProductCode"); // can be <select> or <input type="hidden">
    var linesHost = document.getElementById("linesContainer");
    var tpl = document.getElementById("leLineTemplate");
    var linesJsonEl = document.getElementById("leLinesJson");
    var optionsJsonEl = document.getElementById("leOptionsJson");
    var countCopyEl = document.getElementById("linesDrawsCount");
    var submitBtn = document.getElementById("placeBetButton");
    var unitAmountEl = document.getElementById("leLinesDrawsAmount");
    var totalAmountEl = document.getElementById("leTotalAmount");
    var currencyEl = document.getElementById("leCurrencySymbol");
    var currencyEl2 = document.getElementById("leCurrencySymbolTotal");
    var drawDaysHost = document.getElementById("leDrawDays");
    var jackpot = getJackpot();
    var weeksMinus = document.getElementById("leWeeksMinus");
    var weeksPlus = document.getElementById("leWeeksPlus");
    var weeksInputEl = document.getElementById("weekCount");
    var weeksUnitEl = document.getElementById("subscriptionWeekCopy");

    if (!sel || !linesHost || !tpl || !linesJsonEl || !optionsJsonEl) return;

    function getSelectedProductCode() {
      try {
        if (sel.tagName === "SELECT") return sel.value;
        return sel.value || sel.getAttribute("value") || "";
      } catch (e) {
        return "";
      }
    }

    var state = {
      productCode: getSelectedProductCode(),
      product: null,
      defaultCurrency: getDefaultCurrency() || "EUR",
      lineEdit: lineEdit,
      groups: [],
      lines: [],
      options: {},
      weeks: 1,
      selectedWeekdays: {}, // weekday idx string -> bool
      refresh: function () {
        // Update all line UIs
        var lineEls = linesHost.querySelectorAll(".leLineWrapper");
        for (var i = 0; i < lineEls.length; i++) {
          var le = lineEls[i];
          var idx = parseInt(le.getAttribute("data-line-index") || "0", 10) || 0;
          updateLineUI(le, state.groups, state.lines[idx] || {});
        }
        syncLineEditor();

        // Update hidden fields
        var payloadLines = buildLinesPayload(state.lines, state.groups);
        linesJsonEl.value = JSON.stringify(payloadLines);
        // Persist week/draw-day selection in options_json (safe: CRM will ignore unknown keys if unsupported).
        var optOut = {};
        try {
          for (var kk in (state.options || {})) {
            if ((state.options || {}).hasOwnProperty(kk)) optOut[kk] = (state.options || {})[kk];
          }
        } catch (e) {}

        // Counts + pricing
        var completeLines = 0;
        for (var iC = 0; iC < state.lines.length; iC++) {
          if (isLineComplete(state.lines[iC], state.groups)) completeLines += 1;
        }

        var weekdayCount = 0;
        if (state.selectedWeekdays) {
          for (var k in state.selectedWeekdays) {
            if (state.selectedWeekdays.hasOwnProperty(k) && state.selectedWeekdays[k]) weekdayCount += 1;
          }
        }
        var w = parseInt(state.weeks || 1, 10);
        if (isNaN(w) || w < 1) w = 1;
        if (w > MAX_WEEKS) w = MAX_WEEKS;
        var drawsSelected = weekdayCount * w;
        // LottosOnline duration picker (brief 2, part 4): without the old draw-day/weeks controls the draws come
        // from the chosen duration: 1 draw, a tier of N draws, or a tier of N weeks (2-3 draws a week, so a range).
        var drawsRange = null;
        if (!drawDaysHost) {
          var dur = state.duration || { draws: 1 };
          if (dur.weeks) { drawsRange = [dur.weeks * 3 - 1, dur.weeks * 3]; drawsSelected = drawsRange[1]; }
          else { drawsSelected = dur.draws || 1; }
        }
        optOut._weeks = w;
        optOut._draw_weekdays = Object.keys(state.selectedWeekdays || {}).filter(function (x) { return state.selectedWeekdays[x]; });
        optionsJsonEl.value = JSON.stringify(optOut);

        var baseCurrency = (state.product && (state.product.base_currency || state.product.currency)) || "EUR";
        var unitPrice = priceForCurrency(state.product, state.defaultCurrency);
        var prodCurrency = unitPrice ? unitPrice.currency : baseCurrency;
        var unitPerLineCents = 0;
        if (unitPrice) {
          unitPerLineCents = unitPrice.cents;
        } else if (state.product && state.product.price_in_base_cents != null) {
          unitPerLineCents = parseInt(state.product.price_in_base_cents, 10);
        }
        // a multi-draw tier: its own locked price, never a percentage worked out here (the CRM rounds half-up)
        if (state.duration && state.duration.cents != null) {
          unitPerLineCents = parseInt(state.duration.cents, 10);
        }
        if (isNaN(unitPerLineCents)) unitPerLineCents = 0;

        var addonPerLineCents = 0;
        try {
          var addons = (state.product && state.product.addons) || [];
          if (Array.isArray(addons)) {
            addons.forEach(function (a) {
              if (!a || !a.code) return;
              if (!state.options[a.code]) return;
              var addonPrice = priceForCurrency(a, prodCurrency);
              if (addonPrice) {
                addonPerLineCents += addonPrice.cents;
                return;
              }
              if (a.pricing && a.pricing.unit === "per_line" && a.pricing.amount_cents != null) {
                var ac = parseInt(a.pricing.amount_cents, 10);
                if (!isNaN(ac)) addonPerLineCents += ac;
              }
            });
          }
        } catch (e) {}

        // Legacy behavior: show 0.00 if no complete lines or no draws selected.
        var itemSubtotalCents = 0;
        var totalCents = 0;
        if (completeLines > 0 && drawsSelected > 0) {
          itemSubtotalCents = completeLines * drawsSelected * unitPerLineCents;
          totalCents = completeLines * drawsSelected * (unitPerLineCents + addonPerLineCents);
        }

        if (currencyEl) currencyEl.textContent = currencySymbol(prodCurrency);
        if (currencyEl2) currencyEl2.textContent = currencySymbol(prodCurrency);
        if (unitAmountEl) unitAmountEl.textContent = (itemSubtotalCents / 100).toFixed(2);
        if (totalAmountEl) totalAmountEl.textContent = (totalCents / 100).toFixed(2);
        if (drawsRange && completeLines > 0) {
          // charged for the draws actually in the window: 8 or 9 for 3 weeks of a three-a-week lottery
          var lowCents = completeLines * drawsRange[0] * (unitPerLineCents + addonPerLineCents);
          if (unitAmountEl) unitAmountEl.textContent = (lowCents / 100).toFixed(2) + "–" + (totalCents / 100).toFixed(2);
          if (totalAmountEl) totalAmountEl.textContent = (lowCents / 100).toFixed(2) + "–" + (totalCents / 100).toFixed(2);
        }

        // Lines x Draws copy
        if (countCopyEl) {
          var n = completeLines;
          var dN = drawsSelected || 0;
          countCopyEl.textContent = (state.duration && state.duration.weeks)
            ? n + (n === 1 ? " Line" : " Lines") + " x " + state.duration.weeks + (state.duration.weeks === 1 ? " week" : " weeks")
            : n + (n === 1 ? " Line" : " Lines") + " x " + dN + (dN === 1 ? " Draw" : " Draws");
        }

        // Disable submit until all lines are complete (legacy behavior).
        if (submitBtn) {
          var anyOk = completeLines > 0 && drawsSelected > 0;
          // legacy enables only when at least one complete line exists (and draws chosen)
          submitBtn.disabled = !anyOk;
        }
      },
      rebuildLines: function () {
        // The open line is about to be replaced, so the page has to come back
        // before its markup disappears.
        closeLineEditor();
        linesHost.innerHTML = "";
        for (var i = 0; i < state.lines.length; i++) {
          var html = (tpl.innerHTML || "").replace(/__IDX__/g, String(i));
          var tmp = document.createElement("div");
          tmp.innerHTML = html;
          var lineEl = tmp.firstElementChild;
          if (!lineEl) continue;
          lineEl.setAttribute("data-line-index", String(i));
          renderGroupsInto(lineEl, state.groups, state.lines[i]);
          attachLineHandlers(lineEl, state);
          linesHost.appendChild(lineEl);
        }
      },
      setProduct: function (code) {
        state.productCode = code;
        state.product = findProduct(products, code);
        state.groups = schemaGroups(state.product);
        if (!Array.isArray(state.groups) || !state.groups.length) {
          // Fallback to simple 5-of-50 if schema missing (better than blank UI).
          state.groups = [{ name: "main", min: 1, max: 50, count: 5 }];
        }
        var editingThisLine = !!(
          state.lineEdit &&
          state.lineEdit.product_code &&
          String(state.lineEdit.product_code) === String(code)
        );
        if (editingThisLine) {
          state.lines = [lineFromEditPayload(state.lineEdit.line, state.groups)];
        } else {
          // LottosOnline: open on the lottery's minimum lines (#leMinLines), so the first order is a valid one
          var minEl = document.getElementById("leMinLines");
          var nLines = parseInt((minEl && minEl.value) || DEFAULT_LINES_ON_LOAD, 10);
          if (isNaN(nLines) || nLines < 1) nLines = 1;
          state.lines = [];
          // Land on a playable ticket: the customer edits or clears from there.
          for (var i = 0; i < nLines; i++) state.lines.push(quickPickLine(state.groups));
        }
        state.options = {};
        renderAddons((state.product && state.product.addons) || [], state);
        state.setDrawOptions();
        state.rebuildLines();
        state.refresh();
      },
      setDrawOptions: function () {
        if (!drawDaysHost) return;
        drawDaysHost.innerHTML = "";
        state.selectedWeekdays = {};

        var nextCutoff = (jackpot && (jackpot.cutoff_at_utc || jackpot.next_draw_utc)) || null;
        var gameCode = (state.product && state.product.game_code) || (jackpot && jackpot.game_code) || "";
        var weekdays = drawWeekdaysForGame(gameCode);
        var tz = timeZoneForGame(gameCode);

        // CRM timestamps may omit a trailing Z; treat as UTC.
        var base = nextCutoff ? new Date(String(nextCutoff).replace("Z", "") + "Z") : null;
        if (base && isNaN(base.getTime())) base = null;

        if (base && !weekdays.length) {
          // A game missing from the map above renders a page nobody can buy
          // from: no day to tick is no draws, which is a total of 0.00 and a
          // dead Play button, with nothing on screen to say why. The cutoff
          // names one real draw, so offer that. Fewer days than the lottery
          // actually holds, but a working page, and adding the game above
          // restores the rest.
          weekdays = [weekdayIndexInTz(base, tz)];
        }

        if (!base || !weekdays.length) {
          // Fallback: show a single non-interactive option so layout matches.
          var sp = document.createElement("span");
          sp.textContent = "Next draw";
          drawDaysHost.appendChild(sp);
          return;
        }
        // Show one option per weekday (legacy UI), while duration controls how many weeks are included.
        var options = [];
        weekdays.forEach(function (wd) {
          var next = nextDrawsFromCutoff(base, tz, [wd], 1)[0];
          options.push({ wd: wd, dt: next });
        });
        options.sort(function (a, b) { return a.dt.getTime() - b.dt.getTime(); });
        var defaultW = options.length ? options[0].wd : weekdays[0];

        options.forEach(function (opt, idx) {
          var wd = opt.wd;
          var d = opt.dt;
          var lab = document.createElement("label");
          lab.className = "checkboxRadioContainer";

          var cb = document.createElement("input");
          cb.type = "checkbox";
          cb.value = String(wd);
          cb.checked = (wd === defaultW);
          state.selectedWeekdays[String(wd)] = cb.checked;
          cb.addEventListener("change", function () {
            state.selectedWeekdays[String(wd)] = !!cb.checked;
            state.refresh();
          });
          lab.appendChild(cb);

          var day = document.createElement("span");
          day.className = "drawDayOfWeek";
          day.textContent = fmtWeekdayInTz(d, tz);
          lab.appendChild(day);

          var date = document.createElement("span");
          date.className = "drawDate";
          // Legacy: show "Starting " only when duration > 1 week.
          var starting = document.createElement("span");
          starting.className = "drawDateStarting";
          starting.style.display = (parseInt(state.weeks || 1, 10) > 1 ? "inline" : "none");
          starting.textContent = "Starting ";
          date.appendChild(starting);
          date.appendChild(document.createTextNode(fmtShortDateInTz(d, tz)));
          lab.appendChild(date);

          var clock = document.createElement("img");
          clock.className = "drawDateCountdown drawDateCountdownClock";
          clock.setAttribute("src", "/resources/images/drawCountdownClock.svg");
          clock.setAttribute("width", "14");
          clock.setAttribute("height", "14");
          lab.appendChild(clock);

          // Legacy countdown text (clock + "1 day" / "X days" / "HH:MM:SS")
          var counter = document.createElement("span");
          counter.className = "drawDateCountdown drawDateCountdownCopy";
          counter.setAttribute("data-drawdate", d.toISOString());
          counter.textContent = fmtLegacyShortCountdown(d.toISOString());
          lab.appendChild(counter);

          var cm = document.createElement("span");
          cm.className = "redesignCheckmark";
          lab.appendChild(cm);

          drawDaysHost.appendChild(lab);
        });
        // Keep the countdown text updated every second (small number of nodes).
        try {
          if (window.__leDrawDayTicker) window.clearInterval(window.__leDrawDayTicker);
        } catch (e) {}
        tickDrawDayCounters(drawDaysHost);
        try {
          window.__leDrawDayTicker = window.setInterval(function () {
            tickDrawDayCounters(drawDaysHost);
          }, 1000);
        } catch (e) {}
      }
    };

    function renderWeeks() {
      var w = parseInt(state.weeks || 1, 10);
      if (isNaN(w) || w < 1) w = 1;
      if (w > MAX_WEEKS) w = MAX_WEEKS;
      state.weeks = w;
      if (weeksInputEl) weeksInputEl.value = String(w);
      if (weeksUnitEl) weeksUnitEl.textContent = (w === 1 ? "Week" : "Weeks");

      // Legacy: fade minus button at 1 week.
      try {
        if (weeksMinus) {
          if (w <= 1) weeksMinus.classList.add("fadeoutCounter");
          else weeksMinus.classList.remove("fadeoutCounter");
        }
      } catch (e) {}

      // Legacy: toggle "Starting" prefix in draw-day rows.
      try {
        if (drawDaysHost) {
          var starts = drawDaysHost.getElementsByClassName("drawDateStarting");
          for (var iS = 0; iS < starts.length; iS++) {
            starts[iS].style.display = (w > 1 ? "inline" : "none");
          }
        }
      } catch (e) {}
    }

    function setWeeks(w) {
      state.weeks = w;
      renderWeeks();
      state.refresh();
    }

    if (weeksMinus) {
      weeksMinus.addEventListener("click", function (ev) {
        ev.preventDefault();
        setWeeks(Math.max(1, (parseInt(state.weeks || 1, 10) || 1) - 1));
      });
    }
    if (weeksPlus) {
      weeksPlus.addEventListener("click", function (ev) {
        ev.preventDefault();
        setWeeks(Math.min(MAX_WEEKS, (parseInt(state.weeks || 1, 10) || 1) + 1));
      });
    }

    // Product selection changes schema
    if (sel.tagName === "SELECT") {
      sel.addEventListener("change", function () {
        state.setProduct(getSelectedProductCode());
      });
    }

    // Add line / add quick pick
    var addLine = document.getElementById("addLine");
    if (addLine) {
      addLine.addEventListener("click", function (ev) {
        if (state.lineEdit) {
          ev.preventDefault();
          return;
        }
        ev.preventDefault();
        // The mobile card reads "Add Quick Pick", so give it numbers; on desktop
        // the new line is picked in place.
        state.lines.push(
          isMobileEditorViewport() ? quickPickLine(state.groups) : defaultEmptyLine(state.groups)
        );
        state.rebuildLines();
        state.refresh();
      });
    }

    // Global clear/quickpick buttons (legacy IDs)
    var clearAll = document.getElementById("clearAll");
    if (clearAll) {
      clearAll.addEventListener("click", function (ev) {
        ev.preventDefault();
        // Legacy behavior: "Clear All" clears selected numbers, but does NOT remove lines/tickets.
        if (!state.lines || !state.lines.length) {
          state.lines = [defaultEmptyLine(state.groups)];
        } else {
          for (var i3 = 0; i3 < state.lines.length; i3++) {
            state.lines[i3] = defaultEmptyLine(state.groups);
          }
        }
        state.refresh();
      });
    }
    var qpAll = document.getElementById("quickPickAll");
    if (qpAll) {
      qpAll.addEventListener("click", function (ev) {
        ev.preventDefault();
        for (var i = 0; i < state.lines.length; i++) {
          state.lines[i] = quickPickLine(state.groups);
        }
        state.refresh();
      });
    }

    // A rotation into tablet/desktop width leaves the editor's hidden page
    // furniture stranded, so hand the page back at that point.
    window.addEventListener("resize", function () {
      if (!isMobileEditorViewport()) closeLineEditor();
    });
    document.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.keyCode === 27) && document.querySelector(".leLineWrapper.showTicket")) {
        closeLineEditor();
      }
    });

    // Kick off
    renderWeeks();
    state.setProduct(getSelectedProductCode());

    // Control surface for the LottosOnline play page (lo_picker_fx.js): line-count chips, shuffle all,
    // per-line shuffle, add line, own numbers. Every change goes through the same state + refresh as the
    // buttons above, so lines_json / options_json reach /cart/add exactly as before.
    function notify(name, detail) {
      try { document.dispatchEvent(new CustomEvent(name, { detail: detail || {} })); } catch (e) {}
    }
    window.LOPicker = {
      groups: function () { return state.groups; },
      lineCount: function () { return state.lines.length; },
      unitPrice: function () {
        var p = priceForCurrency(state.product, state.defaultCurrency);
        if (state.duration && state.duration.cents != null) {
          return { cents: parseInt(state.duration.cents, 10), currency: (p && p.currency) || (state.product && state.product.base_currency) || "EUR" };
        }
        if (p) return p;
        if (state.product && state.product.price_in_base_cents != null) {
          return { cents: parseInt(state.product.price_in_base_cents, 10), currency: state.product.base_currency || "EUR" };
        }
        return null;
      },
      currencySymbol: currencySymbol,
      // LottosOnline duration picker: {cents, draws} or {cents, weeks}. Price and draws only: the lines stay.
      setDuration: function (d) {
        state.duration = d || null;
        state.refresh();
        notify("lopicker:duration", d || {});
      },
      setLineCount: function (n) {
        if (state.lineEdit) return;
        n = Math.max(1, Math.min(50, parseInt(n, 10) || 1));
        state.lines = [];
        for (var i = 0; i < n; i++) state.lines.push(quickPickLine(state.groups));
        state.rebuildLines();
        state.refresh();
        notify("lopicker:quickpicked", { all: true });
      },
      ownNumbers: function () {
        if (state.lineEdit) return;
        state.lines = [defaultEmptyLine(state.groups)];
        state.rebuildLines();
        state.refresh();
        notify("lopicker:own", {});
      },
      shuffleAll: function () {
        for (var i = 0; i < state.lines.length; i++) state.lines[i] = quickPickLine(state.groups);
        state.refresh();
        notify("lopicker:quickpicked", { all: true });
      },
      shuffleLine: function (idx) {
        if (idx < 0 || idx >= state.lines.length) return;
        state.lines[idx] = quickPickLine(state.groups);
        state.refresh();
        notify("lopicker:quickpicked", { index: idx });
      },
      addLine: function (quick) {
        if (state.lineEdit) return;
        state.lines.push(quick ? quickPickLine(state.groups) : defaultEmptyLine(state.groups));
        state.rebuildLines();
        state.refresh();
        notify(quick ? "lopicker:quickpicked" : "lopicker:own", { index: state.lines.length - 1 });
      }
    };
    notify("lopicker:ready", {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

