/* Gift pack reveal. Authoritative spec: design/pack-handover/lottos-gift-pack/storyboard.md (frames 1-7, reduced
 * motion, accessibility) and card-pack.md (layers, coordinates). Coordinates are canvas px (1200x1600) read from
 * geometry.json, so redrawn artwork moves the animation with it.
 *
 * Server rules (build brief 3.2): the open request goes out as soon as the customer commits (grip, tap, Enter),
 * the card is revealed only when the server has answered AND the tear is complete, a failure reloads the page
 * (the pack is still sealed), and without JavaScript the Open button is a plain form POST.
 */
(function () {
  "use strict";
  var root = document.getElementById("loPack");
  if (!root) return;
  root.classList.add("js");
  var box = root.querySelector(".lo-pack__box");
  var tilt = root.querySelector(".lo-pack__tilt");
  var card = root.querySelector(".lo-pack__card");
  var live = root.querySelector(".lo-pack__live");
  var errorEl = root.querySelector(".lo-pack__error");
  var geo = JSON.parse(root.querySelector(".lo-pack__geometry").textContent);
  var W = geo.canvas[0], H = geo.canvas[1];
  var X0 = geo.tearLine[0][0], X1 = geo.pack.x1;                  // notch apex 252 -> right edge 970
  var GRIP_Y = 560, FAR_X = 552, RELEASE_P = 0.55;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) root.classList.add("is-reduced");

  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content ||
             ((root.querySelector('input[name="csrf_token"]') || {}).value || "");

  // ---------------------------------------------------------------- overlay close
  Array.prototype.forEach.call(root.querySelectorAll("[data-pack-close]"), function (b) {
    b.addEventListener("click", function () { root.setAttribute("hidden", ""); document.documentElement.style.overflow = ""; });
  });
  if (root.classList.contains("lo-pack--overlay")) document.documentElement.style.overflow = "hidden";

  if (root.getAttribute("data-state") !== "sealed") { settle(true); return; }

  // ---------------------------------------------------------------- state
  var tx = X0, phase = "rest";            // rest | grip | tearing | releasing | done
  var request = null, answer = null, tearDone = false;
  root.classList.add("is-sealed-rest");

  function p() { return Math.max(0, Math.min(1, (tx - X0) / (X1 - X0))); }
  function paint() {
    var pp = p();
    root.style.setProperty("--tx", (tx / W * 100).toFixed(3) + "%");
    root.style.setProperty("--rot", (tx > X0 + 0.5 ? -(4 + 18 * Math.min(1, 2.2 * pp)) : 0).toFixed(2) + "deg");
    root.style.setProperty("--interior", Math.min(1, 1.6 * pp).toFixed(3));
    root.classList.toggle("is-sealed-rest", tx <= X0 + 0.5);
  }
  function canvasPoint(e) {
    var r = box.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width * W, y: (e.clientY - r.top) / r.height * H };
  }
  function tween(from, to, ms, ease, step, done) {
    var t0 = performance.now();
    (function f(now) {
      var k = Math.min(1, (now - t0) / ms);
      step(from + (to - from) * ease(k));
      if (k < 1) requestAnimationFrame(f); else if (done) done();
    })(t0);
  }
  var linear = function (k) { return k; };
  var easeOut = function (k) { return 1 - Math.pow(1 - k, 3); };
  var easeInOut = function (k) { return k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; };

  // ---------------------------------------------------------------- server
  function openOnServer() {
    if (request) return request;
    request = fetch(root.getAttribute("data-open-url"), {
      method: "POST", credentials: "same-origin",
      headers: { "Accept": "application/json", "X-CSRF-Token": csrf, "Content-Type": "application/x-www-form-urlencoded" },
      body: "csrf_token=" + encodeURIComponent(csrf)
    }).then(function (r) { return r.json().then(function (d) { if (!r.ok || !d.ok) throw new Error(d.reason || r.status); return d; }); })
      .then(function (d) { answer = d; maybeReveal(); return d; })
      .catch(function () { fail(); });
    return request;
  }
  function fail() {
    if (errorEl) errorEl.hidden = false;
    // The pack is still sealed on the server: start again from a clean page.
    setTimeout(function () { window.location.reload(); }, 1800);
  }

  // ---------------------------------------------------------------- frame 1: resting
  function onHover(e) {
    if (phase !== "rest" || reduced) return;
    var r = box.getBoundingClientRect();
    var nx = ((e.clientX - r.left) / r.width - .5) * 2, ny = ((e.clientY - r.top) / r.height - .5) * 2;
    nx = Math.max(-1, Math.min(1, nx)); ny = Math.max(-1, Math.min(1, ny));
    tilt.style.transform = "rotateY(" + (nx * 7).toFixed(2) + "deg) rotateX(" + (-ny * 4.5).toFixed(2) + "deg)";
    root.style.setProperty("--sheen", (-nx * 30).toFixed(1) + "%");
  }
  var peekTimer = null;
  function peek() {
    if (phase !== "rest" || reduced || document.hidden) return;
    var t0 = performance.now();
    (function f(now) {
      if (phase !== "rest") return;
      var k = Math.min(1, (now - t0) / 700);
      tx = X0 + 70 * Math.sin(Math.PI * k); paint();
      if (k < 1) requestAnimationFrame(f); else { tx = X0; paint(); }
    })(t0);
  }
  if (!reduced) {
    root.addEventListener("pointermove", onHover);
    peekTimer = setInterval(peek, 3200);
  }

  // ---------------------------------------------------------------- frames 2-3: grip and tear
  var down = null, lastMoves = [];
  box.addEventListener("pointerdown", function (e) {
    if (phase !== "rest" || reduced) return;
    var c = canvasPoint(e);
    down = { x: c.x, y: c.y, sx: e.clientX, sy: e.clientY, moved: 0, far: c.x > FAR_X, grip: c.y < GRIP_Y };
    lastMoves = [{ t: performance.now(), x: c.x }];
    try { box.setPointerCapture(e.pointerId); } catch (err) {}
    if (down.grip) {
      phase = "grip"; root.classList.add("is-gripped");
      tilt.style.transform = "";
      openOnServer();                       // committed: ask the server now, reveal later
    }
  });
  box.addEventListener("pointermove", function (e) {
    if (!down) return;
    down.moved = Math.max(down.moved, Math.hypot(e.clientX - down.sx, e.clientY - down.sy));
    if (!down.grip) return;
    var c = canvasPoint(e);
    lastMoves.push({ t: performance.now(), x: c.x });
    var target = down.far ? X0 + (c.x - down.x) * 1.5 : c.x;
    // resistance, then give: the first 40 canvas px of foil move at 0.6x the finger
    var pulled = target - X0;
    if (pulled < 40 / 0.6) target = X0 + pulled * 0.6;
    if (target > tx) { tx = Math.min(X1, target); phase = "tearing"; paint(); }
    if (tx >= X1) release();
  });
  function pointerEnd() {
    if (!down) return;
    var d = down; down = null;
    if (d.moved < 6) { autoTear(); return; }  // a tap opens it too (WCAG 2.5.7)
    if (!d.grip) return;
    release();
  }
  box.addEventListener("pointerup", pointerEnd);
  box.addEventListener("pointercancel", pointerEnd);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (reduced) reducedOpen(); else autoTear(); }
  });
  var openBtn = root.querySelector(".lo-pack__openbtn");
  if (openBtn) openBtn.addEventListener("click", function (e) { e.preventDefault(); if (reduced) reducedOpen(); else autoTear(); });

  function release() {
    if (phase === "releasing" || phase === "done") return;
    root.classList.remove("is-gripped");
    if (p() >= RELEASE_P || tx >= X1) { finishTear(); return; }
    phase = "rest";
    var from = tx;                             // springs back, 220 ms cubic ease-out
    tween(from, X0, 220, easeOut, function (v) { tx = v; paint(); });
  }
  function autoTear() {
    if (phase === "releasing" || phase === "done") return;
    phase = "tearing"; openOnServer();
    var from = tx;
    tween(from, X1, 380, easeInOut, function (v) { tx = v; paint(); }, function () { finishTear(true); });
  }

  // ---------------------------------------------------------------- frames 4-7
  function finishTear(already) {
    phase = "releasing"; clearInterval(peekTimer);
    root.classList.remove("is-gripped"); root.classList.add("is-opening");
    var from = tx;
    tween(from, X1, already ? 1 : 120, linear, function (v) { tx = v; paint(); }, function () {
      tearDone = true; maybeReveal();
    });
  }
  function maybeReveal() {
    if (!tearDone || !answer || phase === "done") return;
    phase = "done";
    fillCard(answer.card);
    var peel = root.querySelector(".lo-pack__peel");
    var attached = root.querySelector(".lo-pack__strip--attached");
    if (attached) attached.style.visibility = "hidden";
    // frame 4: the strip pivots off its right end, flicks up, then falls
    peel.style.transformOrigin = "80.8% 24.8%";
    peel.animate([
      { transform: "rotate(" + getComputedStyle(root).getPropertyValue("--rot") + ")", opacity: 1 },
      { transform: "translate(2%,-7%) rotate(-30deg)", opacity: 1, offset: .28, easing: "ease-in" },
      { transform: "translate(16%,78%) rotate(46deg)", opacity: 0 }
    ], { duration: 420, fill: "forwards" });
    // frame 5: the card rises, the glow blooms, one sparkle burst
    var glow = root.querySelector(".lo-pack__glow"), sparkle = root.querySelector(".lo-pack__sparkle");
    setTimeout(function () {
      card.animate([{ transform: "translateY(0)" }, { transform: "translateY(-30%)" }],
        { duration: 380, easing: "cubic-bezier(.2,.9,.3,1.12)", fill: "forwards" });
      glow.animate([{ opacity: 0, transform: "scale(.8)" }, { opacity: 1, transform: "scale(1)" }],
        { duration: 420, easing: "ease-out", fill: "forwards" });
    }, 220 - 120);
    setTimeout(function () {
      sparkle.animate([{ opacity: 0, transform: "translateY(0) scale(.85)" }, { opacity: 1, offset: .4 },
        { opacity: 0, transform: "translateY(-7%) scale(1.1)" }], { duration: 600, fill: "forwards" });
    }, 260 - 120);
    // frame 6: the pack drops away, the card goes to centre stage at 270 CSS px
    setTimeout(function () {
      Array.prototype.forEach.call(root.querySelectorAll(".lo-pack__body, .lo-pack__shadow"), function (el) {
        el.animate([{ transform: "translateY(0)", opacity: 1 }, { transform: "translateY(22%)", opacity: 1, offset: .5 },
          { transform: "translateY(45%)", opacity: 0 }], { duration: 380, easing: "cubic-bezier(.5,0,.9,.5)", fill: "forwards" });
      });
      card.style.zIndex = 3;
      card.animate([{ transform: "translateY(-30%)" }, { transform: settleTransform() }],
        { duration: 420, easing: "cubic-bezier(.22,.85,.25,1.08)", fill: "forwards" });
    }, 580 - 120);
    // frame 7: settled
    setTimeout(function () {
      glow.animate([{ opacity: 1 }, { opacity: .45 }], { duration: 260, fill: "forwards" });
      settle(false);
    }, 1020 - 120);
  }

  function settleTransform() {
    // centre of the card (600, 844) to the centre of the visible stage, scaled to 270 CSS px wide
    var r = box.getBoundingClientRect();
    var stage = root.querySelector(".lo-pack__stage").getBoundingClientRect();
    var scale = 270 / (600 / W * r.width);
    var cx = r.left + r.width * 0.5, cy = r.top + r.height * (844 / H);
    var tyPx = (stage.top + stage.height * 0.46) - cy;
    var txPx = (stage.left + stage.width / 2) - cx;
    return "translate(" + txPx.toFixed(1) + "px," + tyPx.toFixed(1) + "px) scale(" + scale.toFixed(3) + ")";
  }
  function fillCard(c) {
    if (!c) return;
    var alert = root.querySelector("[data-pack-alert]");
    if (alert && answer && answer.game_code) {
      alert.setAttribute("data-game", answer.game_code);
      root.querySelector("[data-pack-alert-row]").hidden = false;
      var gn = root.querySelector('[data-card="game_name"]'); if (gn) gn.textContent = c.title || "";
    }
    ["title", "sub", "expiry"].forEach(function (k) {
      var el = root.querySelector('[data-card="' + k + '"]');
      if (el) el.textContent = c[k] || "";
    });
  }
  function settle(initial) {
    if (!initial) card.getAnimations().forEach(function (a) { a.commitStyles && a.commitStyles(); a.cancel(); });
    root.style.setProperty("--settle", settleTransform());
    root.classList.remove("is-opening", "is-gripped", "is-sealed-rest");
    root.classList.add("is-settled");
    var done = root.querySelector(".lo-pack__done"); if (done) done.hidden = false;
    var form = root.querySelector(".lo-pack__openform"); if (form) form.style.display = "none";
    if (!initial && answer && live) live.textContent = answer.announce || "";
    if (!initial) { card.style.transform = ""; try { card.focus({ preventScroll: true }); } catch (e) { card.focus(); } }
  }

  // ---------------------------------------------------------------- reduced motion: no sequence
  function reducedOpen() {
    if (phase === "done") return;
    phase = "releasing";
    openOnServer().then(function (d) {
      if (!d) return;
      phase = "done"; fillCard(d.card);
      root.style.setProperty("--tx", (X1 / W * 100) + "%");
      settle(false);
    });
  }
  if (reduced) {
    var hint = root.querySelector(".lo-pack__hint"); if (hint) hint.textContent = "Your gift is ready";
    box.addEventListener("click", reducedOpen);
  }
  // the gift's lottery is followed by default; unticking removes the alert, ticking again restores it
  var alertBox = root.querySelector("[data-pack-alert]");
  if (alertBox) alertBox.addEventListener("change", function () {
    var body = "csrf_token=" + encodeURIComponent(csrf) + "&game_code=" + encodeURIComponent(alertBox.getAttribute("data-game")) +
               "&action=" + (alertBox.checked ? "save" : "remove");
    fetch(alertBox.getAttribute("data-url"), { method: "POST", credentials: "same-origin",
      headers: { "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded" }, body: body });
  });
  window.addEventListener("resize", function () { if (root.classList.contains("is-settled")) root.style.setProperty("--settle", settleTransform()); });
})();
