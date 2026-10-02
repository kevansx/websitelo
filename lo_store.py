"""The brand's store catalogue, read the same way whatever shape the CRM answers in.

The CRM's /api/v1/store/games lists a game's products under `single_products` (plus `single_product` and
`syndicate_products`), and a product's number format (`line_schema`) as a list of groups:
    [{"name": "main", "count": 6, "min": 1, "max": 45}, ...]
Other builds (and the local stand-in CRM) use `products` and a {"groups": [...]} or {"main": {...}} format.
Everything LottosOnline adds on top of the engine (home-screen ticket, gift packs) reads products through here.
"""
from __future__ import annotations

import random
from typing import Any


def game_products(game: dict) -> list[dict]:
    if not isinstance(game, dict):
        return []
    out: list[dict] = []
    for key in ("products", "single_products"):
        v = game.get(key)
        if isinstance(v, list):
            out.extend(p for p in v if isinstance(p, dict))
    if not out and isinstance(game.get("single_product"), dict):
        out.append(game["single_product"])
    seen, uniq = set(), []
    for p in out:
        code = product_code(p)
        if code in seen:
            continue
        seen.add(code)
        uniq.append(p)
    return uniq


def product_code(p: dict) -> str:
    return str(p.get("code") or p.get("product_code") or "").strip()


def schema_groups(line_schema: Any) -> list[dict]:
    """The number format as a list of {name, count, min, max}, main group first."""
    groups: list[dict] = []
    if isinstance(line_schema, list):
        groups = [g for g in line_schema if isinstance(g, dict) and g.get("name")]
    elif isinstance(line_schema, dict):
        if isinstance(line_schema.get("groups"), list):
            groups = [g for g in line_schema["groups"] if isinstance(g, dict) and g.get("name")]
        else:
            groups = [{"name": k, **v} for k, v in line_schema.items() if isinstance(v, dict)]
    groups.sort(key=lambda g: 0 if g.get("name") == "main" else 1)
    return groups


def quick_pick(line_schema: Any) -> dict:
    """One random line in the CRM's grant format: main as "1,2,3", single bonus numbers as an int."""
    line: dict[str, Any] = {}
    for g in schema_groups(line_schema):
        lo, hi, n = int(g.get("min", 1)), int(g.get("max", 45)), int(g.get("count", 1))
        nums = sorted(random.sample(range(lo, hi + 1), min(n, hi - lo + 1)))
        name = str(g["name"])
        line[name] = ",".join(map(str, nums)) if (name == "main" or len(nums) > 1) else nums[0]
    return line


def find_product(games: list[dict], *, game_code: str | None = None, code: str | None = None) -> dict | None:
    """The product with this code, or else the first website-enabled product of this game."""
    for g in games or []:
        if game_code and str(g.get("game_code") or "").lower() != game_code.lower():
            continue
        for p in game_products(g):
            if p.get("website_enabled") is False:
                continue
            if code and product_code(p) != code:
                continue
            p = dict(p)
            p.setdefault("game_code", g.get("game_code"))
            p.setdefault("game_name", g.get("game_name"))
            return p
    return None
