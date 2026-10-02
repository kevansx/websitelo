"""The brand's store catalogue, read the same way whatever shape the CRM answers in.

The CRM's /api/v1/store/games lists a game's products under `single_products` (plus `single_product` and
`syndicate_products`), and a product's number format (`line_schema`) as a list of groups:
    [{"name": "main", "count": 6, "min": 1, "max": 45}, ...]
Other builds (and the local stand-in CRM) use `products` and a {"groups": [...]} or {"main": {...}} format.
Everything LottosOnline adds on top of the engine (home-screen ticket, gift packs) reads products through here.
"""
from __future__ import annotations

import logging
import random
import re
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
    """The product with this code, or else the game's base (single-draw) product. Never a multi-draw tier or a
    subscription unless asked for by code: a grant or a default on one of those would be the wrong product."""
    for g in games or []:
        if game_code and str(g.get("game_code") or "").lower() != game_code.lower():
            continue
        for p in game_products(g):
            if p.get("website_enabled") is False:
                continue
            if code and product_code(p) != code:
                continue
            if not code and product_kind(p) != "base":
                continue
            p = dict(p)
            p.setdefault("game_code", g.get("game_code"))
            p.setdefault("game_name", g.get("game_name"))
            return p
    return None


# ------------------------------------------------------------------ product kinds (build brief 2, part 1)
# Since the October 2026 catalogue a lottery has up to three kinds of product (CRM reply, crm-setup/):
#   base          LO-XXXXX          the single draw, the only product a play page sells as an ordinary ticket
#   tier          LO-XXXXX-4/-8/-16 (draws) or -1W/-3W/-5W (weeks): multi-draw with the discount locked in the
#                 price, sold only with ticket_mode multi_draw and its locked draw_weeks
#   subscription  LO-XXXXX-W        weekly syndicate share, never in the single-ticket cart
_log = logging.getLogger(__name__)
_BASE_RE = re.compile(r"^LO-[A-Z]{5}$")
_TIER_RE = re.compile(r"^LO-[A-Z]{5}-(4|8|16|1W|3W|5W)$")
_SUB_RE = re.compile(r"^LO-[A-Z]{5}-W$")

# Locked draw_weeks per tier product, from the CRM reply (2 October 2026). Used when the store API does not carry
# the lock itself; if it does, the two must agree or the product is not sold.
TIER_DRAW_WEEKS = {
    "LO-USMEG-4": 2, "LO-USMEG-8": 4,
    "LO-USCAL-4": 2, "LO-USCAL-8": 4, "LO-USCAL-16": 8,
    "LO-EUEUR-4": 2, "LO-EUEUR-8": 4, "LO-EUEUR-16": 8,
    "LO-EUJAC-4": 2, "LO-EUJAC-8": 4, "LO-EUJAC-16": 8,
    "LO-DELOT-4": 2, "LO-DELOT-8": 4, "LO-DELOT-16": 8,
    "LO-IELOT-4": 2, "LO-IELOT-8": 4, "LO-IELOT-16": 8,
    "LO-ITSUP-4": 1, "LO-ITSUP-8": 2, "LO-ITSUP-16": 4,
    "LO-UKTHU-4": 1, "LO-UKTHU-8": 2, "LO-UKTHU-16": 4,
    "LO-ESELG-4": 4, "LO-ESELG-8": 8, "LO-ESELG-16": 16,
    "LO-AUPOW-4": 4, "LO-AUPOW-8": 8, "LO-AUPOW-16": 16,
    "LO-AULOT-4": 4, "LO-AULOT-8": 8, "LO-AULOT-16": 16,
    "LO-AUTAT-4": 4, "LO-AUTAT-8": 8, "LO-AUTAT-16": 16,
    "LO-USPOW-1W": 1, "LO-USPOW-3W": 3, "LO-USPOW-5W": 5,
    "LO-USLOT-1W": 1, "LO-USLOT-3W": 3, "LO-USLOT-5W": 5,
    "LO-ESLAP-1W": 1, "LO-ESLAP-3W": 3, "LO-ESLAP-5W": 5,
    "LO-AUMON-1W": 1, "LO-AUMON-3W": 3, "LO-AUMON-5W": 5,
}

# The commercial minimum lines per order ("Send at least"), by base code. The CRM checkout does not enforce it.
MIN_LINES = {
    "LO-USPOW": 3, "LO-USMEG": 1, "LO-USCAL": 5, "LO-USLOT": 5, "LO-USMIL": 1, "LO-EUEUR": 3, "LO-EUJAC": 3,
    "LO-ITSUP": 4, "LO-ESELG": 3, "LO-ESLAP": 4, "LO-ESBON": 5, "LO-DELOT": 5, "LO-FRLOT": 3, "LO-IELOT": 3,
    "LO-UKTHU": 3, "LO-AUPOW": 5, "LO-AULOT": 5, "LO-AUTAT": 5, "LO-AUMON": 5,
}


def _code_kind(code: str) -> str | None:
    c = code.upper()
    if _SUB_RE.match(c):
        return "subscription"
    if _TIER_RE.match(c):
        return "tier"
    if _BASE_RE.match(c):
        return "base"
    return None


def _api_kind(p: dict) -> str | None:
    modes = p.get("available_ticket_modes")
    modes = [str(m).lower() for m in modes] if isinstance(modes, list) else None
    if str(p.get("product_type") or "").lower() == "syndicate" or modes == ["subscription"]:
        return "subscription"
    if modes is None:
        return None
    if "multi_draw" in modes:
        return "tier"
    if "standard" in modes:
        return "base"
    return None


def product_kind(p: dict) -> str | None:
    """'base', 'tier' or 'subscription'. None = not sellable: the store fields and the code disagree (a catalogue
    error to fix on the CRM), or a tier has no known draw_weeks lock. A product with neither an LO- code nor ticket
    modes (another brand's single) counts as base."""
    if not isinstance(p, dict):
        return None
    code = product_code(p)
    by_code, by_api = _code_kind(code), _api_kind(p)
    if by_code and by_api and by_code != by_api:
        _log.warning("catalogue error: %s is a %s by its code but a %s by its store fields; not sold", code, by_code, by_api)
        return None
    kind = by_code or by_api or ("base" if str(p.get("product_type") or "single").lower() == "single" else None)
    if kind == "tier" and tier_draw_weeks(p) is None:
        _log.warning("catalogue error: multi-draw product %s has no draw_weeks lock; not sold", code)
        return None
    return kind


def tier_draw_weeks(p: dict) -> int | None:
    code = product_code(p).upper()
    table = TIER_DRAW_WEEKS.get(code)
    api = None
    for k in ("locked_draw_weeks", "multi_draw_weeks", "draw_weeks"):
        v = p.get(k)
        if v not in (None, "", 0):
            try:
                api = int(v)
                break
            except (TypeError, ValueError):
                pass
    if api is not None and table is not None and api != table:
        _log.warning("catalogue error: %s has draw_weeks %s on the CRM but %s in the CRM reply; not sold", code, api, table)
        return None
    return api if api is not None else table


def tier_span(p: dict) -> dict:
    """What a tier covers: {'draws': 4} for -4/-8/-16, {'weeks': 3} for -1W/-3W/-5W."""
    m = _TIER_RE.match(product_code(p).upper())
    if not m:
        return {}
    s = m.group(1)
    return {"weeks": int(s[:-1])} if s.endswith("W") else {"draws": int(s)}


def base_code(code: str) -> str:
    m = re.match(r"^(LO-[A-Z]{5})", (code or "").upper())
    return m.group(1) if m else (code or "").upper()


def min_lines(p_or_code: Any) -> int:
    code = product_code(p_or_code) if isinstance(p_or_code, dict) else str(p_or_code or "")
    return MIN_LINES.get(base_code(code), 1)


def price_cents(p: dict, currency: str = "EUR") -> int | None:
    pbc = p.get("prices_by_currency") or {}
    entry = pbc.get(currency) if isinstance(pbc, dict) else None
    if isinstance(entry, dict) and entry.get("amount_cents") is not None:
        return int(entry["amount_cents"])
    v = p.get("price_in_base_cents")
    return int(v) if v is not None else None


def split_products(products: list[dict]) -> dict:
    """{'base': product|None, 'tiers': [...] shortest first, 'subscription': product|None}."""
    out: dict[str, Any] = {"base": None, "tiers": [], "subscription": None}
    for p in products or []:
        if not isinstance(p, dict) or p.get("website_enabled") is False:
            continue
        kind = product_kind(p)
        if kind == "base":
            # two base rows is a catalogue error too; prefer the website default
            if out["base"] is None or (p.get("website_default") and not out["base"].get("website_default")):
                out["base"] = p
        elif kind == "tier":
            out["tiers"].append(p)
        elif kind == "subscription" and out["subscription"] is None:
            out["subscription"] = p
    out["tiers"].sort(key=lambda p: (tier_span(p).get("draws") or 0) + 3 * (tier_span(p).get("weeks") or 0))
    return out


def cart_item_error(p: dict | None, ticket_mode: str | None, draw_weeks: Any) -> str | None:
    """The server-side guard (brief 2, 1.3): None if this product may go in the single-ticket cart like this."""
    if not p:
        return "That ticket is not available."
    kind = product_kind(p)
    mode = (ticket_mode or "standard").strip().lower()
    try:
        weeks = int(draw_weeks) if draw_weeks not in (None, "") else None
    except (TypeError, ValueError):
        return "That ticket is not available."
    if kind == "subscription":
        return "Memberships are joined from their own page, not added to the cart."
    if kind == "base":
        if mode != "standard" or weeks is not None:
            return "That ticket is not available."
        return None
    if kind == "tier":
        if mode != "multi_draw" or weeks is None or weeks != tier_draw_weeks(p):
            return "That ticket is not available."
        return None
    return "That ticket is not available."
