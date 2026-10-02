/* Home banner carousel (after theLotter): a track of full-width slides that moves left every 6.5s with a 0.5s
   ease-in-out slide, looping seamlessly through a clone of the first slide. Pauses on hover, keyboard focus,
   touch and when the tab is hidden; swipe on touch screens; dots jump to a slide. With reduced motion there is
   no autoplay and no sliding animation (dots still work). No dependencies. */
(function () {
  "use strict";
  var root = document.querySelector("[data-hero]");
  if (!root) return;
  var track = root.querySelector("[data-hero-track]");
  var slides = Array.prototype.slice.call(root.querySelectorAll("[data-hero-slide]"));
  var dots = Array.prototype.slice.call(root.querySelectorAll("[data-hero-dot]"));
  var n = slides.length;
  if (n < 2) return;

  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var INTERVAL = 6500, SLIDE_MS = 500;
  var index = 0, timer = null, paused = false;

  // seamless loop: clone the first slide onto the end
  var clone = slides[0].cloneNode(true);
  clone.setAttribute("aria-hidden", "true");
  Array.prototype.forEach.call(clone.querySelectorAll("a, button"), function (el) { el.setAttribute("tabindex", "-1"); });
  track.appendChild(clone);

  function setFocusable(active) {
    slides.forEach(function (s, i) {
      s.setAttribute("aria-hidden", i === active ? "false" : "true");
      Array.prototype.forEach.call(s.querySelectorAll("a, button"), function (el) {
        if (i === active) el.removeAttribute("tabindex"); else el.setAttribute("tabindex", "-1");
      });
    });
    dots.forEach(function (d, i) { d.setAttribute("aria-selected", i === active ? "true" : "false"); });
  }

  function go(i, animate) {
    track.style.transition = (animate && !REDUCED) ? "transform " + SLIDE_MS + "ms ease-in-out" : "none";
    track.style.transform = "translateX(" + (-i * 100) + "%)";
    index = i;
    setFocusable(i % n);
  }

  track.addEventListener("transitionend", function () {
    if (index === n) go(0, false);   // landed on the clone: jump back to the real first slide
  });

  function next() { go(index >= n ? 1 : index + 1, true); }
  function start() { if (REDUCED) return; stop(); timer = setInterval(function () { if (!paused && !document.hidden) next(); }, INTERVAL); }
  function stop() { if (timer) clearInterval(timer); timer = null; }

  root.addEventListener("mouseenter", function () { paused = true; });
  root.addEventListener("mouseleave", function () { paused = false; });
  root.addEventListener("focusin", function () { paused = true; });
  root.addEventListener("focusout", function () { paused = false; });

  dots.forEach(function (d) {
    d.addEventListener("click", function () { go(parseInt(d.getAttribute("data-hero-dot"), 10), true); start(); });
  });

  // swipe
  var x0 = null, y0 = null;
  root.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; paused = true; }, { passive: true });
  root.addEventListener("touchend", function (e) {
    paused = false;
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
    if (dx < 0) next();
    else go(index === 0 ? n - 1 : (index === n ? n - 1 : index - 1), true);
    start();
  }, { passive: true });

  go(0, false);
  start();
})();
