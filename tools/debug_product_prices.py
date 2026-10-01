"""Temporary diagnostic: show retail prices per currency for a game's products."""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv  # noqa: E402

from crm_api import CRMClient, load_crm_config_from_env  # noqa: E402


def main() -> None:
    load_dotenv()
    game_code = (sys.argv[1] if len(sys.argv) > 1 else "superenalotto").strip()
    c = CRMClient(load_crm_config_from_env())
    resp = c.store_game(game_code)
    game = (resp.get("game") if isinstance(resp, dict) else None) or {}
    products = []
    for k in ("products", "default_products", "skus"):
        if isinstance(game.get(k), list) and game.get(k):
            products = [p for p in game[k] if isinstance(p, dict)]
            break
    if not products:
        sp = c.store_products()
        allp = sp.get("products") if isinstance(sp, dict) else []
        products = [p for p in (allp or []) if isinstance(p, dict) and p.get("game_code") == game_code]

    # Same product from the products endpoint, where per-currency prices are documented.
    from_products: dict[str, dict] = {}
    try:
        sp = c.store_products()
        for p in (sp.get("products") if isinstance(sp, dict) else []) or []:
            if isinstance(p, dict):
                code = str(p.get("code") or p.get("product_code") or "").strip().upper()
                if code:
                    from_products[code] = p
    except Exception as e:
        print("store_products failed:", e)

    print("game:", game_code, "products:", len(products))
    for p in products:
        code_u = str(p.get("code") or p.get("product_code") or "").strip().upper()
        alt = from_products.get(code_u) or {}
        if alt:
            print(
                "\n[store_products] price_in_base_cents:",
                alt.get("price_in_base_cents"),
                "prices_by_currency:",
                json.dumps(alt.get("prices_by_currency")) if alt.get("prices_by_currency") is not None else "MISSING",
            )
        print("\n--- ", p.get("code") or p.get("product_code"), "---")
        for k in (
            "price_in_base_cents",
            "base_currency",
            "pricing_kind",
            "sale_unit_lines",
            "default_lines",
            "website_max_lines_per_item",
        ):
            if k in p:
                print(f"  {k}:", p.get(k))
        pbc = p.get("prices_by_currency")
        print("  prices_by_currency:", json.dumps(pbc) if pbc is not None else "MISSING")
        addons = p.get("addons")
        if addons:
            print("  addons:", json.dumps(addons)[:600])


if __name__ == "__main__":
    main()
