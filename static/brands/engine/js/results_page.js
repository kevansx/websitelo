(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function parseJsonScript(id, fallback) {
    var el = byId(id);
    if (!el) return fallback;
    try {
      var parsed = JSON.parse(el.textContent || "");
      return parsed === undefined ? fallback : parsed;
    } catch (e) {
      return fallback;
    }
  }

  function toInt(n, fallback) {
    var i = parseInt(n, 10);
    return isNaN(i) ? fallback : i;
  }

  function fmt2(n) {
    var i = toInt(n, 0);
    return String(i).padStart(2, "0");
  }

  function fmtMoney(code, amount) {
    var c = String(code || "").trim().toUpperCase();
    var v = Number(amount || 0);
    if (!isFinite(v)) v = 0;
    return c + " " + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function ballHtml(n, isBonus) {
    return "<span class='resultsBall " + (isBonus ? "resultBonusNumber" : "resultNumber") + "'>" + fmt2(n) + "</span>";
  }

  function drawNumbersHtml(d) {
    if (!d || d.is_pending) return "Pending";
    var main = Array.isArray(d.main_numbers) ? d.main_numbers : [];
    var bonus = Array.isArray(d.bonus_numbers) ? d.bonus_numbers : [];
    var out = [];
    for (var i = 0; i < main.length; i++) out.push(ballHtml(main[i], false));
    for (var j = 0; j < bonus.length; j++) out.push(ballHtml(bonus[j], true));
    return out.join("");
  }

  function tierRowsHtml(d) {
    var tiers = Array.isArray(d.prize_tiers) ? d.prize_tiers : [];
    var out = [];
    for (var i = 0; i < tiers.length; i++) {
      var t = tiers[i] || {};
      out.push(
        "<div class='row'>" +
          "<div class='lrg-col resultsBreakdownDetails'>" + String(t.label || "") + "</div>" +
          "<div class='mid-col resultsBreakdownDetails'>" + String(t.tier_code || "") + "</div>" +
          "<div class='mid-col resultsBreakdownDetails resultsBreakdownWinners'>" + Number(t.winners_count || 0).toLocaleString() + "</div>" +
          "<div class='mid-col resultsBreakdownDetails'>" + fmtMoney(t.currency, t.prize_amount) + "</div>" +
          "<div class='mid-col resultsBreakdownDetails'>" + fmtMoney(t.currency, t.payout_amount) + "</div>" +
        "</div>"
      );
    }
    return out.join("");
  }

  function drawItemHtml(d) {
    return (
      "<div class='leResultsDrawItem'>" +
        "<div class='lotteryResultsColumns leResultsDrawHeader' data-draw-id='" + String(d.id || "") + "'>" +
          "<span class='lotteryResultsDate'>" + String(d.draw_date_label || "") + "</span>" +
          "<span class='lotteryResultsTotalPrizes'>" + fmtMoney(d.currency, d.total_prize_payout) + "</span>" +
          "<span class='lotteryResultsNumbers'>" + drawNumbersHtml(d) + "</span>" +
          "<span class='glyphicon glyphicon-triangle-bottom'></span>" +
        "</div>" +
        "<div class='leResultsDrawBody' style='display:none;'>" +
          "<div class='resultsBreakdown'>" +
            "<div class='row resultsBreakdownHeaders'>" +
              "<div class='lrg-col resultsBreakdownHeader'>Prize Structure</div>" +
              "<div class='mid-col resultsBreakdownHeader'>Prize Tier</div>" +
              "<div class='mid-col resultsBreakdownHeader resultsBreakdownWinners'>Winners</div>" +
              "<div class='mid-col resultsBreakdownHeader'>Prize Value</div>" +
              "<div class='mid-col resultsBreakdownHeader'>Prize Payout</div>" +
            "</div>" +
            tierRowsHtml(d) +
            "<div class='row resultsBreakdownTotals resultsBreakdownHeaders'>" +
              "<div class='lrg-col resultsBreakdownHeader'><div>Total</div></div>" +
              "<div class='mid-col resultsBreakdownHeader'><div></div></div>" +
              "<div class='mid-col resultsBreakdownHeader'><div>" + Number(d.total_winners_count || 0).toLocaleString() + "</div></div>" +
              "<div class='mid-col resultsBreakdownHeader'><div></div></div>" +
              "<div class='mid-col resultsBreakdownHeader'><div>" + fmtMoney(d.currency, d.total_prize_payout) + "</div></div>" +
            "</div>" +
          "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function initAccordion(host) {
    if (!host) return;
    host.addEventListener("click", function (ev) {
      var header = ev.target && ev.target.closest ? ev.target.closest("header") : null;
      if (!header || !host.contains(header)) return;
      var body = header.nextElementSibling;
      if (!body) return;
      var isOpen = header.classList.contains("active");
      if (isOpen) {
        header.classList.remove("active");
        body.style.display = "none";
        var icon0 = header.querySelector(".glyphicon");
        if (icon0) icon0.classList.remove("open");
      } else {
        header.classList.add("active");
        body.style.display = "inline-block";
        var icon1 = header.querySelector(".glyphicon");
        if (icon1) icon1.classList.add("open");
      }
    });
  }

  function init() {
    var gameCode = parseJsonScript("leResultsGameCode", "");
    var drawsHost = byId("leResultsDraws");
    var monthSelect = byId("selectedResultsDate");
    var checkerRules = parseJsonScript("leResultsCheckerRules", {});
    var pickerHost = byId("leResultsPickerHost");
    var clearBtn = byId("leResultsClearBtn");
    var checkBtn = byId("leResultsCheckBtn");
    var statusEl = byId("leResultsCheckStatus");
    var matchesHost = byId("leResultsMatches");
    if (!drawsHost || !gameCode) return;

    var state = {
      selectedMain: [],
      selectedBonus: [],
      draws: parseJsonScript("leResultsInitialDraws", []),
    };

    function syncButtons() {
      var mainCount = toInt(checkerRules && checkerRules.main && checkerRules.main.count, 0);
      var bonusCount = toInt(checkerRules && checkerRules.bonus && checkerRules.bonus.count, 0);
      var mainOk = mainCount > 0 && state.selectedMain.length === mainCount;
      var bonusOk = bonusCount < 1 || state.selectedBonus.length === bonusCount;
      var ready = mainOk && bonusOk;
      if (clearBtn) {
        if (state.selectedMain.length || state.selectedBonus.length) clearBtn.classList.remove("disabledState");
        else clearBtn.classList.add("disabledState");
      }
      if (checkBtn) {
        if (ready) checkBtn.classList.remove("disabledState");
        else checkBtn.classList.add("disabledState");
      }
      if (statusEl) {
        statusEl.textContent = ready ? "Ready to check numbers." : "";
      }
      var found = byId("resultsCheckNumberFound");
      if (found && !ready) {
        found.style.display = "none";
      }
    }

    function renderGroup(rule, selected, key) {
      if (!rule || !pickerHost) return;
      // Presentation lives in the stylesheet (LottosOnline: css/results.css); no inline colours here.
      var wrap = document.createElement("div");
      wrap.className = "lines";

      var p = document.createElement("p");
      var label = key === "main" ? "numbers" : (rule.label || "bonus number" + (toInt(rule.count, 0) === 1 ? "" : "s"));
      p.textContent = "Choose " + String(rule.count || 0) + " " + String(label);
      wrap.appendChild(p);

      var ul = document.createElement("ul");
      var min = toInt(rule.min, 1);
      var max = toInt(rule.max, min);
      var maxCount = toInt(rule.count, 0);
      for (var n = min; n <= max; n++) {
        var li = document.createElement("li");
        li.textContent = String(n);
        li.className = key === "main" ? "ticketNumber" : "bonusTicketNumber";
        if (selected.indexOf(n) >= 0) li.classList.add("selectedNumber");
        li.setAttribute("role", "button");
        li.setAttribute("tabindex", "0");
        li.setAttribute("data-key", key);
        li.setAttribute("data-num", String(n));
        li.addEventListener("click", function () {
          var k = this.getAttribute("data-key");
          var num = toInt(this.getAttribute("data-num"), 0);
          var arr = (k === "main" ? state.selectedMain : state.selectedBonus).slice();
          var idx = arr.indexOf(num);
          if (idx >= 0) arr.splice(idx, 1);
          else {
            if (arr.length >= maxCount) return;
            arr.push(num);
          }
          arr.sort(function (a, b) { return a - b; });
          if (k === "main") state.selectedMain = arr;
          else state.selectedBonus = arr;
          renderPicker();
          syncButtons();
        });
        ul.appendChild(li);
      }
      wrap.appendChild(ul);
      pickerHost.appendChild(wrap);
    }

    function renderPicker() {
      if (!pickerHost) return;
      pickerHost.innerHTML = "";
      renderGroup(checkerRules.main, state.selectedMain, "main");
      if (checkerRules.bonus) renderGroup(checkerRules.bonus, state.selectedBonus, "bonus");
    }

    function renderDraws(draws) {
      state.draws = Array.isArray(draws) ? draws : [];
      drawsHost.innerHTML = "";
      if (!state.draws.length) {
        drawsHost.innerHTML = "<p class='processOrderCopy' style='padding:10px 0;'>No draw results returned.</p>";
        return;
      }
      for (var i = 0; i < state.draws.length; i++) {
        var d = state.draws[i];
        var html =
          "<header>" +
            "<span class='glyphicon glyphicon-triangle-bottom'></span>" +
            "<div class='lotteryResultsColumns'>" +
              "<span class='lotteryResultsDate'>" + String(d.draw_date_label || "") + "</span>" +
              "<span class='lotteryResultsTotalPrizes'>" + fmtMoney(d.currency, d.total_prize_payout) + "</span>" +
              "<span class='lotteryResultsNumbers'>" + drawNumbersHtml(d) + "</span>" +
            "</div>" +
          "</header>" +
          "<div>" +
            "<div class='resultsBreakdown'>" +
              "<div class='row resultsBreakdownHeaders'>" +
                "<div class='lrg-col resultsBreakdownHeader'>Prize Structure</div>" +
                "<div class='mid-col resultsBreakdownHeader'>Prize Tier</div>" +
                "<div class='mid-col resultsBreakdownHeader resultsBreakdownWinners'>Winners</div>" +
                "<div class='mid-col resultsBreakdownHeader'>Prize Value</div>" +
                "<div class='mid-col resultsBreakdownHeader'>Prize Payout</div>" +
              "</div>" +
              tierRowsHtml(d) +
              "<div class='row resultsBreakdownTotals resultsBreakdownHeaders'>" +
                "<div class='lrg-col resultsBreakdownHeader'><div>Total</div></div>" +
                "<div class='mid-col resultsBreakdownHeader'><div></div></div>" +
                "<div class='mid-col resultsBreakdownHeader'><div>" + Number(d.total_winners_count || 0).toLocaleString() + "</div></div>" +
                "<div class='mid-col resultsBreakdownHeader'><div></div></div>" +
                "<div class='mid-col resultsBreakdownHeader'><div>" + fmtMoney(d.currency, d.total_prize_payout) + "</div></div>" +
              "</div>" +
            "</div>" +
          "</div>";
        drawsHost.insertAdjacentHTML("beforeend", html);
      }
    }

    function renderMatches(matches) {
      if (!matchesHost) return;
      matchesHost.innerHTML = "";
      var list = Array.isArray(matches) ? matches : [];
      if (!list.length) {
        matchesHost.innerHTML = "<p class='processOrderCopy'>No matches in this month's draws.</p>";
        var found0 = byId("resultsCheckNumberFound");
        if (found0) found0.style.display = "block";
        return;
      }
      for (var i = 0; i < list.length; i++) {
        var m = list[i] || {};
        var ul = document.createElement("ul");
        ul.className = "numbersFound";
        var liDate = document.createElement("li");
        liDate.className = "numberFoundDate";
        liDate.textContent = String(m.draw_date_label || "");
        ul.appendChild(liDate);

        var main = Array.isArray(m.matched_main) ? m.matched_main : [];
        for (var j = 0; j < main.length; j++) {
          var liM = document.createElement("li");
          liM.className = "resultsBall resultNumber";
          liM.textContent = fmt2(main[j]);
          ul.appendChild(liM);
        }
        var bonus = Array.isArray(m.matched_bonus) ? m.matched_bonus : [];
        for (var k = 0; k < bonus.length; k++) {
          var liB = document.createElement("li");
          liB.className = "resultsBall resultBonusNumber";
          liB.textContent = fmt2(bonus[k]);
          ul.appendChild(liB);
        }

        if (m.tier && m.tier.label) {
          var liTier = document.createElement("li");
          liTier.className = "processOrderCopy numberFoundTier";
          var t = m.tier;
          liTier.textContent = "Tier: " + String(t.label) + (t.prize_amount ? (" (" + fmtMoney(t.currency, t.prize_amount) + ")") : "");
          ul.appendChild(liTier);
        }
        matchesHost.appendChild(ul);
      }
      var found = byId("resultsCheckNumberFound");
      if (found) found.style.display = "block";
    }

    if (monthSelect) {
      monthSelect.addEventListener("change", function () {
        var month = String(monthSelect.value || "");
        var url = "/api/results/" + encodeURIComponent(gameCode) + "/month?month=" + encodeURIComponent(month);
        fetch(url, { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            renderDraws((data && data.draws) || []);
          })
          .catch(function () {});
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (clearBtn.classList.contains("disabledState")) return;
        state.selectedMain = [];
        state.selectedBonus = [];
        renderPicker();
        renderMatches([]);
        syncButtons();
      });
    }

    if (checkBtn) {
      checkBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (checkBtn.classList.contains("disabledState")) return;
        var payload = {
          month: monthSelect ? String(monthSelect.value || "") : "",
          main_numbers: state.selectedMain,
          bonus_numbers: state.selectedBonus,
        };
        fetch("/api/results/" + encodeURIComponent(gameCode) + "/check-numbers", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            renderMatches((data && data.matches) || []);
          })
          .catch(function () {
            if (statusEl) statusEl.textContent = "Could not check numbers right now.";
          });
      });
    }

    renderDraws(state.draws);
    initAccordion(drawsHost);
    renderPicker();
    syncButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

