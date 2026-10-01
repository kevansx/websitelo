from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from crm_api import CRMClient, CRMError
from crm_cache import CRMCache


def is_sync_enabled() -> bool:
    return os.environ.get("CRM_SYNC_ENABLE", "0").strip() in {"1", "true", "True", "yes", "YES"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _seconds_since(ts: str | None) -> float | None:
    d = _parse_iso(ts)
    if not d:
        return None
    return (_utcnow() - d).total_seconds()


def should_sync(last_fetch_iso: str | None, interval_seconds: int) -> bool:
    age = _seconds_since(last_fetch_iso)
    if age is None:
        return True
    return age >= float(interval_seconds)


def _extract_policies_refresh_interval_seconds(policies_by_category: dict[str, Any] | None) -> int | None:
    if not isinstance(policies_by_category, dict):
        return None

    def _norm_key(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")

    preferred_names = [
        "refresh_interval",
        "refresh_interval_minutes",
        "refresh_interval_seconds",
        "website_policies_refresh_interval_seconds",
        "website_policies_refresh_seconds",
        "website_policies_refresh_interval_minutes",
        "website_policies_refresh_minutes",
    ]
    preferred_norm = [_norm_key(v) for v in preferred_names]

    found_name: str | None = None
    found_val: Any = None
    found_idx: int | None = None
    for _cat, policies in policies_by_category.items():
        if not isinstance(policies, dict):
            continue
        for name, pobj in policies.items():
            n = _norm_key(str(name or ""))
            if not n:
                continue
            try:
                idx = preferred_norm.index(n)
            except ValueError:
                continue
            if found_idx is None or idx < found_idx:
                found_idx = idx
                found_name = str(name)
                found_val = pobj

    if found_name is None:
        return None
    if isinstance(found_val, dict):
        raw_int = found_val.get("value_int")
    else:
        raw_int = found_val
    try:
        val = int(raw_int)
    except Exception:
        return None
    if val <= 0:
        return None
    key = _norm_key(found_name)
    if key == "refresh_interval" or "minute" in key:
        val = val * 60
    val = max(30, min(val, 7 * 24 * 3600))
    return int(val)


def sync_draw_results_incremental(
    client: CRMClient,
    cache: CRMCache,
    *,
    include_prize_tiers: bool = True,
    backfill_all_pages: bool = False,
    limit: int = 500,
    max_pages: int = 10_000,
    sleep_seconds: float = 0.25,
) -> dict[str, Any]:
    """
    Incremental sync using cursor (Winnow pattern).
    Stores cursor in sync_state under last_draw_results_cursor.
    """
    cursor = cache.get_state("last_draw_results_cursor", None)
    pages = 0
    draws_total = 0
    last_cursor = cursor
    has_more = False

    for _ in range(max_pages):
        params: dict[str, Any] = {
            "status": "completed",
            "limit": str(int(limit)),
            "include_prize_tiers": "1" if include_prize_tiers else "0",
        }
        if last_cursor:
            params["cursor"] = last_cursor

        resp = client._request("GET", "/api/v1/draw-results", service_key=True, params=params)
        draws = resp.get("draws") or []
        if not isinstance(draws, list):
            draws = []
        cache.upsert_draw_results_page([d for d in draws if isinstance(d, dict)], include_prize_tiers=include_prize_tiers)
        pages += 1
        draws_total += len(draws)

        has_more = bool(resp.get("has_more"))
        next_cursor = resp.get("next_cursor")
        if next_cursor:
            cache.set_state("last_draw_results_cursor", str(next_cursor))
            last_cursor = str(next_cursor)

        if not has_more or not backfill_all_pages:
            break
        time.sleep(max(0.0, float(sleep_seconds)))

    cache.set_state("last_draw_results_fetch_at", _utcnow().replace(microsecond=0).isoformat())
    # `has_more` is reported so the caller can tell "there is nothing left to
    # fetch" from "I stopped early", which decides whether it should come
    # straight back rather than wait out its usual interval.
    return {
        "pages": pages,
        "draws": draws_total,
        "cursor_before": cursor,
        "cursor_after": last_cursor,
        "has_more": has_more,
    }


def sync_countries_once(client: CRMClient, cache: CRMCache, *, timeout_seconds: int | None = None) -> dict[str, Any]:
    """
    Fetch the brand-scoped countries table (including blocked + inactive) and store in SQLite.
    """
    resp = client._request(
        "GET",
        "/api/v1/countries",
        service_key=True,
        params={"active_only": "0", "include_blocked": "1"},
        timeout_seconds=timeout_seconds,
    )
    countries = resp.get("countries") or []
    if not isinstance(countries, list):
        countries = []
    cache.upsert_countries([c for c in countries if isinstance(c, dict)])
    return {"countries": len(countries)}


def sync_website_policies_once(client: CRMClient, cache: CRMCache) -> dict[str, Any]:
    resp = client._request("GET", "/api/v1/website/policies", service_key=True)
    policies_by_category = resp.get("policies_by_category") or {}
    if not isinstance(policies_by_category, dict):
        policies_by_category = {}
    count = cache.upsert_website_policies(policies_by_category)
    refresh_s = _extract_policies_refresh_interval_seconds(policies_by_category)
    if refresh_s is not None:
        cache.set_state("website_policies_refresh_interval_seconds", str(int(refresh_s)))
    return {"policies": count, "refresh_interval_seconds": refresh_s}


def sync_product_prices_once(client: CRMClient, cache: CRMCache) -> dict[str, Any]:
    """
    Fetch store games/products and persist a flattened per-product price snapshot.
    Used as a controlled fallback when quote totals are temporarily unavailable.

    The snapshot is optional, and a cache with nowhere to put it skips instead
    of raising. `_get_cached_product_price_lookup` in app.py reads it back
    through getattr for the same reason, and the fallback that actually fires
    reads `prices_by_currency` out of the store-games cache, so nothing depends
    on this table existing.
    """
    store = getattr(cache, "upsert_product_prices", None)
    if not callable(store):
        # Stamped even though nothing was stored, so the job settles onto its
        # normal interval instead of asking the CRM for the games list every
        # five minutes only to throw the answer away.
        cache.set_state("last_product_prices_fetch_at", _utcnow().replace(microsecond=0).isoformat())
        return {"products": 0, "skipped": "cache cannot store product prices"}

    resp = client._request("GET", "/api/v1/store/games", service_key=True)
    games = resp.get("games") or []
    if not isinstance(games, list):
        games = []

    products_out: list[dict[str, Any]] = []
    for g in games:
        if not isinstance(g, dict):
            continue
        game_code = str(g.get("game_code") or "").strip().lower()
        merged: list[dict[str, Any]] = []
        for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
            v = g.get(k)
            if isinstance(v, list):
                merged.extend([p for p in v if isinstance(p, dict)])
            elif isinstance(v, dict):
                merged.append(v)
        for p in merged:
            row = dict(p)
            if game_code and not row.get("game_code"):
                row["game_code"] = game_code
            products_out.append(row)

    count = store(products_out)
    # Without this the job looked like it had never run and repeated on every
    # pass of the loop.
    cache.set_state("last_product_prices_fetch_at", _utcnow().replace(microsecond=0).isoformat())
    return {"products": count}


def run_with_backoff(
    *args: Any,
    max_attempts: int = 5,
    base_sleep_seconds: float = 1.0,
) -> Any:
    """
    Supports both call styles:
      - Winnow style: run_with_backoff(fn, cache, "state_prefix")
      - Legacy LE style: run_with_backoff("name", fn, cache)
    """
    if len(args) < 3:
        raise TypeError("run_with_backoff requires 3 positional args")

    if callable(args[0]):
        fn = args[0]
        cache = args[1]
        state_prefix = str(args[2])
    else:
        state_prefix = str(args[0])
        fn = args[1]
        cache = args[2]

    if not callable(fn) or not isinstance(cache, CRMCache):
        raise TypeError("run_with_backoff invalid args")

    delay = max(0.1, float(base_sleep_seconds))
    last_exc: Exception | None = None
    for attempt in range(1, int(max_attempts) + 1):
        try:
            out = fn()
            cache.set_state(f"{state_prefix}_last_error", None)
            cache.set_state(f"{state_prefix}_last_error_at", None)
            cache.set_state(f"sync_error:{state_prefix}", None)
            return out
        except CRMError as exc:
            last_exc = exc
            cache.set_state(f"{state_prefix}_last_error", str(exc)[:400])
            cache.set_state(f"{state_prefix}_last_error_at", _utcnow().replace(microsecond=0).isoformat())
            cache.set_state(f"sync_error:{state_prefix}", str(exc)[:400])
            if attempt >= int(max_attempts):
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 60.0)
        except Exception as exc:
            last_exc = exc
            cache.set_state(f"{state_prefix}_last_error", repr(exc)[:400])
            cache.set_state(f"{state_prefix}_last_error_at", _utcnow().replace(microsecond=0).isoformat())
            cache.set_state(f"sync_error:{state_prefix}", repr(exc)[:400])
            if attempt >= int(max_attempts):
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 60.0)

    if last_exc:
        raise last_exc
    raise RuntimeError("run_with_backoff failed without an exception")


def start_background_sync(sync_fn: Callable[[], None], *, interval_seconds: int = 300) -> None:
    if not is_sync_enabled():
        return

    def _loop() -> None:
        while True:
            try:
                sync_fn()
            except Exception:
                # Intentionally swallow exceptions; production should log to stderr/journald.
                pass
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="crm_sync_loop", daemon=True)
    t.start()

