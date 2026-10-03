"""Gift packs (build brief 1, parts 2 and 3): the website owns the pack; the CRM only grants the gift.

Same pattern as lo_homescreen.py: a local record, and the CRM's idempotency key as the real guard against
granting twice.

* Triggers come from order history. They are worked out when an order is placed (checkout_submit hands over
  the order), against a per-customer activity record seeded once from the CRM's order history:
    first_play  first paid order
    return      second paid order within 14 days of the first
    explorer    first order in a lottery new to this customer (not on the first order: that is first_play)
    long_play   first purchase of any multi-draw tier product
    surprise    any later order, at random (Joey, 2 Oct 2026: unpredictable rewards keep people going far longer
                than a fixed "every Nth order" schedule). About 1 order in 4; never two orders in a row; guaranteed
                after 8 orders without a gift; at most one surprise per 7 days, so buying faster or bigger never
                earns more; 1 surprise in 4 is a gold (premium) pack. Never tied to spend. Drawn on the server.
  `welcome` (home screen added) is not wired: the home-screen offer has approved terms of its own (one free
  Australia Saturday Lotto line), which a random pack would change.
* A pack is earned sealed. Opening it (POST /packs/<id>/open, or the nightly auto-open after 14 days) draws the
  gift on the server and grants it through POST /api/v1/marketing/incentives/grant-free-ticket with
  idempotency_key "pack-<pack_id>". The gift is recorded before anything is shown; opening twice returns the
  same gift.
* Gift shape A: a quick pick at the lottery's own minimum line count, from four low-cost lotteries. Of those, the
  ones the customer has never played first, then the rest, three candidates, one drawn at random.
  Shape B: two quick-pick lines on a lottery they play (long_play; and the fallback when all four are played).
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import lo_store

# Five live types (brief 2, part 8). welcome stays the home-screen ticket under its own terms; raffle is gone:
# the CRM cannot grant a raffle and Spanish Raffles is not being created.
PACK_TYPES = ("first_play", "return", "explorer", "long_play", "surprise")
# surprise packs (variable-ratio): chance per order, guarantee, spacing, cooling-off, share that are gold
SURPRISE_CHANCE = 0.25
SURPRISE_GUARANTEE_GAP = 8               # orders since the last gift that make the next order a sure thing
SURPRISE_MIN_GAP = 2                     # never on the order straight after a gift
SURPRISE_COOLDOWN = timedelta(days=7)    # harm guard: buying faster never earns more
SURPRISE_GOLD_CHANCE = 0.25              # the gift inside a gold pack is drawn exactly the same way
SEALED_DAYS = 14
RETURN_WINDOW = timedelta(days=14)

# Shape A pool: (game_code, preferred product code, minimum lines). Codes as in the CRM product request.
GIFT_POOL = (
    ("weekday-windfall-au", "LO-AUMON", 5),
    ("sat-lotto-au", "LO-AUTAT", 5),
    ("bonoloto", "LO-ESBON", 5),
    ("powerball-au", "LO-AUPOW", 5),
)
SHAPE_B_LINES = 2

_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


# ------------------------------------------------------------------ storage
def db_path() -> Path:
    base = (os.environ.get("LO_PACKS_DB_PATH") or "").strip()
    if base:
        return Path(base)
    cache = (os.environ.get("CRM_CACHE_DB_PATH") or "").strip()
    folder = Path(cache).parent if cache else Path(__file__).resolve().parent / "data"
    return folder / "packs.sqlite"


def _db() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS packs (
        pack_id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL, type TEXT NOT NULL, tier TEXT NOT NULL,
        state TEXT NOT NULL, earned_at TEXT NOT NULL, opened_at TEXT, expires_at TEXT NOT NULL,
        gift_json TEXT, idempotency_key TEXT NOT NULL, order_id TEXT, error TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS packs_customer ON packs(customer_id, state)")
    c.execute("""CREATE TABLE IF NOT EXISTS activity (
        customer_id INTEGER PRIMARY KEY, orders_count INTEGER NOT NULL, first_order_at TEXT,
        games_json TEXT NOT NULL, played_raffle INTEGER NOT NULL, played_long INTEGER NOT NULL,
        seen_orders_json TEXT NOT NULL)""")
    for col in ("last_pack_order INTEGER", "last_surprise_at TEXT"):
        try:
            c.execute(f"ALTER TABLE activity ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass                                    # already there
    return c


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["gift"] = json.loads(d["gift_json"]) if d.get("gift_json") else None
    return d


def get_pack(pack_id: str, customer_id: int | None = None) -> dict | None:
    with closing(_db()) as c:
        r = c.execute("SELECT * FROM packs WHERE pack_id=?", (pack_id,)).fetchone()
    p = _row(r)
    if p and customer_id is not None and int(p["customer_id"]) != int(customer_id):
        return None
    return p


def customer_packs(customer_id: int) -> dict[str, list[dict]]:
    with closing(_db()) as c:
        rows = [_row(r) for r in c.execute(
            "SELECT * FROM packs WHERE customer_id=? ORDER BY earned_at DESC", (customer_id,))]
    now = _now()
    sealed, opened = [], []
    for p in rows:
        if p["state"] == "sealed":
            exp = _parse(p["expires_at"]) or now
            p["days_left"] = max(0, (exp - now).days)
            sealed.append(p)
        else:
            opened.append(p)
    return {"sealed": sealed, "opened": opened}


# ------------------------------------------------------------------ activity (what the customer has played)
def _activity(c: sqlite3.Connection, customer_id: int) -> dict | None:
    r = c.execute("SELECT * FROM activity WHERE customer_id=?", (customer_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["games"] = json.loads(d.pop("games_json") or "{}")
    d["seen_orders"] = set(json.loads(d.pop("seen_orders_json") or "[]"))
    return d


def _save_activity(c: sqlite3.Connection, customer_id: int, a: dict) -> None:
    c.execute("""INSERT OR REPLACE INTO activity
        (customer_id, orders_count, first_order_at, games_json, played_raffle, played_long, seen_orders_json,
         last_pack_order, last_surprise_at)
        VALUES (?,?,?,?,?,?,?,?,?)""", (customer_id, int(a["orders_count"]), a.get("first_order_at"),
                                         json.dumps(a["games"]), int(bool(a["played_raffle"])),
                                         int(bool(a["played_long"])), json.dumps(sorted(a["seen_orders"])),
                                         a.get("last_pack_order"), a.get("last_surprise_at")))


def history_from_crm(crm: Any, token: str, *, exclude_order_id: Any = None) -> dict:
    """What the customer had played before this order: paid order count, first order date, games played.
    Legacy (old-site) orders count as orders, so a long-standing customer never gets a first_play pack."""
    a = {"orders_count": 0, "first_order_at": None, "games": {}, "played_raffle": False, "played_long": False,
         "seen_orders": set()}
    for page in range(1, 21):
        try:
            data = crm.orders(token, page=page, per_page=100)
        except Exception:
            break
        orders = data.get("orders") if isinstance(data, dict) else None
        if not orders:
            break
        for o in orders:
            if not isinstance(o, dict) or str(o.get("id")) == str(exclude_order_id):
                continue
            if str(o.get("status") or "").lower() in ("cancelled", "canceled", "failed", "refunded", "pending"):
                continue
            a["orders_count"] += 1
            a["seen_orders"].add(str(o.get("id")))
            when = o.get("created_at") or o.get("placed_at")
            if when and (a["first_order_at"] is None or str(when) < a["first_order_at"]):
                a["first_order_at"] = str(when)
            for t in (o.get("tickets") or o.get("items") or []):
                gc = str((t or {}).get("game_code") or "").lower() if isinstance(t, dict) else ""
                if gc:
                    a["games"][gc] = a["games"].get(gc, 0) + 1
        if len(orders) < 100:
            break
    try:
        legacy = crm.legacy_orders(token, page=1, per_page=1)
        a["orders_count"] += int((legacy or {}).get("total") or 0)
    except Exception:
        pass
    return a


# ------------------------------------------------------------------ triggers
def _is_multi_draw(it: dict) -> bool:
    """A multi-draw purchase: a tier product (brief 2, 7.3). Since October 2026 each duration is its own product,
    so this no longer counts draws or weekdays."""
    if str(it.get("ticket_mode") or "").lower() == "multi_draw":
        return True
    import lo_store
    return lo_store._code_kind(str(it.get("product_code") or "")) == "tier"


def _order_facts(items: list[dict]) -> dict:
    games, multi_game = set(), None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        gc = str(it.get("game_code") or "").lower()
        if gc:
            games.add(gc)
        if multi_game is None and _is_multi_draw(it):
            multi_game = gc or "?"
    return {"games": games, "multi_draw": multi_game is not None, "multi_game": multi_game}


def triggers_for(before: dict, facts: dict, now: datetime, rng: random.Random | None = None) -> list[str]:
    rng = rng or random.SystemRandom()
    n_before = int(before["orders_count"])
    n_after = n_before + 1
    out: list[str] = []
    if n_before == 0:
        out.append("first_play")
    if n_before == 1:
        first = _parse(before.get("first_order_at"))
        if first and now - first <= RETURN_WINDOW:
            out.append("return")
    if n_before >= 1 and facts["games"] - set(before["games"]):
        out.append("explorer")
    if facts["multi_draw"] and not before["played_long"]:
        out.append("long_play")
    # surprise: only when this order earned nothing else, so a customer never gets two gifts for one order
    if n_before >= 1 and not out:
        last_pack = before.get("last_pack_order")
        gap = n_after - int(last_pack if last_pack is not None else n_before)
        last_s = _parse(before.get("last_surprise_at"))
        cooled = last_s is None or now - last_s >= SURPRISE_COOLDOWN
        if gap >= SURPRISE_MIN_GAP and cooled and (gap >= SURPRISE_GUARANTEE_GAP or rng.random() < SURPRISE_CHANCE):
            out.append("surprise")
    return out


def on_order_placed(*, customer_id: int, order_id: Any, items: list[dict], seed=None,
                    rng: random.Random | None = None) -> list[dict]:
    """Record the order and earn its packs. `seed()` returns the history before this order (only called the
    first time this customer is seen). Returns the packs earned, newest first. The same order twice earns
    nothing the second time."""
    now = _now()
    rng = rng or random.SystemRandom()
    facts = _order_facts(items)
    with _lock, closing(_db()) as c:
        before = _activity(c, customer_id)
        if before is None:
            before = seed() if seed else None
            if before is None:
                before = {"orders_count": 0, "first_order_at": None, "games": {}, "played_raffle": False,
                          "played_long": False, "seen_orders": set()}
        if str(order_id) in before["seen_orders"]:
            return []
        # a customer seeded from their history starts the surprise count from now, not from their first order
        if before.get("last_pack_order") is None:
            before["last_pack_order"] = int(before["orders_count"])
        kinds = triggers_for(before, facts, now, rng)
        after = dict(before)
        after["orders_count"] = int(before["orders_count"]) + 1
        after["first_order_at"] = before.get("first_order_at") or _iso(now)
        after["games"] = dict(before["games"])
        for g in facts["games"]:
            after["games"][g] = after["games"].get(g, 0) + 1
        after["played_raffle"] = False          # raffle packs were dropped (the CRM cannot grant a raffle)
        after["played_long"] = bool(before["played_long"] or facts["multi_draw"])
        after["seen_orders"] = set(before["seen_orders"]) | {str(order_id)}
        if kinds:
            after["last_pack_order"] = after["orders_count"]
        if "surprise" in kinds:
            after["last_surprise_at"] = _iso(now)
        _save_activity(c, customer_id, after)
        earned = []
        for k in kinds:
            pack = {"pack_id": uuid.uuid4().hex[:16], "customer_id": customer_id, "type": k,
                    "tier": "premium" if (k == "surprise" and rng.random() < SURPRISE_GOLD_CHANCE) else "standard",
                    "state": "sealed",
                    "earned_at": _iso(now), "expires_at": _iso(now + timedelta(days=SEALED_DAYS)),
                    "order_id": str(order_id),
                    # long_play's gift is two extra lines on the lottery bought as multi-draw
                    "gift_json": json.dumps({"_hint_game": facts["multi_game"]}) if (k == "long_play" and facts["multi_game"] not in (None, "?")) else None}
            pack["idempotency_key"] = f"pack-{pack['pack_id']}"
            c.execute("""INSERT INTO packs (pack_id, customer_id, type, tier, state, earned_at, expires_at,
                         gift_json, idempotency_key, order_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (pack["pack_id"], customer_id, k, pack["tier"], "sealed", pack["earned_at"],
                       pack["expires_at"], pack["gift_json"], pack["idempotency_key"], pack["order_id"]))
            earned.append(pack)
        c.commit()
    return earned


# ------------------------------------------------------------------ the gift
def choose_gift(pack: dict, played: dict[str, int], games: list[dict], *, rng: random.Random | None = None) -> dict | None:
    """Server-side draw. Returns {game_code, game_name, product_code, lines, shape} or None if nothing is sellable."""
    rng = rng or random.SystemRandom()
    hint = ((json.loads(pack["gift_json"]) if pack.get("gift_json") else {}) or {}).get("_hint_game")

    def product_for(game_code: str, code: str | None = None) -> dict | None:
        return lo_store.find_product(games, game_code=game_code, code=code) or (
            lo_store.find_product(games, game_code=game_code) if code else None)

    def shape_b(game_code: str) -> dict | None:
        p = product_for(game_code)
        if not p:
            return None
        return {"shape": "B", "game_code": game_code, "game_name": p.get("game_name") or game_code,
                "product_code": lo_store.product_code(p), "line_schema": p.get("line_schema"), "lines": SHAPE_B_LINES}

    if pack["type"] == "long_play" and hint:
        g = shape_b(hint)
        if g:
            return g

    available = []
    for game_code, code, min_lines in GIFT_POOL:
        p = product_for(game_code, code)
        if p:
            lines = int(p.get("minimum_lines") or p.get("min_lines") or min_lines)
            available.append({"shape": "A", "game_code": game_code, "game_name": p.get("game_name") or game_code,
                              "product_code": lo_store.product_code(p), "line_schema": p.get("line_schema"),
                              "lines": max(lines, 2)})
    never = [g for g in available if g["game_code"] not in played]
    if not never and played:
        # every lottery in the pool already played: two lines on the one they play most
        for gc, _ in sorted(played.items(), key=lambda kv: -kv[1]):
            g = shape_b(gc)
            if g:
                return g
    never = rng.sample(never, len(never))      # any three of the never-played, not the first three listed
    candidates = never[:3]
    if len(candidates) < 3:
        candidates += [g for g in available if g not in candidates][: 3 - len(candidates)]
    return rng.choice(candidates) if candidates else None


def card_text(gift: dict) -> dict:
    n = int(gift.get("lines") or 0)
    return {"title": gift.get("game_name") or "", "sub": f"{n} free line{'s' if n != 1 else ''}",
            "expiry": "Entered in the next draw"}


class PackError(Exception):
    pass


def open_pack(pack_id: str, *, customer_id: int | None, crm: Any, games: list[dict], auto: bool = False) -> dict:
    """Grant the gift and mark the pack opened. Idempotent: an opened pack returns its recorded gift."""
    with _lock, closing(_db()) as c:
        p = _row(c.execute("SELECT * FROM packs WHERE pack_id=?", (pack_id,)).fetchone())
        if p is None or (customer_id is not None and int(p["customer_id"]) != int(customer_id)):
            raise PackError("not_found")
        if p["state"] in ("opened", "auto_opened"):
            return p
        a = _activity(c, int(p["customer_id"])) or {"games": {}}
        gift = (p.get("gift") or {}) if (p.get("gift") or {}).get("product_code") else None
        if gift is None:
            gift = choose_gift(p, a["games"], games)
            if gift is None:
                raise PackError("no_gift_available")
        lines = [lo_store.quick_pick(gift.get("line_schema"), gift.get("game_code")) for _ in range(int(gift["lines"]))]
        # Record the draw before calling the CRM: a retry grants the same gift with the same key.
        c.execute("UPDATE packs SET gift_json=? WHERE pack_id=?", (json.dumps(gift), pack_id))
        c.commit()
        try:
            res = crm._request("POST", "/api/v1/marketing/incentives/grant-free-ticket", service_key=True, json={
                "customer_id": int(p["customer_id"]), "product_code": gift["product_code"], "lines": lines,
                "incentive_id": f"pack-{p['type']}", "reason": f"Gift pack ({p['type'].replace('_', ' ')})",
                "idempotency_key": p["idempotency_key"],
            })
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE packs SET error=? WHERE pack_id=?", (str(e)[:300], pack_id))
            c.commit()
            raise PackError("grant_failed") from e
        if not (isinstance(res, dict) and res.get("success")):
            c.execute("UPDATE packs SET error=? WHERE pack_id=?", (str(res)[:300], pack_id))
            c.commit()
            raise PackError("grant_failed")
        gift = {k: v for k, v in gift.items() if k != "line_schema"}
        gift["promo_order_id"] = res.get("promo_order_id")
        gift["card"] = card_text(gift)
        state = "auto_opened" if auto else "opened"
        c.execute("UPDATE packs SET state=?, opened_at=?, gift_json=?, error=NULL WHERE pack_id=?",
                  (state, _iso(_now()), json.dumps(gift), pack_id))
        c.commit()
        return _row(c.execute("SELECT * FROM packs WHERE pack_id=?", (pack_id,)).fetchone())


def auto_open_expired(*, crm: Any, games: list[dict]) -> dict:
    """Nightly: a pack left sealed for 14 days opens itself and the gift is granted anyway."""
    now = _iso(_now())
    with closing(_db()) as c:
        ids = [r[0] for r in c.execute("SELECT pack_id FROM packs WHERE state='sealed' AND expires_at <= ?", (now,))]
    done, failed = 0, 0
    for pid in ids:
        try:
            open_pack(pid, customer_id=None, crm=crm, games=games, auto=True)
            done += 1
        except PackError:
            failed += 1
    return {"opened": done, "failed": failed}


# ------------------------------------------------------------------ web
def register(app) -> None:
    import secrets as _secrets

    from flask import abort, jsonify, redirect, render_template, request, session, url_for

    BRAND_STATIC = Path(__file__).resolve().parent / "static" / "brands" / "lottosonline"
    _geometry = {"data": None}

    def geometry() -> dict:
        if _geometry["data"] is None:
            _geometry["data"] = json.loads((BRAND_STATIC / "img" / "packs" / "geometry.json").read_text())
        return _geometry["data"]

    def _cid() -> int | None:
        c = session.get("customer") if isinstance(session.get("customer"), dict) else None
        try:
            return int(c["id"]) if c and c.get("id") is not None else None
        except (TypeError, ValueError):
            return None

    def _csrf_ok() -> bool:
        sent = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "").strip()
        want = session.get("csrf_token") if isinstance(session.get("csrf_token"), str) else ""
        return bool(sent and want and _secrets.compare_digest(sent, want))

    def _engine():
        return app.config["LO_ENGINE"]

    def _games() -> list[dict]:
        try:
            return _engine()["store_games_cached"]() or []
        except Exception:
            return []

    def stage_context(pack: dict) -> dict:
        tier = pack.get("tier") if pack.get("tier") in ("standard", "premium") else "standard"
        layers = {
            "shadow": "img/packs/shared/01-shadow.webp", "pack_back": f"img/packs/{tier}/02-pack-back.webp",
            "pack_front": f"img/packs/{tier}/03-pack-front.webp", "tear_strip": f"img/packs/{tier}/04-tear-strip.webp",
            "pack_torn_edge": "img/packs/shared/05-pack-torn-edge.webp",
            "strip_torn_edge": "img/packs/shared/06-strip-torn-edge.webp",
            "pack_interior": "img/packs/shared/07-pack-interior.webp", "card_back": f"img/packs/{tier}/08-card-back.webp",
            "card_hero": "img/packs/shared/09-card-hero.webp", "foil_sheen": "img/packs/shared/10-foil-sheen.webp",
            "glow": "img/packs/shared/11-glow.webp", "sparkle": "img/packs/shared/12-sparkle.webp",
        }
        lo_asset = app.config["LO_ASSET"]
        gift = pack.get("gift") if pack.get("state") != "sealed" else None
        return {"pack": pack, "layers": {k: lo_asset(v) for k, v in layers.items()}, "geometry": geometry(),
                "card": (gift or {}).get("card")}

    app.jinja_env.globals["lo_pack_stage"] = stage_context

    @app.get("/account/packs")
    def account_packs():
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next=request.path))
        return render_template("lo/packs.html", packs=customer_packs(cid), noindex="noindex, nofollow")

    @app.get("/packs/<pack_id>")
    def pack_page(pack_id: str):
        cid = _cid()
        if cid is None:
            return redirect(url_for("login", next=request.path))
        pack = get_pack(pack_id, cid)
        if pack is None:
            abort(404)
        return render_template("lo/pack_page.html", stage=stage_context(pack), noindex="noindex, nofollow")

    @app.post("/packs/<pack_id>/open")
    def pack_open(pack_id: str):
        wants_json = "application/json" in (request.headers.get("Accept") or "")
        if not _csrf_ok():
            abort(400)
        cid = _cid()
        if cid is None:
            return (jsonify({"ok": False, "reason": "login_required"}), 401) if wants_json else redirect(url_for("login", next=f"/packs/{pack_id}"))
        try:
            pack = open_pack(pack_id, customer_id=cid, crm=_engine()["get_crm"](), games=_games())
        except PackError as e:
            if str(e) == "not_found":
                abort(404)
            app.logger.warning("pack %s for customer %s not opened: %s", pack_id, cid, e)
            if wants_json:
                return jsonify({"ok": False, "reason": str(e)}), 503
            return redirect(url_for("pack_page", pack_id=pack_id, error=1))
        if wants_json:
            card = (pack.get("gift") or {}).get("card") or {}
            return jsonify({"ok": True, "state": pack["state"], "card": card, "game_code": (pack.get("gift") or {}).get("game_code"),
                            "announce": f"Your gift: {card.get('sub', '')} on {card.get('title', '')}. {card.get('expiry', '')}."})
        return redirect(url_for("pack_page", pack_id=pack_id))

    @app.context_processor
    def _packs_ctx():
        # A pack earned by the order just placed opens on the order page: nobody has to go and find it.
        just = session.get("lo_pack_just_earned") if request.endpoint == "order_detail" else None
        pack = None
        if just:
            session.pop("lo_pack_just_earned", None)
            cid = _cid()
            pack = get_pack(just, cid) if cid is not None else None
            if pack and pack["state"] != "sealed":
                pack = None
        return {"lo_pack_now": stage_context(pack) if pack else None}

    def after_checkout(*, token: str | None, order_id: Any, items: list[dict]) -> None:
        """Called by checkout_submit once the CRM has accepted the order. Never raises."""
        cid = _cid()
        if cid is None or order_id is None:
            return
        try:
            crm = _engine()["get_crm"]()
            earned = on_order_placed(customer_id=cid, order_id=order_id, items=items,
                                     seed=(lambda: history_from_crm(crm, token, exclude_order_id=order_id)) if token else None)
            if earned:
                session["lo_pack_just_earned"] = earned[0]["pack_id"]
        except Exception as e:  # noqa: BLE001 - a pack must never break a purchase
            app.logger.warning("packs: order %s not evaluated: %s", order_id, e)

    app.config["LO_PACKS_AFTER_CHECKOUT"] = after_checkout

    @app.cli.command("packs-auto-open")
    def packs_auto_open_cmd():
        """Nightly: open packs left sealed for 14 days and grant their gifts."""
        print(auto_open_expired(crm=_engine()["get_crm"](), games=_games()))
