/* Add to Home Screen + free Saturday Lotto ticket (see lo_homescreen.py and templates/lo/_install.html).
 *
 *  - Registers /sw.js (network only, no caching) so browsers offer installation.
 *  - Chrome/Edge/Android: keeps the beforeinstallprompt event and fires it from our "Add to home screen" button.
 *  - iPhone/iPad: shows the Share -> Add to Home Screen steps (Apple has no install API).
 *  - Opens by itself ~1.2s after load on phones and tablets only (never on a desktop computer),
 *    except on money/sign-up pages, when already installed, or within 7 days of "Not now".
 *  - When the page is running as the installed app: claims the free ticket once (POST /homescreen/claim) if
 *    logged in, or asks the customer to log in first.
 *  - [data-lo-install] anywhere opens the sheet (account card, menu item, order confirmation).
 */
(function () {
  "use strict";
  var sheet = document.getElementById("loInstall");
  if (!sheet) return;
  var toast = document.getElementById("loInstallToast");
  var KEY = "lo_install_snooze_until";
  var CLAIM_KEY = "lo_homescreen_claim_done";
  var deferred = null;

  var ua = navigator.userAgent || "";
  var isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var isAndroid = /Android/i.test(ua);
  // A desktop computer = a mouse that hovers. Phones and tablets have touch only (iPads are caught by isIOS).
  var isDesktop = !!(window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches);
  var isMobile = isIOS || isAndroid || !isDesktop;
  var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  if (standalone) document.documentElement.classList.add("lo-standalone");
  var INSTALLED = "lo_installed";
  try { if (standalone) localStorage.setItem(INSTALLED, "1"); } catch (e) {}

  var path = location.pathname;
  var QUIET = /^\/(cart|checkout|wallet|create-account|login|forgot-password|reset-password|set-password|verify-email|orders\/\d+\/refund)/;

  function store(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  function setMode(m) {
    Array.prototype.forEach.call(sheet.querySelectorAll(".lo-install__mode"), function (el) {
      if (el.getAttribute("data-mode") === m) el.removeAttribute("hidden"); else el.setAttribute("hidden", "");
    });
    sheet.setAttribute("data-current", m);
  }

  function pickMode() {
    if (standalone) return "login";
    if (deferred) return "prompt";
    if (isIOS) {
      // Chrome/Firefox on iOS put Share in the address bar; Safari puts it in the bottom toolbar (iPhone) or top (iPad)
      var where = sheet.querySelector("[data-ios-where]");
      if (where) where.textContent = /CriOS|FxiOS|EdgiOS/.test(ua) ? "next to the address bar" : (/iPad/.test(ua) || navigator.maxTouchPoints > 1 && !/iPhone/.test(ua) ? "at the top of the screen" : "at the bottom of the screen");
      return "ios";
    }
    if (isAndroid) return "menu";
    return null; // desktop browser that has not offered installation
  }

  function open(force) {
    var m = pickMode();
    if (!m) return false;
    if (!force && m === "menu" && !isMobile) return false;
    setMode(m);
    sheet.removeAttribute("hidden");
    document.documentElement.classList.add("lo-install-open");
    var first = sheet.querySelector(".lo-install__mode:not([hidden]) .lo-btn, .lo-install__x");
    if (first) setTimeout(function () { try { first.focus(); } catch (e) {} }, 50);
    return true;
  }
  function close() {
    sheet.setAttribute("hidden", "");
    document.documentElement.classList.remove("lo-install-open");
  }
  function snooze(days) { store(KEY, String(Date.now() + (days || 7) * 864e5)); close(); }
  // Any way of closing the box is an answer: x, the backdrop, Escape and "Not now" for 7 days; "Got it" (they
  // followed the steps, so it is very likely installed) for 30. It never comes back on the very next page.
  function dismiss() {
    var m = sheet.getAttribute("data-current");
    if (m === "push" && window.LOPush) window.LOPush.decline();
    if (m === "login") { try { sessionStorage.setItem("lo_install_login_seen", "1"); } catch (e) {} close(); return; }
    snooze(7);
  }

  function say(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.removeAttribute("hidden");
    setTimeout(function () { toast.setAttribute("hidden", ""); }, 6000);
  }

  // service worker (network only)
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {}); });
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (!sheet.hasAttribute("hidden")) setMode("prompt");
    else maybeAutoOpen();
  });
  window.addEventListener("appinstalled", function () {
    deferred = null;
    store(INSTALLED, "1");
    close();
    say(sheet.getAttribute("data-offer") === "1" && sheet.getAttribute("data-claimed") !== "1"
      ? "Added! Open LottosOnline from your home screen to collect your free ticket."
      : "Added to your home screen.");
  });

  sheet.addEventListener("click", function (e) {
    var t = e.target;
    var closer = t.closest("[data-lo-install-close]");
    if (closer) {
      // "Got it" under the steps: they have just added it, or know how. Leave them be for 30 days.
      if (closer.classList.contains("lo-btn")) { snooze(30); return; }
      dismiss();
      return;
    }
    if (t.closest("[data-lo-install-later]")) { dismiss(); return; }
    if (t.closest("[data-lo-install-go]") && deferred) {
      deferred.prompt();
      deferred.userChoice.then(function (r) { if (r && r.outcome !== "accepted") snooze(); deferred = null; }).catch(function () {});
    }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !sheet.hasAttribute("hidden")) dismiss(); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-lo-install]");
    if (!b) return;
    e.preventDefault();
    if (!open(true)) say("Use your browser's menu and choose “Install” or “Add to Home screen”.");
  });

  var autoTried = false;
  function maybeAutoOpen() {
    if (autoTried || standalone || QUIET.test(path)) return;
    if (read(INSTALLED) === "1") return;       // opened from the home-screen icon on this phone before
    var until = parseInt(read(KEY) || "0", 10);
    if (until && Date.now() < until) return;
    if (!isMobile) return;                     // phones and tablets only
    autoTried = true;
    // Android Chrome can say whether this site is already installed (manifest related_applications)
    var check = (navigator.getInstalledRelatedApps ? navigator.getInstalledRelatedApps() : Promise.resolve([]))
      .catch(function () { return []; });
    check.then(function (apps) {
      if (apps && apps.length) { store(INSTALLED, "1"); return; }
      setTimeout(function () { if (sheet.hasAttribute("hidden")) open(false); }, 1200);
    });
  }

  // running as the installed app: collect the free ticket once
  function claim() {
    if (!standalone || sheet.getAttribute("data-offer") !== "1" || sheet.getAttribute("data-claimed") === "1") return;
    if (read(CLAIM_KEY) === "1") return;
    if (sheet.getAttribute("data-logged-in") !== "1") {
      var seen = false;
      try { seen = sessionStorage.getItem("lo_install_login_seen") === "1"; } catch (e) {}
      if (!QUIET.test(path) && !seen) {
        try { sessionStorage.setItem("lo_install_login_seen", "1"); } catch (e) {}
        setMode("login"); sheet.removeAttribute("hidden");
      }
      return;
    }
    var meta = document.querySelector('meta[name="csrf-token"]');
    fetch("/homescreen/claim", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": meta ? meta.content : "", "X-Display-Mode": "standalone", "Content-Type": "application/json" },
      body: "{}"
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok) {
        store(CLAIM_KEY, "1");
        sheet.setAttribute("data-claimed", "1");
        setTimeout(offerPush, 2500);
        say(d.already ? "Your free Saturday Lotto ticket is already in your account."
          : d.pending ? "Thanks for adding LottosOnline! Your free Saturday Lotto ticket will appear in your account shortly."
          : "Your free Australia Saturday Lotto ticket is in your account. Good luck!");
      }
    }).catch(function () {});
  }

  // Notifications: asked here only (the installed app, after the ticket), never on a first visit, never again
  // by ourselves after a "no". The browser prompt follows the customer's tap on "Turn on alerts".
  function offerPush() {
    var P = window.LOPush;
    if (!standalone || !P || !P.available() || P.permission() !== "default" || P.declined()) return;
    if (sheet.getAttribute("data-logged-in") !== "1" || QUIET.test(path)) return;
    setMode("push"); sheet.removeAttribute("hidden");
  }
  sheet.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest("[data-lo-push-yes]")) return;
    window.LOPush.enable().then(function (ok) {
      close();
      say(ok ? "Alerts are on. We'll tell you when a jackpot you follow gets big." : "No problem: you can turn alerts on later from your account.");
    });
  });
  sheet.addEventListener("click", function (e) {
    // "Not now" on the notifications step is a "no": remembered, and not asked again by ourselves
    if (e.target.closest && e.target.closest("[data-lo-install-later]") && sheet.querySelector('[data-mode="push"]:not([hidden])') && window.LOPush) window.LOPush.decline();
  }, true);
  if (standalone && read(CLAIM_KEY) === "1") setTimeout(offerPush, 2500);

  if (document.readyState === "complete") { maybeAutoOpen(); claim(); }
  else window.addEventListener("load", function () { maybeAutoOpen(); claim(); });
})();
