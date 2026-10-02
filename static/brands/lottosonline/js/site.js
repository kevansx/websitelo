/* LottosOnline public pages: menu drawer, footer accordions, draw countdowns. No dependencies. */
(function () {
  "use strict";

  // Menu drawer (phones).
  var toggle = document.querySelector("[data-drawer-toggle]");
  var drawer = document.querySelector("[data-drawer]");
  if (toggle && drawer) {
    toggle.addEventListener("click", function () {
      var open = drawer.hasAttribute("hidden");
      if (open) drawer.removeAttribute("hidden"); else drawer.setAttribute("hidden", "");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Footer columns are open on desktop, collapsible on phones.
  var mq = window.matchMedia("(min-width: 900px)");
  function syncFooter() {
    document.querySelectorAll(".lo-footer__cols details").forEach(function (d, i) {
      if (mq.matches) d.setAttribute("open", ""); else if (i > 0) d.removeAttribute("open");
    });
  }
  syncFooter();
  if (mq.addEventListener) mq.addEventListener("change", syncFooter);

  // Countdowns. Two markups are supported:
  //   <span class="lo-countdown" data-until="<ISO UTC>">   (public pages)
  //   <span class="wl-countdown" data-remaining="<seconds>"> (engine pages)
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function parts(s) {
    var d = Math.floor(s / 86400); s %= 86400;
    var h = Math.floor(s / 3600); s %= 3600;
    var m = Math.floor(s / 60); s %= 60;
    return { d: d, h: h, m: m, s: s };
  }
  function fmt(sec) {
    var p = parts(sec);
    return (p.d ? p.d + (p.d === 1 ? " day " : " days ") : "") + pad(p.h) + "h " + pad(p.m) + "m " + pad(p.s) + "s";
  }
  var until = Array.prototype.slice.call(document.querySelectorAll(".lo-countdown[data-until]"));
  until.forEach(function (el) { el._t = Date.parse(el.getAttribute("data-until")); });
  var remaining = Array.prototype.slice.call(document.querySelectorAll(".wl-countdown[data-remaining]"));
  var started = Date.now();
  remaining.forEach(function (el) { el._r = parseInt(el.getAttribute("data-remaining"), 10); });

  function tick() {
    var now = Date.now();
    until.forEach(function (el) {
      if (isNaN(el._t)) return;
      var sec = Math.max(0, Math.round((el._t - now) / 1000));
      if (sec <= 0) { el.textContent = el.getAttribute("data-ended-label") || "Draw closed"; el.classList.add("lo-countdown--closed"); return; }
      el.textContent = fmt(sec);
      if (sec < 3600) el.classList.add("lo-countdown--final");
    });
    remaining.forEach(function (el) {
      if (isNaN(el._r)) return;
      var sec = Math.max(0, el._r - Math.round((now - started) / 1000));
      el.textContent = sec <= 0 ? (el.getAttribute("data-ended-label") || "Results pending") : fmt(sec);
    });
  }
  if (until.length || remaining.length) {
    tick();
    setInterval(function () { if (!document.hidden) tick(); }, 1000);
  }
})();

/* Show/hide password buttons. */
(function () {
  document.querySelectorAll("[data-pw-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-pw-toggle"));
      if (!input) return;
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });
})();

// Account menu (person icon): close on a click elsewhere or Escape.
(function () {
  var menu = document.querySelector("[data-acctmenu]");
  if (!menu) return;
  document.addEventListener("click", function (e) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
  });
})();
