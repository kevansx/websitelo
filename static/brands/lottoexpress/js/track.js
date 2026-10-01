(function () {
  function postJson(url, payload) {
    try {
      return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
        credentials: "same-origin",
        keepalive: true,
      });
    } catch (e) {
      return null;
    }
  }

  function trackPageview() {
    postJson("/api/track/pageview", { path: window.location.pathname });
  }

  function trackRegisterClick(phase, element) {
    postJson("/api/track/click", {
      metadata: {
        cta: "register",
        phase: phase || "unknown",
        element: element || "unknown",
        path: window.location.pathname,
      },
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    trackPageview();

    document.body.addEventListener("click", function (e) {
      var el = e.target;
      if (!el) return;

      // Walk up to anchor if needed
      while (el && el !== document.body && el.tagName !== "A") el = el.parentElement;
      if (!el || el.tagName !== "A") return;

      var href = el.getAttribute("href") || "";
      var isRegister = href.indexOf("/register") === 0 || el.classList.contains("registrationFormLink");
      if (!isRegister) return;

      // best-effort phase/element identifiers
      var phase = "page";
      if (el.closest && el.closest(".navbar")) phase = "header";
      var element = el.id || el.className || "register_link";

      trackRegisterClick(phase, element);
    });
  });
})();

