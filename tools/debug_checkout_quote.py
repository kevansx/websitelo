"""
Diagnostic: what does POST /api/v1/checkout/quote actually return?

The website can only make the CRM apply a checkout offer by posting the offer's
rule id on the quote and submitting that quote's id. If the quote carries no id,
or lists no eligible offers, no discount is possible — and both failures are
invisible from the outside.

    python tools/debug_checkout_quote.py <email> <password>                 # sweep every SKU
    python tools/debug_checkout_quote.py <email> <password> SE1 3           # one cart, in full

The sweep is the evidence to send the CRM team: one row per catalogue SKU with
the subtotal, whether a quote id was issued, and what the CRM listed under
`eligible_checkout_offers`. The single-cart mode dumps the raw response and then
re-quotes with the first rule id it found, so you can see whether posting the
rule changes the total.
"""

import json
import os
import random
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv  # noqa: E402

from crm_api import CRMClient, CRMError, load_crm_config_from_env  # noqa: E402

OFFER_LIST_KEYS = ("eligible_checkout_offers", "eligible_offers", "checkout_offers", "offers")


def _groups(line_schema):
    if isinstance(line_schema, dict) and isinstance(line_schema.get("groups"), list):
        return [g for g in line_schema["groups"] if isinstance(g, dict)]
    if isinstance(line_schema, list):
        return [g for g in line_schema if isinstance(g, dict)]
    if isinstance(line_schema, dict):
        out = []
        for name, spec in line_schema.items():
            if isinstance(spec, dict):
                out.append({"name": name, **spec})
        return out
    return []


def _quickpick(line_schema, count):
    lines = []
    for _ in range(count):
        line = {}
        for g in _groups(line_schema):
            lo = int(g.get("min") or 1)
            hi = int(g.get("max") or lo)
            need = int(g.get("count") or 1)
            picks = sorted(random.sample(range(lo, hi + 1), min(need, hi - lo + 1)))
            line[str(g.get("name"))] = picks[0] if need == 1 else ",".join(str(n) for n in picks)
        lines.append(line)
    return lines


def _find_offers(resp):
    containers = [resp if isinstance(resp, dict) else {}]
    if isinstance(resp, dict) and isinstance(resp.get("quote"), dict):
        containers.append(resp["quote"])
    for container in containers:
        for key in OFFER_LIST_KEYS:
            value = container.get(key)
            if isinstance(value, list) and value:
                return key, [x for x in value if isinstance(x, dict)]
    return None, []


def _find_quote_id(resp):
    if not isinstance(resp, dict):
        return None, None
    quote = resp.get("quote") if isinstance(resp.get("quote"), dict) else {}
    for where, value in (
        ("quote_id", resp.get("quote_id")),
        ("id", resp.get("id")),
        ("quote.quote_id", quote.get("quote_id")),
        ("quote.id", quote.get("id")),
    ):
        if value not in (None, "", 0):
            return where, value
    return None, None


def _report(label, resp):
    print(f"\n=== {label} ===")
    print("top-level keys:", sorted(resp.keys()) if isinstance(resp, dict) else type(resp).__name__)
    where, qid = _find_quote_id(resp)
    print("quote id:", f"{qid!r} (at {where})" if where else "NONE — /checkout/submit is unreachable")
    key, offers = _find_offers(resp)
    if offers:
        print(f"eligible offers ({len(offers)}) under {key!r}:")
        for o in offers:
            print("   ", json.dumps(o, default=str)[:300])
    else:
        print("eligible offers: NONE under", ", ".join(OFFER_LIST_KEYS))
    quote = resp.get("quote") if isinstance(resp, dict) else None
    if isinstance(quote, dict):
        print("quote keys:", sorted(quote.keys()))
        for k in ("currency", "subtotal_cents", "discount_cents", "total_cents", "total_base_cents"):
            if k in quote:
                print(f"  {k}:", quote.get(k))
        print("  discount_breakdown:", json.dumps(quote.get("discount_breakdown"), default=str)[:600])
    return offers


def _sweep(c, token, products) -> None:
    """One row per SKU: the shape of the quote the website actually gets."""
    print(f"{'code':<10}{'lines':<7}{'subtotal':<12}{'quote_id':<10}eligible_checkout_offers")
    for p in products:
        code = str(p.get("code") or p.get("product_code") or "")
        if not code:
            continue
        cap = int(p.get("website_max_lines_per_item") or 50)
        floor = int(p.get("bundle_min_lines") or 1) if str(p.get("pricing_kind")) == "bundle" else 1
        counts = sorted({n for n in (int(p.get("default_lines") or 1), max(3, floor), floor * 2) if 0 < n <= cap})
        for n in counts:
            items = [{"kind": "single", "product_code": code, "lines": _quickpick(p.get("line_schema"), n)}]
            try:
                resp = c.checkout_quote({"items": items}, token=token)
            except CRMError as e:
                print(f"{code:<10}x{n:<6}HTTP {e.status_code}: {e}")
                continue
            quote = (resp or {}).get("quote") or {}
            _, qid = _find_quote_id(resp)
            _, offers = _find_offers(resp)
            print(
                f"{code:<10}x{n:<6}{str(quote.get('subtotal_cents')) + ' ' + str(quote.get('currency')):<12}"
                f"{str(qid or 'NONE'):<10}{json.dumps(offers, default=str) if offers else '[] (no discount possible)'}"
            )


def main() -> None:
    load_dotenv()
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    email, password = sys.argv[1], sys.argv[2]
    product_code = (sys.argv[3] if len(sys.argv) > 3 else "").strip().upper()
    line_count = int(sys.argv[4]) if len(sys.argv) > 4 else 3

    c = CRMClient(load_crm_config_from_env())
    token = (c.auth_login({"email": email, "password": password}) or {}).get("token")
    if not token:
        print("login failed")
        raise SystemExit(1)

    products = [p for p in ((c.store_products() or {}).get("products") or []) if isinstance(p, dict)]
    if not product_code:
        _sweep(c, token, products)
        return
    if product_code:
        products = [p for p in products if str(p.get("code") or p.get("product_code") or "").upper() == product_code]
    product = next((p for p in products if p.get("line_schema")), None)
    if not product:
        print("no product with a line_schema found for", product_code or "(any)")
        raise SystemExit(1)
    code = str(product.get("code") or product.get("product_code"))
    print("product:", code, "lines:", line_count)

    items = [{"product_code": code, "lines": _quickpick(product.get("line_schema"), line_count)}]
    try:
        resp = c.checkout_quote({"items": items}, token=token)
    except CRMError as e:
        print("quote failed:", e, "payload:", json.dumps(e.payload, default=str)[:600])
        raise SystemExit(1)
    offers = _report("quote without a rule id", resp)

    # Marketing banners are the other place these offers surface.
    try:
        banners = (c.marketing_banners("checkout", token=token) or {}).get("banners") or []
        print(f"\n=== checkout placement banners ({len(banners)}) ===")
        for b in banners[:10]:
            print("   ", json.dumps(b, default=str)[:300])
    except CRMError as e:
        print("\ncheckout banners failed:", e)

    rule_id = None
    for o in offers:
        for k in ("rule_id", "id", "offer_rule_id", "mm_offer_rule_id"):
            if o.get(k) not in (None, "", 0):
                rule_id = o[k]
                break
        if rule_id:
            break
    if not rule_id:
        print("\nNo rule id to post back: the CRM listed no eligible offer for this cart.")
        return

    try:
        resp2 = c.checkout_quote(
            {"items": items, "selected_checkout_offers": [str(rule_id)]},
            token=token,
        )
    except CRMError as e:
        print(f"\nre-quote with rule {rule_id} failed:", e, json.dumps(e.payload, default=str)[:600])
        return
    _report(f"quote with selected_checkout_offers=[{rule_id}]", resp2)


if __name__ == "__main__":
    main()
