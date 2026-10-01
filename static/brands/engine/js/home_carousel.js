// Homepage lotteries scroller (robust replacement for legacy index.js lottery slider).
// Uses transform-based scrolling and intercepts clicks in capture phase so legacy handlers can't break it.
(function () {
  function visibleStepPx(visibleWidth) {
    // Mirror the legacy visibleWidth(...) logic closely for consistent feel.
    if (visibleWidth > 1000) return 450;
    if (visibleWidth > 800 && visibleWidth < 1000) return 550;
    if (visibleWidth > 500 && visibleWidth < 800) return 450;
    if (visibleWidth < 360 && visibleWidth > 320) return 353;
    if (visibleWidth < 320 && visibleWidth > 290) return 313;
    if (visibleWidth < 290) return 288;
    return 383;
  }

  function init() {
    var wrap = document.querySelector(".availableLotteries");
    var inner = document.querySelector(".availableLotteries .lotteryContent");
    var leftBtn = document.querySelector(".lotteriesLeft");
    var rightBtn = document.querySelector(".lotteriesRight");
    if (!wrap || !inner || !leftBtn || !rightBtn) return;

    // Ensure transform animation works even if legacy CSS expects `left`.
    try {
      inner.style.willChange = "transform";
      inner.style.transition = "transform 450ms ease";
      inner.style.transform = "translate3d(0px, 0px, 0px)";
    } catch (e) {}

    var pos = 0; // px scrolled to the right; we apply translateX(-pos)

    function measure() {
      var visible = 0;
      var full = 0;
      try {
        visible = Math.max(0, Math.floor(wrap.getBoundingClientRect().width || 0));
      } catch (e) {
        visible = 0;
      }
      try {
        full = Math.max(0, Math.floor(inner.scrollWidth || inner.getBoundingClientRect().width || 0));
      } catch (e2) {
        full = 0;
      }
      return { visible: visible, full: full };
    }

    function setDisabled(btn, isDisabled) {
      try {
        if (isDisabled) btn.classList.add("lotteriesArrowDisabled");
        else btn.classList.remove("lotteriesArrowDisabled");
      } catch (e) {}
    }

    function clampAndApply() {
      var m = measure();
      var max = Math.max(0, m.full - m.visible);
      if (pos < 0) pos = 0;
      if (pos > max) pos = max;

      setDisabled(leftBtn, pos <= 0);
      setDisabled(rightBtn, pos >= (max - 5));

      try {
        inner.style.transform = "translate3d(" + String(-pos) + "px, 0px, 0px)";
      } catch (e3) {}
    }

    function step() {
      var m = measure();
      var s = visibleStepPx(m.visible);
      return Math.max(180, Math.min(650, s));
    }

    function onLeft(ev) {
      try {
        ev.preventDefault();
        ev.stopImmediatePropagation();
      } catch (e) {}
      pos -= step();
      clampAndApply();
    }

    function onRight(ev) {
      try {
        ev.preventDefault();
        ev.stopImmediatePropagation();
      } catch (e) {}
      pos += step();
      clampAndApply();
    }

    // Capture phase so legacy jQuery handlers won't run after ours.
    leftBtn.addEventListener("click", onLeft, true);
    rightBtn.addEventListener("click", onRight, true);

    // Initial state (after layout/images settle).
    clampAndApply();
    window.addEventListener("load", function () { clampAndApply(); });
    window.addEventListener("resize", function () { clampAndApply(); });
    setTimeout(function () { clampAndApply(); }, 250);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

