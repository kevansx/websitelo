/* Web push, browser side (server: lo_push.py). window.LOPush:
 *   available()  push is switched on, the browser supports it and (on iPhone) runs as the installed app
 *   permission() "default" | "granted" | "denied"
 *   declined()   the customer said no to our ask before (we then never ask again by ourselves)
 *   enable()     asks the browser (must be called from a tap), subscribes, stores it on the server
 *   decline()    remembers "no"
 */
(function () {
  "use strict";
  var KEY_META = document.querySelector('meta[name="lo-push-key"]');
  var KEY = KEY_META ? KEY_META.content : "";
  var DECLINED = "lo_push_declined";
  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ""; }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function b64ToBytes(s) {
    var pad = "=".repeat((4 - s.length % 4) % 4), raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  var supported = !!(KEY && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window);

  window.LOPush = {
    available: function () { return supported; },
    permission: function () { return supported ? Notification.permission : "denied"; },
    declined: function () { return read(DECLINED) === "1"; },
    decline: function () { store(DECLINED, "1"); },
    enable: function () {
      if (!supported) return Promise.resolve(false);
      return Notification.requestPermission().then(function (p) {
        if (p !== "granted") { store(DECLINED, "1"); return false; }
        return navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function () {
          return navigator.serviceWorker.ready;
        }).then(function (reg) {
          return reg.pushManager.getSubscription().then(function (s) {
            return s || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(KEY) });
          });
        }).then(function (sub) {
          return fetch("/push/subscribe", {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
            body: JSON.stringify(sub.toJSON())
          }).then(function (r) { return r.ok; });
        });
      }).catch(function () { return false; });
    }
  };
})();
