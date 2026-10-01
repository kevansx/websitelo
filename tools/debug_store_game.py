import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv  # noqa: E402

from crm_api import CRMClient, load_crm_config_from_env  # noqa: E402


def main() -> None:
    load_dotenv()
    game_code = (sys.argv[1] if len(sys.argv) > 1 else "megamillions").strip()
    c = CRMClient(load_crm_config_from_env())
    resp = c.store_game(game_code)
    game = (resp.get("game") if isinstance(resp, dict) else None) or {}
    products = []
    if isinstance(game, dict):
        for k in ("products", "default_products", "skus", "single_products", "syndicate_products"):
            if isinstance(game.get(k), list):
                products = [p for p in game.get(k) if isinstance(p, dict)]
                if products:
                    break
    if not products and isinstance(resp, dict) and isinstance(resp.get("products"), list):
        products = [p for p in resp.get("products") if isinstance(p, dict)]
    if not products:
        sp = c.store_products()
        allp = sp.get("products") if isinstance(sp, dict) else None
        if isinstance(allp, list):
            products = [p for p in allp if isinstance(p, dict) and (p.get("game_code") == game_code)]

    print("game_code:", game_code)
    print("game_keys:", sorted(list(game.keys()))[:40] if isinstance(game, dict) else type(game).__name__)
    if isinstance(game, dict):
        print("game_json:", json.dumps(game, indent=2)[:2000])
    print("products:", len(products))
    for p in products[:3]:
        code = p.get("code") or p.get("product_code")
        print("\n--- product:", code, "---")
        for k in ("code", "product_code", "name", "product_type", "game_code", "price_in_base_cents", "base_currency"):
            if k in p:
                print(f"{k}:", p.get(k))
        addons = p.get("addons")
        if isinstance(addons, list) and addons:
            print("addons:", json.dumps(addons, indent=2)[:1200])
        ls = p.get("line_schema")
        print("line_schema_type:", type(ls).__name__)
        if isinstance(ls, dict):
            print("line_schema_keys:", sorted(list(ls.keys()))[:60])
            print("line_schema_json:", json.dumps(ls, indent=2)[:1200])
        elif isinstance(ls, list):
            print("line_schema_len:", len(ls))
            print("line_schema_json:", json.dumps(ls, indent=2)[:2000])


if __name__ == "__main__":
    main()

