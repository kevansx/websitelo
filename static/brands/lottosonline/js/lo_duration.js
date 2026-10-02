/* Play page: how many draws (build brief 2, part 4). Each duration is its own CRM product with the discount
 * already in its price, so choosing one swaps the product code and sends ticket_mode multi_draw with the
 * product's locked draw_weeks. The server checks the same rule again (lo_store.cart_item_error). The picker's
 * lines are untouched; only the price per line and the number of draws change (window.LOPicker.setDuration).
 */
(function () {
  "use strict";
  var radios = document.querySelectorAll('input[name="lo_duration"]');
  var code = document.getElementById("leProductCode");
  var mode = document.getElementById("leTicketMode");
  var weeks = document.getElementById("leDrawWeeks");
  if (!radios.length || !code || !mode || !weeks) return;

  function apply(r) {
    code.value = r.value;
    mode.value = r.getAttribute("data-mode") || "standard";
    weeks.value = mode.value === "multi_draw" ? (r.getAttribute("data-weeks-lock") || "") : "";
    var d = { cents: parseInt(r.getAttribute("data-cents"), 10) };
    var w = parseInt(r.getAttribute("data-weeks") || "0", 10), n = parseInt(r.getAttribute("data-draws") || "0", 10);
    if (w) d.weeks = w; else d.draws = n || 1;
    if (window.LOPicker && window.LOPicker.setDuration) window.LOPicker.setDuration(d);
  }

  Array.prototype.forEach.call(radios, function (r) {
    r.addEventListener("change", function () { if (r.checked) apply(r); });
  });
  // the picker builds itself on DOMContentLoaded; apply the checked duration once it exists
  function start() {
    var checked = document.querySelector('input[name="lo_duration"]:checked');
    if (!window.LOPicker) { setTimeout(start, 50); return; }
    if (checked) apply(checked);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
