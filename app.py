from __future__ import annotations


def _debug_print(*args, **kwargs):
    """The cart's diagnostic prints (inherited) flood the server log on every page view; off unless
    DEBUG_PRINTS=1."""
    import os as _os
    if _os.environ.get("DEBUG_PRINTS") == "1":
        print(*args, **kwargs)

import json
import html
import ast
import os
import random
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from urllib.parse import urlparse
from ipaddress import ip_address
from typing import Any

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    has_request_context,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from itsdangerous import URLSafeTimedSerializer
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import RequestRedirect

import blog_content
import retired_content
import lo_lotteries
import seo
from brand_config import BrandConfig, load_brand_config
from crm_api import CRMClient, CRMError, load_crm_config_from_env
from crm_cache import CacheConfig, CRMCache
from crm_sync import run_with_backoff, should_sync, start_background_sync, sync_countries_once, sync_draw_results_incremental, sync_product_prices_once, sync_website_policies_once
from mkt_api import MktClient, load_mkt_config_from_env

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip() in {"1", "true", "True", "yes", "YES"}


def _env_first(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def _github_pull_fernet() -> Fernet | None:
    if Fernet is None:
        return None
    key = (os.getenv("GITHUB_PULL_FERNET_KEY") or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        return None


def _github_pat_encrypt(pat: str) -> str | None:
    f = _github_pull_fernet()
    if not f:
        return None
    try:
        return f.encrypt((pat or "").encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def _github_pat_decrypt(enc: str) -> str | None:
    f = _github_pull_fernet()
    if not f:
        return None
    try:
        return f.decrypt((enc or "").encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None
    except Exception:
        return None


def _redact_secret(text: str, secret: str) -> str:
    if not text:
        return ""
    if not secret:
        return text
    return text.replace(secret, "***REDACTED***")


def _parse_lines_json(raw: str) -> list[dict[str, Any]]:
    """
    Parse line payloads from forms with tolerant fallbacks.
    Accepts strict JSON and legacy/python-literal-like payloads.
    """
    payload = (raw or "").strip()
    if not payload:
        return []

    # Browser form values may be HTML-escaped in edge cases.
    payload = html.unescape(payload)

    try:
        parsed = json.loads(payload)
    except Exception:
        # Some older payloads use single quotes (python literal style).
        try:
            parsed = ast.literal_eval(payload)
        except Exception as e:
            raise ValueError(str(e)) from e

    if not isinstance(parsed, list):
        raise ValueError("lines_json must be a JSON array")
    return parsed


def _as_config_object(value: Any) -> dict[str, Any]:
    """
    A `config_json` payload, whichever way the CRM sent it.

    It used to arrive as an escaped JSON string and now arrives as a parsed
    object. Both shapes are on the wire depending on which side deployed first,
    and a reader that understands only one of them loses the draw schedule
    without saying anything.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


_WEEKDAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# WhatsApp, Facebook and X crop a link preview towards 1.91:1, and to a square
# thumbnail in small layouts, so the card is 1200x630 with the logo centred.
SHARE_CARD_PATH = "brands/lottosonline/img/og-default.png"  # the old site's og:image (logolarge.png)
# The header's own raster logo, for structured data that names the publisher.
BRAND_LOGO_PATH = "brands/lottosonline/img/logo-square.png"

# Pages of draw results one pass of the background sync will pull before
# handing back to the loop. At 500 draws a page this is a large catch-up in a
# single run while keeping the run far shorter than the interval between them,
# so a backfill cannot overlap the next pass or hold the sync lock past its TTL.
_DRAW_RESULTS_PAGES_PER_RUN = 20

# How far back the results page looks when it tops itself up from the CRM. The
# bulk draw-results endpoint is ordered oldest-updated-first because it exists
# to drive the incremental sync, so an unwindowed page for a game with a long
# history returns draws from months ago and never the newest one. Windowing by
# draw date keeps the response small enough that the latest draw is always in it.
_RESULTS_LIVE_WINDOW_DAYS = 120


def _schedule_sentence(schedule: Any) -> str:
    """
    The draw run in words: "Your numbers play every Monday, Wednesday and
    Saturday for 4 weeks — 12 draws."

    One board enters every draw in the run. `draws_count` is a label on that
    board and never a reason to draw more of them, which is the mistake this
    sentence exists to head off.
    """
    cfg = _as_config_object(schedule)
    if not cfg:
        return ""

    days: list[str] = []
    raw_days = cfg.get("draw_weekdays")
    if isinstance(raw_days, list):
        for entry in raw_days:
            name = str(entry or "").strip().lower()
            if name in _WEEKDAY_ORDER and name not in days:
                days.append(name)
    days.sort(key=_WEEKDAY_ORDER.index)
    labels = [d.capitalize() for d in days]
    if len(labels) > 1:
        day_text = ", ".join(labels[:-1]) + " and " + labels[-1]
    else:
        day_text = labels[0] if labels else ""

    def _count(key: str) -> int:
        try:
            return int(float(cfg.get(key)))
        except Exception:
            return 0

    weeks = _count("draw_weeks")
    draws = _count("draws_count")
    if not day_text and not weeks and not draws:
        return ""

    sentence = "Your numbers play " + (f"every {day_text}" if day_text else "in every draw")
    if weeks:
        sentence += f" for {weeks} week{'s' if weeks != 1 else ''}"
    if draws:
        sentence += f" \u2014 {draws} draw{'s' if draws != 1 else ''}"
    return sentence + "."


def _line_has_any_selection(line: Any) -> bool:
    """Best-effort guard against blank line payloads like {} or empty values."""
    if not isinstance(line, dict):
        return False
    for v in line.values():
        if isinstance(v, list):
            if any(str(x).strip() for x in v):
                return True
        elif isinstance(v, (int, float)):
            return True
        elif isinstance(v, str):
            if v.strip():
                return True
        elif v:
            return True
    return False


def _generate_quickpick_lines(line_schema: dict[str, Any] | list[dict[str, Any]] | None, num_lines: int) -> list[dict[str, Any]]:
    """
    Generate quickpick lines based on a line schema.
    
    Args:
        line_schema: Can be:
            - Dict with "groups" key: {"groups": [{"name": "main", "min": 1, "max": 50, "count": 5}, ...]}
            - List of groups directly: [{"name": "main", "min": 1, "max": 50, "count": 5}, ...]
        num_lines: Number of lines to generate
        
    Returns:
        List of line dicts, e.g. [{"main": [1, 2, 3, 4, 5], "megaball": 7}, ...]
    """
    groups = None
    if isinstance(line_schema, dict):
        groups = line_schema.get("groups")
    elif isinstance(line_schema, list):
        groups = line_schema
    
    if not isinstance(groups, list) or not groups:
        return []
    
    lines = []
    for _ in range(num_lines):
        line = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name") or "").strip()
            if not name:
                continue
            min_val = int(group.get("min") or 1)
            max_val = int(group.get("max") or 50)
            count = int(group.get("count") or 1)
            
            # Generate random unique numbers
            available = list(range(min_val, max_val + 1))
            if len(available) < count:
                count = len(available)
            if count <= 0:
                continue
            chosen = random.sample(available, count)
            chosen.sort()
            
            # For single-value fields (like megaball), store as int; for multi-value, store as list
            if count == 1:
                line[name] = chosen[0] if chosen else min_val
            else:
                line[name] = chosen
        if line:
            lines.append(line)
    
    return lines


def create_app() -> Flask:
    load_dotenv()  # server supplies /opt/.../.env; local dev can use .env too

    app = Flask(__name__, static_folder="static", template_folder="templates")
    import fake_crm
    fake_crm.install()  # local preview only; refuses to run unless WEBSITE_ENV=local
    lo_lotteries.register_converters(app)

    # Azure Front Door (or nginx) terminates TLS and forwards requests to this
    # app over an internal hop. Honor the standard X-Forwarded-* headers so that
    # request.url_root / request.is_secure reflect the public https origin.
    # This is required for correct payment return URLs and Secure cookies.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    app.config["SECRET_KEY"] = os.environ.get("WEBSITE_SECRET_KEY", "dev-insecure-change-me")
    # How fast a sign-up form can be filled in before we stop believing a
    # person filled it in. Nobody reads this form in under two seconds; a
    # script submits in milliseconds. Configurable so it can be loosened
    # without a deploy if it ever turns out to catch someone real.
    app.config["SIGNUP_MIN_SECONDS"] = float(os.environ.get("SIGNUP_MIN_SECONDS", "2"))
    app.config["WEBSITE_PORT"] = int(os.environ.get("WEBSITE_PORT", "8003"))

    # Cookie hardening. Secure defaults to on (production); set
    # SESSION_COOKIE_SECURE=0 for local http development.
    # SameSite=Lax (not Strict) so the session survives the top-level GET
    # redirect back from the payment processor.
    app.config["SESSION_COOKIE_SECURE"] = _env_bool("SESSION_COOKIE_SECURE", True)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Startup build marker (helps verify server restarts / code reloads).
    app.config["BUILD_ID"] = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    brand = load_brand_config()
    app.config["BRAND_CONFIG"] = brand

    # Wallet top-up processor selection:
    # - default: let CRM use its currently selected processor (no processor field sent)
    # - optional override via env for targeted testing
    topup_processor_override = (_env_first("WALLET_TOPUP_PROCESSOR") or "").strip().lower()
    app.config["WALLET_TOPUP_PROCESSOR_OVERRIDE"] = topup_processor_override

    cache_db_path = os.environ.get("CRM_CACHE_DB_PATH", "./data/crm_cache.sqlite")
    cache_brand = os.environ.get("WEBSITE_BRAND", "lottosonline").strip() or "lottosonline"
    app.config["CRM_CACHE"] = CRMCache(CacheConfig(db_path=cache_db_path, brand=cache_brand))
    app.config["LEGACY_RESOURCES_DIR"] = os.path.join(app.static_folder, "brands", "engine")

    # Assets asked for by version (`?v=<build_id>`) can be held indefinitely,
    # because a new build changes the URL. Images and fonts are stable enough to
    # cache for a month. Anything else — chiefly the few scripts the layout
    # includes without a version — gets an hour, so a deploy still reaches people
    # the same day.
    _ASSET_LONG_CACHE_SUFFIXES = (
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
    )

    @app.get("/resources/<path:filename>")
    def legacy_resources(filename: str):
        # Serve assets at the same paths the legacy PHP site used:
        # - /resources/css/*
        # - /resources/js/*
        # - /resources/images/*
        versioned = bool((request.args.get("v") or "").strip())
        long_lived = versioned or filename.lower().endswith(_ASSET_LONG_CACHE_SUFFIXES)
        resp = send_from_directory(
            app.config["LEGACY_RESOURCES_DIR"],
            filename,
            max_age=2592000 if long_lived else 3600,
        )
        if versioned:
            resp.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        return resp

    def _safe_next_url(raw_next: str | None, default: str) -> str:
        """
        Prevent redirects to non-local URLs and to routes that do not support GET.
        This avoids landing on 405 pages when 'next' points at POST-only endpoints
        like /cart/add or /checkout.
        """
        if not raw_next:
            return default
        try:
            p = urlparse(str(raw_next))
        except Exception:
            return default
        # Only allow local paths (no scheme/host).
        if p.scheme or p.netloc:
            return default
        path = (p.path or "").strip()
        if not path.startswith("/"):
            return default

        # Ensure the path supports GET in our Flask routing table.
        try:
            adapter = app.url_map.bind(request.host, url_scheme=request.scheme)
            adapter.match(path, method="GET")
        except (NotFound, MethodNotAllowed, RequestRedirect):
            return default
        except Exception:
            return default

        # Preserve query/fragment for in-page anchors (e.g. /account#wallet).
        qs = f"?{p.query}" if p.query else ""
        frag = f"#{p.fragment}" if p.fragment else ""
        return f"{path}{qs}{frag}"

    def _safe_game_code(game_code: str | None) -> str:
        gc = (game_code or "").strip().lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", gc):
            return gc
        return ""

    def _resolve_edit_order_url(candidate: str | None = None) -> str:
        # Keep "edit your order" behavior deterministic and legacy-like.
        c = (candidate or "").strip()
        if c.startswith("/") and not c.startswith("//"):
            return c
        s_edit = session.get("cart_edit_order_url")
        if isinstance(s_edit, str) and s_edit.startswith("/") and not s_edit.startswith("//"):
            return s_edit
        s_gc = _safe_game_code(session.get("cart_last_game_code") if isinstance(session.get("cart_last_game_code"), str) else "")
        if s_gc:
            return url_for("play", game_code=s_gc)
        lp = session.get("last_play_url")
        if isinstance(lp, str) and lp.startswith("/") and not lp.startswith("//"):
            return lp
        return url_for("home")

    def _wallet_funding(wallet: dict[str, Any] | None) -> dict[str, int]:
        """
        A wallet in the parts checkout actually spends from.

        The CRM holds two pots: money the customer deposited, and money they
        won. Checkout spends deposits, and it will not touch winnings unless
        the request says `use_wins: true`, which the customer has to authorise.
        So "can they afford this" has two different answers and the site has to
        know which one it is giving.

        Every total in the response is a trap for this. `balance_cents` is
        deposits plus winnings. `available_balance_cents` is also both, just
        after reservations - it is not "what they can spend without touching
        winnings", which is the reading that cost A1009227 four refusals
        against a wallet holding nearly three times the cart.

        The one figure checkout will honour by default is available deposits,
        and that has to be derived: added funds less what is reserved
        against them.
        """
        w = wallet if isinstance(wallet, dict) else {}

        def _cents(*keys: str) -> int:
            for key in keys:
                if w.get(key) is not None:
                    try:
                        return int(w.get(key) or 0)
                    except Exception:
                        return 0
            return 0

        total = _cents("balance_cents")
        added = _cents("added_funds_balance_cents")
        wins = _cents("wins_balance_cents")
        # Responses that predate the split wallet give a total and nothing
        # else. Calling that zero deposits would tell a funded customer they
        # have nothing, so the total stands in for deposits until the CRM says
        # otherwise.
        if not w.get("added_funds_balance_cents") and not w.get("wins_balance_cents"):
            added = total
            wins = 0
        reserved_added = _cents("reserved_added_funds_cents")
        reserved_wins = _cents("reserved_wins_cents")
        available_added = max(0, added - reserved_added)
        available_wins = max(0, wins - reserved_wins)
        return {
            "total_cents": total,
            "added_cents": added,
            "wins_cents": wins,
            "reserved_added_cents": reserved_added,
            "reserved_wins_cents": reserved_wins,
            # What a submit with the default `use_wins: false` can spend.
            "spendable_cents": available_added,
            # What it could spend if the customer authorises their winnings.
            "spendable_with_wins_cents": available_added + available_wins,
            "available_wins_cents": available_wins,
        }

    def _wallet_spendable_cents(wallet: dict[str, Any] | None) -> int:
        """Deposits available to a default checkout, which is what it will spend."""
        return _wallet_funding(wallet)["spendable_cents"]

    def _cart_funding(
        quote: dict[str, Any] | None,
        wallet: dict[str, Any] | None,
        required_cents: int,
    ) -> dict[str, Any]:
        """
        How this cart can be paid for, preferring the CRM's own arithmetic.

        `quote.funding` is the CRM answering the question against this exact
        quote, with this customer's reservations already taken out, and it is
        the same calculation `/checkout/submit` will perform. Deriving it here
        instead would mean two implementations of one rule, diverging quietly
        until a customer is refused for money they hold.

        It is absent for guests and for tenants still on the older contract, so
        the wallet stands in. That fallback is good enough to choose which
        message to show and is never treated as authoritative: the submit
        still decides, and its 402 is handled on the same terms as this.
        """
        w = _wallet_funding(wallet)
        required = max(0, int(required_cents or 0))
        f = quote.get("funding") if isinstance(quote, dict) else None

        if not isinstance(f, dict):
            added = w["spendable_cents"]
            wins = w["available_wins_cents"]
            # A 402 the CRM told us to recover by asking about winnings beats
            # anything inferred from the wallet, because it was measured
            # against this cart at submit.
            hint = _wins_prompt_get()
            if hint and int(hint.get("required_cents") or 0) == required:
                added = int(hint.get("added_cents") or 0)
                wins = int(hint.get("wins_cents") or 0)
            return {
                "source": "402" if hint else "wallet",
                "total_cents": w["total_cents"] or (added + wins),
                "spendable_cents": added,
                "available_wins_cents": wins,
                "shortfall_without_wins_cents": max(0, required - added),
                "shortfall_with_wins_cents": max(0, required - (added + wins)),
                "wins_cover_cents": min(wins, max(0, required - added)),
            }

        def _cents(key: str) -> int:
            try:
                return int(f.get(key) or 0)
            except Exception:
                return 0

        short_without = max(0, _cents("shortfall_without_wins_cents"))
        short_with = max(0, _cents("shortfall_with_wins_cents"))

        # Back out what the CRM had available rather than reading the balance
        # fields, which carry the same names as the wallet's gross figures and
        # so may not have reservations taken off. A shortfall is a subtraction
        # the CRM already did correctly, and inverting it cannot disagree with
        # the answer submit will give.
        if short_without > 0:
            added = max(0, required - short_without)
        else:
            added = _cents("added_funds_balance_cents") or w["spendable_cents"]
        if short_without > 0 and short_with > 0:
            wins = max(0, short_without - short_with)
        else:
            wins = _cents("wins_balance_cents") or w["available_wins_cents"]
            if short_without > 0 and short_with <= 0:
                # Winnings are known to close the gap even if the reported
                # figure is stale or missing.
                wins = max(wins, short_without)

        return {
            "source": "quote",
            "total_cents": w["total_cents"] or (added + wins),
            "spendable_cents": added,
            "available_wins_cents": wins,
            "shortfall_without_wins_cents": short_without,
            "shortfall_with_wins_cents": short_with,
            "wins_cover_cents": min(wins, short_without),
        }

    def _pending_checkout_get() -> dict:
        ctx = session.get("pending_checkout")
        return ctx if isinstance(ctx, dict) else {}

    def _pending_checkout_set(**values: Any) -> dict:
        ctx = _pending_checkout_get()
        for key, value in values.items():
            if value is None or value == "":
                ctx.pop(str(key), None)
            else:
                ctx[str(key)] = value
        if ctx:
            session["pending_checkout"] = ctx
        else:
            session.pop("pending_checkout", None)
        return ctx

    def _pending_checkout_clear() -> None:
        session.pop("pending_checkout", None)

    def _wins_prompt_set(*, required_cents: int, added_cents: int, wins_cents: int) -> None:
        """
        Remember that submit refused for want of authorisation, not money.

        The cart re-quotes on load and will usually work this out again from
        `quote.funding`, but that object is not on every tenant or every quote
        shape. Without this, a 402 the CRM explicitly says is recoverable
        would land the customer back on a cart that has forgotten why.
        """
        session["checkout_wins_prompt"] = {
            "required_cents": int(required_cents or 0),
            "added_cents": int(added_cents or 0),
            "wins_cents": int(wins_cents or 0),
        }

    def _wins_prompt_get() -> dict[str, int]:
        ctx = session.get("checkout_wins_prompt")
        return ctx if isinstance(ctx, dict) else {}

    def _wins_prompt_clear() -> None:
        session.pop("checkout_wins_prompt", None)

    # Everything that belongs to one signed-in customer. A support handoff
    # arrives in whatever session the staff browser already had, which may be
    # another customer's, so all of this goes before the new token arrives.
    # Leaving any of it behind means one customer's cart, wallet or billing
    # address showing up under another's name.
    _CUSTOMER_SESSION_KEYS = (
        # Who they are.
        "crm_token",
        "customer",
        "email_verified_hint",
        "email_verify_banner_dismissed_at",
        "time_on_site_started_at",
        "register_prefill_currency",
        # Credentials that arrived in a link. None of these belong to whoever
        # the support session is about to become.
        "set_password_token",
        "reactivation_token",
        "legacy_signup_token",
        "password_reset_token",
        "payment_link_token",
        # The cart and the checkout built around it.
        "cart_items",
        "cart_edit_order_url",
        "cart_last_game_code",
        "cart_force_purchase_topup",
        "pending_cart_add",
        "pending_line_edit",
        "checkout_quote_id",
        "checkout_selected_checkout_offers",
        "checkout_bundle_slug",
        "checkout_bundle_locked_cents",
        "checkout_bundle_currency",
        "checkout_wins_prompt",
        "pending_checkout",
        "last_purchase_cart",
        "mkt_checkout_started_uuid",
        "mkt_checkout_attempt_id",
        "pricing_fallback_warned_at",
        # Wallet and payment context, including a staged billing address.
        "wallet",
        "topup_routing_advances",
        "topup_country_asked",
        "topup_address",
        # Account UI state, which is per-customer and would otherwise be
        # inherited: filters, paging and a cached transaction summary.
        "acct_txn_show",
        "acct_txn_filters",
        "acct_order_show",
        "acct_order_filters",
        "acct_winnings_show",
        "acct_winnings_filters",
        "acct_notification_prefs",
        "acct_txn_summary",
        "legacy_orders_available",
    )

    def _clear_customer_session() -> None:
        """Forget the customer entirely, including their cart and payment state."""
        for key in _CUSTOMER_SESSION_KEYS:
            session.pop(key, None)
        _checkout_promo_set(None)

    def _support_session() -> dict[str, Any]:
        """
        The read-only support marker, or nothing once it has run out.

        The bearer token the CRM issues for a handoff dies after an hour, and
        an expired marker would leave staff looking at a page that says
        read-only above content no request can fetch. Expiry is checked on
        every read so the session ends on its own rather than at the next
        failure.
        """
        ctx = session.get("customer_login_as")
        if not isinstance(ctx, dict):
            return {}
        try:
            expires_at = int(ctx.get("expires_at") or 0)
        except Exception:
            expires_at = 0
        if expires_at and int(time.time()) >= expires_at:
            _clear_customer_session()
            session.pop("customer_login_as", None)
            return {}
        return ctx

    def _support_session_active() -> bool:
        return bool(_support_session())

    def _extract_intent_id(init_payload: dict[str, Any] | None) -> str:
        if not isinstance(init_payload, dict):
            return ""
        intent_id = str(init_payload.get("intent_id") or init_payload.get("id") or "").strip()
        if intent_id:
            return intent_id
        # API 58 status shape nests the intent: {"intent": {"id": ...}}.
        intent_obj = init_payload.get("intent")
        if isinstance(intent_obj, dict):
            nested = str(intent_obj.get("id") or "").strip()
            if nested:
                return nested
        try:
            charge_url = (((init_payload.get("options") or {}).get("direct_card") or {}).get("charge_url") or "").strip()
            m = re.search(r"/wallet/topup/([^/]+)/charge", charge_url)
            if m:
                return str(m.group(1)).strip()
            card_form_url = str(init_payload.get("crm_card_form_url") or "").strip()
            m2 = re.search(r"/wallet/topup/([^/]+)/card", card_form_url)
            if m2:
                return str(m2.group(1)).strip()
        except Exception:
            return ""
        return ""

    def _country_iso2_from_input(raw: str, countries: list[dict[str, Any]] | None = None) -> str:
        s = str(raw or "").strip()
        if not s:
            return ""
        if len(s) == 2 and s.isalpha():
            return s.upper()
        norm = re.sub(r"[^a-z]", "", s.lower())
        aliases = {
            "uk": "GB",
            "greatbritain": "GB",
            "unitedkingdom": "GB",
            "england": "GB",
            "scotland": "GB",
            "wales": "GB",
            "northernireland": "GB",
            "usa": "US",
            "unitedstates": "US",
            "unitedstatesofamerica": "US",
            "uae": "AE",
        }
        if norm in aliases:
            return aliases[norm]
        for c in countries or []:
            if not isinstance(c, dict):
                continue
            iso2 = str(c.get("iso2") or "").strip().upper()
            name = str(c.get("name") or "").strip()
            if not iso2 or not name:
                continue
            name_norm = re.sub(r"[^a-z]", "", name.lower())
            if norm == name_norm:
                return iso2
        return ""

    def _serialize_cart_for_rebuy(items: list[Any]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for raw in items[:20]:
            if not isinstance(raw, dict):
                continue
            item: dict[str, Any] = {}
            for key in ("kind", "product_code", "game_code", "game_name", "quantity", "product_id"):
                val = raw.get(key)
                if val is not None and val != "":
                    item[key] = val
            lines = raw.get("lines")
            if isinstance(lines, list):
                item["lines"] = [ln for ln in lines[:80] if isinstance(ln, dict)]
            config_json = _as_config_object(raw.get("config_json"))
            if config_json:
                item["config_json"] = config_json
            options = raw.get("options")
            if isinstance(options, dict):
                item["options"] = options
            if item:
                sanitized.append(item)
        return sanitized

    def _save_last_purchase_cart(items: list[Any], order_id: Any | None) -> None:
        snapshot_items = _serialize_cart_for_rebuy(items)
        if not snapshot_items:
            return
        session["last_purchase_cart"] = {
            "items": snapshot_items,
            "order_id": str(order_id) if order_id is not None else "",
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

    def _last_purchase_cart_items() -> list[dict[str, Any]]:
        payload = session.get("last_purchase_cart")
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [x for x in items if isinstance(x, dict)]

    def _checkout_promo_get() -> str | None:
        # Prefer compact key to keep cookie-backed session payload small.
        v = session.get("pc")
        if isinstance(v, str):
            s = v.strip()
            return s or None
        legacy = session.get("checkout_promo_code")
        if isinstance(legacy, str):
            s = legacy.strip()
            return s or None
        return None

    def _checkout_promo_set(promo: str | None) -> None:
        s = str(promo or "").strip() or None
        if s:
            session["pc"] = s
        else:
            session.pop("pc", None)
        # Remove legacy verbose key to reduce session payload.
        session.pop("checkout_promo_code", None)

    def _sync_selected_offers_from_cart() -> None:
        """Rebuild `selected_checkout_offers` from what is actually in the cart.

        The CRM only discounts an upsell if the quote carries its rule id, and it
        re-prices the same payload again at submit. If the site claims a discount the
        CRM was never told to apply, the two totals disagree and the order is rejected
        as a price mismatch — which is exactly what was happening here.

        Deriving the selection from the cart rather than tracking it separately means a
        removed upsell cannot leave a stale rule id behind. That would fail the other
        way: the CRM would insist on an offered item the cart no longer holds.
        """
        items = session.get("cart_items")
        if not isinstance(items, list):
            items = []
        rule_ids: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            rid = it.get("offer_rule_id")
            if rid in (None, "", 0):
                continue
            rid_s = str(rid).strip()
            if rid_s and rid_s not in rule_ids:
                rule_ids.append(rid_s)
        if rule_ids:
            session["checkout_selected_checkout_offers"] = rule_ids
        else:
            session.pop("checkout_selected_checkout_offers", None)
        session.pop("checkout_quote_id", None)

    # The documented checkout cart-item contract. The session carries extra
    # bookkeeping per item (upsell marker, rule id, price estimate) that has no
    # meaning to the CRM, and `options` is the field it prices add-ons from — a
    # private key in there reads as an unknown add-on.
    _CRM_ITEM_FIELDS = frozenset(
        {
            "kind",
            "product_code",
            "lines",
            "numbers",
            "options",
            "wheel_catalog_key",
            "wheel_pool_numbers",
            "ticket_mode",
            "draw_weeks",
            "draw_weekdays",
            "start_on_date",
            "product_id",
            "quantity",
            "config_json",
        }
    )

    def _crm_cart_items(items: Any, *, drop_schedule: bool = False) -> list[dict[str, Any]]:
        """
        Cart items reduced to the fields the checkout API defines.

        `drop_schedule` is for bundle carts. The CRM takes a bundle's draw run
        from the bundle's own config and overwrites whatever the caller sent, so
        passing ours adds nothing and a stray `draw_weeks` is a way to inflate a
        locked price. Ordinary carts keep sending theirs, because outside a
        bundle the website's schedule is the only one there is.
        """
        out: list[dict[str, Any]] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            clean = {k: v for k, v in it.items() if k in _CRM_ITEM_FIELDS and v is not None}
            if drop_schedule:
                for field in ("draw_weeks", "draw_weekdays", "start_on_date"):
                    clean.pop(field, None)
            opts = clean.get("options")
            if isinstance(opts, dict):
                clean["options"] = {k: v for k, v in opts.items() if not str(k).startswith("_")}
            if clean:
                out.append(clean)
        return out

    def _truncate_for_log(payload: Any, limit: int = 2000) -> str:
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            text = repr(payload)
        return text if len(text) <= limit else text[:limit] + "…(truncated)"

    def _quote_id_from(resp: Any, *, context: str, critical: bool = True) -> Any:
        """
        The id `/checkout/submit` needs, wherever the tenant puts it.

        Without an id the site can only reach the older `/api/v1/checkout`, which
        prices the cart on its own terms — so a missing id is the difference
        between a discounted order and a full-price one, and it has to be
        visible in the log rather than inferred later from takings.
        """
        candidates: list[Any] = []
        if isinstance(resp, dict):
            quote = resp.get("quote") if isinstance(resp.get("quote"), dict) else {}
            candidates = [resp.get("quote_id"), resp.get("id"), quote.get("quote_id"), quote.get("id")]
        for raw in candidates:
            if raw in (None, "", 0):
                continue
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int):
                return raw
            text = str(raw).strip()
            if text:
                return int(text) if text.lstrip("-").isdigit() else text
        # The cart can live without an id (checkout re-quotes), so it logs a
        # warning; at checkout the same gap decides how the order is priced.
        log = app.logger.error if critical else app.logger.warning
        log(
            "%s: no quote id in the /checkout/quote response — checkout cannot use "
            "/checkout/submit and any offer discount will be lost. keys=%s body=%s",
            context,
            sorted(resp.keys()) if isinstance(resp, dict) else type(resp).__name__,
            _truncate_for_log(resp),
        )
        return None

    def _eligible_offers_from(resp: Any) -> list[dict[str, Any]]:
        """
        Checkout offer rules the CRM says this cart can take.

        The rule id is what makes a discount happen — the site posts it back on
        the quote and again at submit — so the shape it arrives in must not be a
        single assumed key. `include_eligible_checkout_offers` is not implemented
        in the CRM, so nothing here depends on having asked for the list.
        """
        found: list[Any] = []
        containers = [resp if isinstance(resp, dict) else {}]
        if isinstance(resp, dict) and isinstance(resp.get("quote"), dict):
            containers.append(resp["quote"])
        for container in containers:
            for key in ("eligible_checkout_offers", "eligible_offers", "checkout_offers", "offers"):
                value = container.get(key)
                if isinstance(value, list) and value:
                    found = value
                    break
            if found:
                break
        return [x for x in found if isinstance(x, dict)]

    def _checkout_recovery_action(e: Exception) -> str | None:
        """
        Classify a CRM pricing rejection into the one thing that fixes it.

        `/checkout/submit` returns 409 when the stored quote no longer matches
        the cart and 400 when it expired; offer selections are refused when the
        cart doesn't hold the offered item at the exact line count the rule
        names; promo codes are refused on their own terms. Each of these is
        recoverable, so none of them should surface as a failed checkout.
        """
        if not isinstance(e, CRMError):
            return None
        payload = e.payload if isinstance(e.payload, dict) else {}
        code = str(payload.get("error_code") or "").strip().upper()
        text = " ".join(str(x) for x in (payload.get("error"), str(e)) if x).lower()
        if code.startswith("PROMO") or "promo" in text:
            return "clear_promo"
        if code in {"MISSING_LINES", "INVALID_LINES"} or "offer" in text:
            return "drop_offers"
        if e.status_code == 409 or "re-quote" in text or "quote has changed" in text or "expired" in text:
            return "requote"
        return None

    def _apply_checkout_recovery(action: str, e: Exception) -> bool:
        """Apply a recovery action. Returns False when nothing could be changed."""
        if action == "clear_promo":
            if not _checkout_promo_get():
                return False
            app.logger.info("checkout recovery: clearing rejected promo code (%s)", e)
            _checkout_promo_set(None)
            session.pop("checkout_quote_id", None)
            flash("That promo code isn't valid for this order, so it was removed. Your order total is updated.", "warning")
            return True
        if action == "drop_offers":
            if not (session.get("checkout_selected_checkout_offers") or []):
                return False
            app.logger.info(
                "checkout recovery: dropping offer selection %s refused by the CRM (%s)",
                session.get("checkout_selected_checkout_offers"),
                e,
            )
            session.pop("checkout_selected_checkout_offers", None)
            cart = session.get("cart_items")
            if isinstance(cart, list):
                for it in cart:
                    if isinstance(it, dict) and it.get("offer_rule_id") is not None:
                        it["offer_rule_id"] = None
                session["cart_items"] = cart
            session.pop("checkout_quote_id", None)
            flash("The extra-lines offer no longer applies to this cart, so it was removed. Your order total is updated.", "warning")
            return True
        if action == "requote":
            app.logger.info("checkout recovery: re-quoting after CRM reported a stale quote (%s)", e)
            session.pop("checkout_quote_id", None)
            return True
        return False

    def _quote_offer_discount_cents(q: dict[str, Any] | None) -> int:
        """
        What the CRM discounted for checkout offer rules, in display cents.

        Read from `discount_breakdown` rows of type `checkout_offer_rule`, which
        is the only place the applied offer amount is stated. Percentages and
        per-item estimates computed here would be numbers the CRM never agreed
        to, and it re-prices the same cart again at submit.
        """
        if not isinstance(q, dict):
            return 0
        total = 0
        for row in q.get("discount_breakdown") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("source_type") or "").strip().lower() != "checkout_offer_rule":
                continue
            for key in ("amount_in_customer_cents", "amount_cents", "amount_base_cents", "amount_eur_cents"):
                try:
                    value = row.get(key)
                    if value is not None:
                        total += max(0, int(float(value)))
                        break
                except Exception:
                    continue
        return total

    def _quote_applied_offer_rule_ids(q: dict[str, Any] | None) -> list[int]:
        """Offer rule ids the CRM reports as applied, per quote line."""
        if not isinstance(q, dict):
            return []
        found: list[int] = []
        for key in ("lines", "items"):
            for row in q.get(key) or []:
                if not isinstance(row, dict):
                    continue
                raw = row.get("applied_mm_offer_rule_id")
                if raw in (None, ""):
                    continue
                try:
                    rule_id = int(raw)
                except Exception:
                    continue
                if rule_id not in found:
                    found.append(rule_id)
        for row in q.get("discount_breakdown") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("source_type") or "").strip().lower() != "checkout_offer_rule":
                continue
            try:
                rule_id = int(row.get("source_id"))
            except Exception:
                continue
            if rule_id not in found:
                found.append(rule_id)
        return found

    def _quote_item_discounts_cents(q: dict[str, Any] | None) -> list[int]:
        """Per-item discount in display cents, positionally matching the cart."""
        if not isinstance(q, dict):
            return []
        rows = q.get("lines") if isinstance(q.get("lines"), list) else q.get("items")
        out: list[int] = []
        for row in rows if isinstance(rows, list) else []:
            amount = 0
            if isinstance(row, dict):
                for key in (
                    "discount_in_customer_cents",
                    "discount_cents",
                    "discount_base_cents",
                    "discount_eur_cents",
                ):
                    try:
                        value = row.get(key)
                        if value is not None:
                            amount = max(0, int(float(value)))
                            break
                    except Exception:
                        continue
            out.append(amount)
        return out

    def _quote_payable_cents(q: dict[str, Any] | None) -> int:
        """
        The amount the CRM will actually debit for a quote, in cents.

        This is the single authoritative figure for both the cart's affordability
        check and the confirm button: any website-side discount that the CRM has
        not applied would otherwise show the customer a total lower than what
        checkout debits, and the order is then rejected with a 402 for an amount
        they were never shown. Returns 0 when the quote carries no usable totals.
        """
        if not isinstance(q, dict):
            return 0

        def _to_int(v: Any) -> int | None:
            try:
                if v is None:
                    return None
                return int(float(v))
            except Exception:
                return None

        total_cents = None
        subtotal_cents = None
        discount_cents = 0

        for k in ("total_in_customer_cents", "total_cents", "total_eur_cents", "total_base_cents"):
            parsed = _to_int(q.get(k))
            if parsed is not None:
                total_cents = parsed
                break

        for k in ("subtotal_in_customer_cents", "subtotal_cents", "subtotal_eur_cents", "subtotal_base_cents"):
            parsed = _to_int(q.get(k))
            if parsed is not None:
                subtotal_cents = parsed
                break

        for k in ("discount_in_customer_cents", "discount_cents", "discount_eur_cents", "discount_base_cents"):
            parsed = _to_int(q.get(k))
            if parsed is not None and parsed > 0:
                discount_cents = parsed
                break

        if subtotal_cents is not None and subtotal_cents > 0 and discount_cents > 0:
            discounted_total = max(0, subtotal_cents - discount_cents)
            if total_cents is None or total_cents <= 0 or total_cents >= subtotal_cents:
                return discounted_total
            return max(0, total_cents)

        if total_cents is not None:
            return max(0, total_cents)
        if subtotal_cents is not None:
            return max(0, subtotal_cents)

        if isinstance(q.get("items"), list):
            try:
                return int(
                    sum(
                        int((it or {}).get("item_total_in_customer_cents") or 0)
                        for it in (q.get("items") or [])
                        if isinstance(it, dict)
                    )
                )
            except Exception:
                pass
        return 0

    def _topup_status_bucket(default_status: str | None, payload: dict | None = None) -> str:
        """
        Normalize mixed CRM/payment-provider status shapes into: pending|success|failed|cancelled.
        """
        candidates: list[str] = []
        if default_status:
            candidates.append(str(default_status))
        if isinstance(payload, dict):
            for k in ("status", "state", "result", "outcome"):
                v = payload.get(k)
                if isinstance(v, str) and v.strip():
                    candidates.append(v)
            for sub_key in ("topup", "intent"):
                sub = payload.get(sub_key)
                if isinstance(sub, dict):
                    for k in ("status", "state", "result", "outcome"):
                        v = sub.get(k)
                        if isinstance(v, str) and v.strip():
                            candidates.append(v)
        text = " ".join(candidates).strip().lower()
        if any(k in text for k in ("success", "succeed", "completed", "paid", "captured")):
            return "success"
        if any(k in text for k in ("cancel", "abandon", "void")):
            return "cancelled"
        if any(k in text for k in ("fail", "declin", "error", "reject", "expired")):
            return "failed"
        return "pending"

    def _topup_routing(payload: Any) -> dict[str, Any] | None:
        """Extract the Website Processor Rules `routing` object (API 58), if any."""
        if not isinstance(payload, dict):
            return None
        routing = payload.get("routing")
        return routing if isinstance(routing, dict) else None

    def _follow_topup_payment_instructions(resp: Any, token: str, next_url: str):
        """
        Follow the processor-neutral payment instructions of a top-up init
        response (API 58): redirect_url / next_action_url / hosted form /
        CRM card form, or start HPP from an options-mode response.
        Returns a Flask response, or None when no instruction is usable.
        """
        if not isinstance(resp, dict):
            return None
        if resp.get("redirect_url"):
            return redirect(str(resp["redirect_url"]))
        if resp.get("next_action_url"):
            return redirect(str(resp["next_action_url"]))
        redirect_obj = resp.get("redirect")
        if isinstance(redirect_obj, dict) and redirect_obj.get("action_url"):
            return render_template("wallet_topup_redirect_form.html", redirect_obj=redirect_obj)
        if resp.get("crm_card_form_url"):
            return redirect(str(resp["crm_card_form_url"]))
        intent_id = _extract_intent_id(resp)
        # Only start a hosted page the response actually offers one for.
        if intent_id and _topup_hosted_ready(resp):
            try:
                hpp = get_crm().wallet_topup_hpp_start(token, intent_id)
            except CRMError as e:
                # Swallowed silently until now, which made a refused hosted
                # start indistinguishable from never having attempted one.
                app.logger.warning("wallet_topup_hpp_start failed for intent %s: %s", intent_id, e)
                return None
            followed = _hosted_start_redirect(hpp)
            if followed is not None:
                return followed
            app.logger.warning(
                "wallet_topup_hpp_start returned no usable redirect for intent %s: %s",
                intent_id,
                _topup_response_shape(hpp),
            )
        return None

    def _hosted_start_redirect(hpp: Any):
        """
        Where a hosted-start response sends the customer, or None for nowhere.

        `mode` is deliberately not read. The same CRM endpoint has answered
        `hpp_redirect`, `hosted_redirect` and no mode at all, and the payment
        instruction is the URL, not the label beside it. Requiring the label
        put customers on "Hosted payment page unavailable" while holding a
        working payment URL — reported live 2026-09-09 on the campaign emails.
        """
        if not isinstance(hpp, dict):
            return None
        for key in ("redirect_url", "hosted_url", "next_action_url", "crm_card_form_url"):
            if hpp.get(key):
                return redirect(str(hpp[key]))
        redirect_obj = hpp.get("redirect")
        # The template posts `action_url` with `form_fields`; a redirect block
        # without one is a form with nowhere to submit to.
        if isinstance(redirect_obj, dict) and redirect_obj.get("action_url"):
            return render_template("wallet_topup_redirect_form.html", redirect_obj=redirect_obj)
        return None

    def _start_hosted_page(token: str, intent_id: str, next_url: str, *, on_failure: str = ""):
        """
        Send the customer to the processor's hosted page for an intent that
        already exists. Used when the CRM offers no direct-card option, when the
        customer chooses the hosted page, and when a charge is refused — in
        every case the alternative is leaving a created intent unpaid.
        """
        try:
            hpp = get_crm().wallet_topup_hpp_start(token, intent_id)
        except CRMError as e:
            app.logger.warning("wallet_topup_hpp_start failed for intent %s: %s", intent_id, e)
            # The CRM's own words win over `on_failure`. That text explains why
            # we came to the hosted page, which stops being the useful thing to
            # say the moment the hosted page gives a reason of its own - the
            # processor's reason is usually the only one a customer can act on,
            # as with CCM's "Ship address can not be empty".
            return redirect(
                url_for(
                    "wallet_payment_failed",
                    reason=_friendly_crm_error(e),
                    next=next_url or None,
                    intent_id=intent_id,
                )
            )
        started = _hosted_start_redirect(hpp)
        if started is not None:
            return started
        # What came back decides whether this is the CRM declining to open a
        # hosted page or the site failing to read one, and until now the log
        # said only that the customer had been turned away.
        app.logger.warning(
            "wallet_topup_hpp_start returned no usable redirect for intent %s: %s",
            intent_id,
            _topup_response_shape(hpp),
        )
        return redirect(
            url_for(
                "wallet_payment_failed",
                reason=on_failure or "Hosted payment page unavailable",
                next=next_url or None,
                intent_id=intent_id,
            )
        )

    def _topup_direct_card_processors() -> set[str]:
        """
        Processors whose intents the CRM will accept a direct card charge for.

        The CRM reports `options.direct_card.available` per intent, but has
        returned it true for processors whose charge endpoint then rejects the
        intent, so the routed processor is checked against this list too.

        It is configurable because it mirrors a rule the CRM owns. Hardcoding it
        meant that enabling Worldpay in the CRM sent every Worldpay-routed
        customer to a hosted page Worldpay was not set up for: the CRM refused
        the hosted start and the intent sat pending with nothing collected.
        A processor added CRM-side now needs an env change, not a deploy.
        """
        raw = os.environ.get("WALLET_DIRECT_CARD_PROCESSORS", "eltrovox,emerchant,worldpay,testing,traxx")
        return {p.strip().lower() for p in raw.split(",") if p.strip()}

    def _topup_hosted_ready(resp: Any) -> bool:
        """
        True when this init response advertises a hosted payment page.

        Not every processor has one. Worldpay and Z1 are direct-card only, and
        starting a hosted page for them calls a route the CRM does not have, so
        the customer sees a failure for a processor that was ready to take a
        card. Only the options the response actually carries are offered.
        """
        if not isinstance(resp, dict):
            return False
        options = resp.get("options")
        if not isinstance(options, dict):
            return False
        # `hpp` is the common shape; MEU and CCM advertise `hosted_checkout`.
        return any(bool(options.get(k)) and isinstance(options.get(k), dict) for k in ("hpp", "hosted_checkout"))

    def _topup_direct_card_offer(resp: Any) -> str:
        """
        How the CRM advertises direct card on this intent; "" for not at all.

        Two shapes are in the wild and they mean the same thing. Most
        processors answer `available: true` alongside a `charge_url`; TRAXX
        answers `allowed: true` with `status: "available"` and no URLs at all
        (confirmed by the CRM team 2026-09-02; API 60 documents neither). The
        URL is not the point — both charge and hosted start are addressed by
        intent id — so its absence is not a refusal. An absent or empty
        `direct_card` is, and stays, a no.

        Which of the two answered matters to the caller, because the site's
        allowlist was built to second-guess one of them and not the other.
        """
        if not isinstance(resp, dict):
            return ""
        dc = (resp.get("options") or {}).get("direct_card") or {}
        if not isinstance(dc, dict):
            return ""
        if dc.get("available") is True and str(dc.get("charge_url") or "").strip():
            return "available"
        if dc.get("allowed") is True and str(dc.get("status") or "").strip().lower() == "available":
            return "allowed"
        return ""

    def _topup_direct_card_advertised(resp: Any) -> bool:
        """True when the CRM says this intent will take a direct card charge."""
        return bool(_topup_direct_card_offer(resp))

    def _topup_direct_card_ready(resp: Any) -> bool:
        """
        True when the site should drive a direct-card charge from its own form.

        `WALLET_DIRECT_CARD_PROCESSORS` is a guard over the CRM's answer, kept
        from the days when `available: true` came back for processors whose
        `/charge` then refused the intent. It is only applied where there is a
        hosted page to fall back to. Vetoing a processor that has no hosted flow
        guarantees a dead end, whereas honouring the CRM at worst ends at the
        same failure and at best takes the payment.
        """
        offer = _topup_direct_card_offer(resp)
        if not offer:
            return False
        # The allowlist second-guesses `available`, which the CRM has returned
        # true for processors whose /charge then refused the intent. It has
        # nothing to say about the `allowed`/`status` pair, which the CRM team
        # gave us as authoritative and which no processor returned when the
        # list was written. Applying it there would only send TRAXX back to the
        # hosted page, and it would do so on any server carrying its own value
        # for the list, which is where this would go unnoticed longest.
        if offer == "allowed":
            return True
        processor = str(
            (_topup_routing(resp) or {}).get("processor") or resp.get("processor") or ""
        ).strip().lower()
        if not processor or processor in _topup_direct_card_processors():
            return True
        if not _topup_hosted_ready(resp):
            app.logger.info(
                "processor %s is not on the direct-card list but offers no hosted page; charging it anyway",
                processor,
            )
            return True
        return False

    def _topup_response_shape(resp: Any) -> str:
        """
        A short, loggable description of what a top-up response offers.

        Init responses carry no card data, but URLs can carry tokens, so only
        the keys and the flags that decide the flow are recorded.
        """
        if not isinstance(resp, dict):
            return "not an object"
        options = resp.get("options") if isinstance(resp.get("options"), dict) else {}
        direct_card = options.get("direct_card") if isinstance(options.get("direct_card"), dict) else {}
        flags = {k: v for k, v in direct_card.items() if not isinstance(v, (dict, list)) and not str(k).endswith("_url")}
        return (
            f"mode={resp.get('mode')!r} "
            f"top_level={sorted(k for k in resp if k not in ('options',))} "
            f"options={sorted(options)} "
            f"direct_card={flags} "
            f"direct_card_urls={sorted(k for k in direct_card if str(k).endswith('_url'))}"
        )

    def _topup_tried_processors() -> list[str]:
        tried = session.get("topup_tried_processors")
        return [str(p) for p in tried] if isinstance(tried, list) else []

    def _topup_mark_tried(*processors: Any) -> None:
        tried = _topup_tried_processors()
        for processor in processors:
            name = str(processor or "").strip().lower()
            if name and name not in tried:
                tried.append(name)
        session["topup_tried_processors"] = tried

    def _advance_topup_routing(token: str, routing: Any, next_url: str, *, from_intent_id: str = ""):
        """
        Move a routing session on to its next processor and send the customer
        into that processor's flow (API 58/60).

        The CRM decides whether a given failure may advance. When it may, it
        hands back a `resume_payload` to post to init, which creates the *next*
        attempt: the failed intent is never retried and the failed processor is
        never called again directly. A next processor that takes cards gets its
        own trip through the payment step rather than a silent replay of card
        details the customer gave to someone else.

        Returns a response, or None when the session cannot advance, the guard
        is spent, or the next processor leaves us nowhere to go — the caller
        then shows its own terminal failure.
        """
        if not token or not isinstance(routing, dict) or routing.get("can_advance") is not True:
            return None
        resume = routing.get("resume_payload")
        if not isinstance(resume, dict) or not resume.get("routing_session_id"):
            return None

        session_id = str(resume["routing_session_id"])
        try:
            advances = int(session.get("topup_routing_advances") or 0)
        except Exception:
            advances = 0
        if advances >= 5:
            app.logger.warning("topup routing advance guard reached for session %s", session_id)
            return None

        # "Advance" is the CRM's word, and nothing on its side stops it naming
        # the processor that has just failed: a rule listing one twice, or one
        # the CRM considers still eligible, hands the same processor back. The
        # customer is then told we switched provider and charged by the same
        # one again. So a processor already tried in this top-up is never
        # started a second time, whatever the routing says.
        failed_processor = str(routing.get("processor") or "").strip().lower()
        _topup_mark_tried(failed_processor)
        next_processor = str(routing.get("next_processor") or "").strip().lower()
        if next_processor and next_processor in _topup_tried_processors():
            app.logger.error(
                "topup routing session %s offered %s again after intent %s failed on %s; not advancing (tried: %s)",
                session_id,
                next_processor,
                from_intent_id or "unknown",
                failed_processor or "unknown",
                ",".join(_topup_tried_processors()),
            )
            return None
        session["topup_routing_advances"] = advances + 1

        base = request.url_root
        if g.brand.canonical_domain:
            base = f"https://{g.brand.canonical_domain}/"
        resume_payload = {
            "routing_session_id": session_id,
            "start_hpp": False,
            "return_urls": {
                "success": urljoin(base, url_for("wallet_topup_return", status="success", next=next_url or None)),
                "fail": urljoin(base, url_for("wallet_topup_return", status="fail", next=next_url or None)),
                "cancel": urljoin(base, url_for("wallet_topup_return", status="cancel", next=next_url or None)),
            },
        }
        try:
            resumed = get_crm().wallet_topup_init(token, resume_payload)
        except CRMError as e:
            app.logger.warning("topup routing advance failed to start session %s: %s", session_id, e)
            return None
        if not isinstance(resumed, dict):
            return None

        new_intent_id = _extract_intent_id(resumed)
        new_processor = str(
            (_topup_routing(resumed) or {}).get("processor") or resumed.get("processor") or ""
        ).strip().lower()
        if new_processor and new_processor in _topup_tried_processors():
            # Routing did not say where it was going, and it went back. The new
            # intent is left pending, which is the lesser harm: the CRM has no
            # endpoint to abandon it, and the alternative is a second charge on
            # a processor that has just refused this customer.
            app.logger.error(
                "topup routing session %s resumed onto %s again as intent %s after intent %s failed; "
                "not following it (tried: %s)",
                session_id,
                new_processor,
                new_intent_id or "unknown",
                from_intent_id or "unknown",
                ",".join(_topup_tried_processors()),
            )
            return None
        _topup_mark_tried(new_processor)
        direct_card = _topup_direct_card_ready(resumed)
        if new_intent_id:
            _pending_checkout_set(
                intent_id=new_intent_id,
                topup_processor=new_processor or None,
                direct_card_available=direct_card,
                topup_hosted_available=_topup_hosted_ready(resumed),
            )

        if new_intent_id and direct_card:
            # An unexplained second card form after a decline reads as the site
            # having lost the payment, and the pending intents left at the end
            # of a cascade are customers who stopped there. Card details cannot
            # be carried across processors, so the least we owe them is the
            # reason they are being asked again.
            flash(
                "That payment was declined by the provider. We have switched to another one — "
                "please enter your card details again to try.",
                "error",
            )
            followed = redirect(url_for("wallet_topup_pay", intent_id=new_intent_id))
        else:
            followed = _follow_topup_payment_instructions(resumed, token, next_url)
        if followed is None:
            # The intent exists and nothing can be done with it: the customer
            # gets the previous processor's failure and this one is stranded
            # pending, because the CRM has no endpoint to abandon it. The shape
            # goes in the log because which flow a processor advertises is the
            # whole reason we end up here, and it is not always documented.
            app.logger.warning(
                "topup routing advanced session %s to intent %s on %s but it offered no usable next step: %s",
                session_id,
                new_intent_id or "unknown",
                new_processor or "unknown",
                _topup_response_shape(resumed),
            )
            return None

        app.logger.info(
            "topup routing advanced session=%s from intent=%s to intent=%s processor=%s",
            session_id,
            from_intent_id or "unknown",
            new_intent_id or "unknown",
            new_processor or "unknown",
        )
        return followed

    def _routing_country() -> str:
        """
        The country Website Processor Rules will match on: the one persisted on
        the CRM customer record (API 58). Falls back to the geo country so a
        first top-up can still route before billing has been collected.
        """
        customer = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        for candidate in (
            customer.get("country"),
            ((customer.get("address") or {}).get("country_iso2") if isinstance(customer.get("address"), dict) else None),
            ((customer.get("address") or {}).get("country") if isinstance(customer.get("address"), dict) else None),
            getattr(g, "geo_country", None),
        ):
            iso = str(candidate or "").strip().upper()
            if re.fullmatch(r"[A-Z]{2}", iso):
                return iso
        return ""

    def _billing_address_on_file() -> bool:
        """
        True when the CRM already holds an address a processor could be given.

        Our card form is the only place the site asks for one, and a hosted-only
        processor never shows it, so a customer without an address reaches the
        gateway with nothing to send. CCM refuses that outright — live intent
        3282 came back "Ship address can not be empty" — and no amount of
        retrying fixes it, because nothing in the journey collects an address.
        """
        customer = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        address = customer.get("address") if isinstance(customer.get("address"), dict) else {}
        mailing = customer.get("mailing_address") if isinstance(customer.get("mailing_address"), dict) else {}
        street = str(customer.get("street") or address.get("line1") or mailing.get("street") or "").strip()
        city = str(customer.get("city") or address.get("city") or mailing.get("city") or "").strip()
        postcode = str(
            customer.get("postal_code")
            or customer.get("postcode")
            or address.get("postal_code")
            or mailing.get("postal_code")
            or ""
        ).strip()
        return bool(street and city and postcode)

    def _topup_address_payload(form: Any, country: str) -> dict[str, Any]:
        """
        An address in the shape the CRM documents for top-up initiation, or {}
        when the form did not carry a whole one.

        API 62 accepts these fields on `topup/init` and persists them *before*
        it routes, which makes this the last point where an address can still
        reach the processor that is about to ask for one. The shape mirrors what
        the card form already sends to `PATCH /customers/me`, so both paths
        leave the same record behind.
        """
        street = str(form.get("billing_street") or "").strip()
        city = str(form.get("billing_city") or "").strip()
        state = str(form.get("billing_state") or "").strip()
        postcode = str(form.get("billing_postcode") or "").strip()
        if not (street and city and postcode):
            return {}
        address: dict[str, Any] = {
            "street": street,
            "city": city,
            "postal_code": postcode,
        }
        if state:
            address["state"] = state
        if country:
            address["country"] = country
        return {**address, "mailing_address": dict(address)}

    def _sync_profile_from_topup_payload(token: str, payload: Any) -> None:
        """
        Best-effort: after a hosted-page payment, lift any billing address the
        processor/CRM echoed back in the status payload into the customer
        profile, so the customer doesn't have to type it again elsewhere.
        Card numbers never reach the website from a hosted page (PCI), so only
        address data can be captured here.
        """
        if not isinstance(payload, dict):
            return
        sources: list[Any] = [
            payload.get("billing"),
            payload.get("billing_address"),
            (payload.get("intent") or {}).get("billing") if isinstance(payload.get("intent"), dict) else None,
            (payload.get("card") or {}).get("billing") if isinstance(payload.get("card"), dict) else None,
            (payload.get("customer") or {}).get("address") if isinstance(payload.get("customer"), dict) else None,
        ]
        billing = next((s for s in sources if isinstance(s, dict) and s), None)
        if not billing:
            return
        street = str(billing.get("street") or billing.get("line1") or billing.get("streetAddress") or "").strip()
        city = str(billing.get("city") or "").strip()
        postal = str(billing.get("postal_code") or billing.get("postcode") or billing.get("zip") or "").strip()
        country = str(billing.get("country") or "").strip().upper()
        state = str(billing.get("state") or billing.get("province") or "").strip()
        if not (street or city or postal):
            return
        customer = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        # Fill gaps only; never overwrite an address the customer set themselves.
        update: dict[str, Any] = {}
        if street and not str(customer.get("street") or "").strip():
            update["street"] = street
        if city and not str(customer.get("city") or "").strip():
            update["city"] = city
        if postal and not str(customer.get("postal_code") or "").strip():
            update["postal_code"] = postal
        if country and not str(customer.get("country") or "").strip():
            update["country"] = country
        if state and not str(customer.get("state") or "").strip():
            update["state"] = state
        if not update:
            return
        try:
            get_crm().customer_update(token, update)
            me = get_crm().customer_me(token).get("customer")
            if isinstance(me, dict):
                session["customer"] = me
            app.logger.info("topup billing capture: synced %s to customer profile", sorted(update.keys()))
        except CRMError:
            pass

    def _friendly_crm_error(e: Exception, *, context: str | None = None) -> str:
        """
        Customer-friendly error messaging for CRM outages / upstream HTML error pages.
        - Strips HTML tags/entities
        - Maps transient upstream issues to a retry message
        """
        if isinstance(e, CRMError):
            sc = e.status_code
            # A support session refused a write. Retrying cannot help and the
            # CRM's own wording is the clearest thing to show, so it is used
            # verbatim rather than dressed up as a temporary fault.
            if isinstance(e.payload, dict) and str(e.payload.get("error_code") or "") == "SUPPORT_SESSION_READ_ONLY":
                return SUPPORT_READ_ONLY_MESSAGE
            # Website Processor Rules found no processor for this customer's
            # saved country (API 58). The customer cannot fix this by retrying.
            if isinstance(e.payload, dict) and str(e.payload.get("error_code") or "") == "PAYMENT_ROUTES_EXHAUSTED":
                return (
                    "Payments are not available for your country at the moment. "
                    "Please contact support so we can help you top up."
                )
            if sc in {502, 503, 504}:
                return "Sorry — our service is temporarily unavailable. Please try again in a minute."
            if sc == 429:
                return "Too many attempts. Please wait a moment and try again."
            if sc == 401 and (context or "") == "login":
                # Common auth failure UX.
                return "Incorrect email or password."
            if sc == 500:
                # Never surface the CRM's raw "Internal Server Error" to customers.
                return "Sorry — something went wrong on our side. Please try again in a moment."

        raw = str(e or "").strip()
        raw = re.sub(r"^CRM HTTP \d+:\s*", "", raw).strip()
        raw = html.unescape(raw)
        # Remove HTML tags if the CRM returned a gateway/proxy error page.
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        lowered = raw.lower()
        if "testing processor is disabled" in lowered:
            return (
                "Testing processor is disabled in CRM for this brand/API key. "
                "In CRM Admin, enable Testing for this brand and enable API flow(s) "
                "(HPP and/or direct card)."
            )
        if "return_urls" in lowered and "allow" in lowered and "host" in lowered:
            return (
                "Top-up return URL host is not allowlisted in CRM. "
                "Add this website host under Testing payment settings (allowed return hosts)."
            )
        if not raw:
            return "Something went wrong. Please try again."
        # Avoid dumping long backend payloads into the UI.
        if len(raw) > 180:
            raw = raw[:180].rstrip() + "…"
        return raw

    def _crm_error_raw(e: Exception) -> str:
        """
        What the CRM actually said, lowercased, for code that must match on it.

        `_friendly_crm_error` is for customers, and it throws the CRM's wording
        away on a 500, 429 and every gateway status. Deciding what to *do*
        about a failure by reading that text means the decision quietly depends
        on which status code the CRM chose - and this CRM already answers 500
        to things that should be a 422, which is how a duplicate phone number
        at registration presents. A recovery path that works on 422 and not on
        500 is one nobody will find by reading the code.
        """
        parts = [re.sub(r"^CRM HTTP \d+:\s*", "", str(e or "")).strip()]
        payload = getattr(e, "payload", None)
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        return " ".join(parts).lower()

    def _normalized_currency_code(raw: Any) -> str:
        code = str(raw or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", code):
            return code
        return ""

    def _default_display_currency() -> str:
        # Prefer env-configured fallback in exceptional cases where CRM omits currency.
        return _normalized_currency_code(os.environ.get("CRM_PRICE_FALLBACK_CURRENCY")) or "EUR"

    def _currency_symbol(code: Any) -> str:
        c = _normalized_currency_code(code)
        return {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "AUD": "A$",
            "CAD": "C$",
            "NZD": "NZ$",
            "JPY": "¥",
            "ZAR": "R",
        }.get(c, c)

    def _resolve_display_currency(
        *,
        quote: dict[str, Any] | None = None,
        wallet: dict[str, Any] | None = None,
        customer: dict[str, Any] | None = None,
        prefer_quote: bool = False,
    ) -> str:
        candidates: list[Any] = []
        if prefer_quote and isinstance(quote, dict):
            candidates.append(quote.get("currency"))
        if isinstance(wallet, dict):
            candidates.append(wallet.get("currency"))
        if isinstance(customer, dict):
            # Handle variants seen across CRM payloads.
            candidates.extend(
                [
                    customer.get("currency"),
                    customer.get("customer_currency"),
                    customer.get("wallet_currency"),
                ]
            )
        if not prefer_quote and isinstance(quote, dict):
            candidates.append(quote.get("currency"))
        for raw in candidates:
            c = _normalized_currency_code(raw)
            if c:
                return c
        return _default_display_currency()

    def _get_cached_product_price_lookup() -> dict[str, int]:
        """
        Compatibility helper: some cache builds expose product price lookups, others do not.
        Always return a dict so pricing fallbacks stay non-fatal.
        """
        try:
            cache_obj = get_cache()
            getter = getattr(cache_obj, "get_product_price_lookup", None)
            if callable(getter):
                out = getter()
                if isinstance(out, dict):
                    return out
        except Exception:
            pass
        return {}

    def _product_price_cents(product: dict[str, Any] | None, currency: str) -> int | None:
        """
        Customer-facing unit price for a product in `currency`, from the CRM's
        saved `prices_by_currency` map (API: "Frontends can use this map to
        choose which currency to display without recomputing prices").

        `price_in_base_cents` is an amount in a *different* currency, so showing
        it to a customer on another currency misquotes the price. Returns None
        when the CRM has no saved price for that currency, leaving the fallback
        decision (and its warning) to the caller.
        """
        if not isinstance(product, dict):
            return None
        want = str(currency or "").strip().upper()
        prices = product.get("prices_by_currency")
        if not want or not isinstance(prices, dict):
            return None
        entry = prices.get(want)
        if not isinstance(entry, dict) or entry.get("amount_cents") is None:
            return None
        try:
            cents = int(float(entry["amount_cents"]))
        except Exception:
            return None
        return cents if cents > 0 else None

    def _catalog_product(product_code: str) -> dict[str, Any] | None:
        """The cached catalogue entry for a SKU, or None when it isn't cached."""
        code = str(product_code or "").strip().upper()
        if not code:
            return None
        try:
            for game in store_games_cached():
                if not isinstance(game, dict):
                    continue
                for key in ("products", "default_products", "skus", "single_products", "syndicate_products"):
                    for p in game.get(key) or []:
                        if not isinstance(p, dict):
                            continue
                        if str(p.get("code") or p.get("product_code") or "").strip().upper() == code:
                            return p
        except Exception:
            return None
        return None

    def _catalog_game(game_code: str) -> dict[str, Any] | None:
        """The cached game for a code, or None when the store doesn't sell it."""
        code = str(game_code or "").strip().lower()
        if not code:
            return None
        try:
            for game in store_games_cached():
                if isinstance(game, dict) and str(game.get("game_code") or "").strip().lower() == code:
                    return game
        except Exception:
            return None
        return None

    def _game_for_product_code(product_code: str) -> dict[str, Any] | None:
        """The cached game that sells a SKU, for naming it and for cart metadata."""
        code = str(product_code or "").strip().upper()
        if not code:
            return None
        try:
            for game in store_games_cached():
                if not isinstance(game, dict):
                    continue
                for key in ("products", "default_products", "skus", "single_products", "syndicate_products"):
                    for p in game.get(key) or []:
                        if not isinstance(p, dict):
                            continue
                        if str(p.get("code") or p.get("product_code") or "").strip().upper() == code:
                            return game
        except Exception:
            return None
        return None

    def _cart_line_schemas(cart_items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """
        Number-board layout per SKU in the cart.

        The cart edits a line with the same grids the play page draws, and those
        are built from the product's `line_schema`, so the page needs the schema
        for every SKU it is showing. A SKU whose schema isn't cached simply has
        no editor rather than a broken one.
        """
        codes: list[str] = []
        for item in cart_items or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("product_code") or "").strip().upper()
            if code and code not in codes:
                codes.append(code)

        raw_by_code: dict[str, Any] = {}
        for code in codes:
            product = _catalog_product(code)
            if product:
                raw_by_code[code] = product.get("line_schema")
        # The games cache can be cold or a SKU can be missing from it; the flat
        # catalogue is the other place the schema lives, and one call covers
        # every SKU still unaccounted for.
        if any(code not in raw_by_code for code in codes):
            try:
                for product in (get_crm().store_products() or {}).get("products") or []:
                    if not isinstance(product, dict):
                        continue
                    pc = str(product.get("code") or product.get("product_code") or "").strip().upper()
                    if pc in codes and pc not in raw_by_code:
                        raw_by_code[pc] = product.get("line_schema")
            except Exception:
                pass

        out: dict[str, list[dict[str, Any]]] = {}
        for code in codes:
            raw = raw_by_code.get(code)
            # Schemas arrive as a list of groups, as {"groups": [...]}, or as a
            # map of name -> spec; a cart that only understood one of those
            # silently had no editor.
            groups: list[Any] = []
            if isinstance(raw, list):
                groups = raw
            elif isinstance(raw, dict):
                if isinstance(raw.get("groups"), list):
                    groups = raw["groups"]
                else:
                    groups = [{"name": k, **v} for k, v in raw.items() if isinstance(v, dict)]
            clean: list[dict[str, Any]] = []
            for g in groups:
                if not isinstance(g, dict):
                    continue
                name = str(g.get("name") or "").strip()
                if not name:
                    continue
                try:
                    clean.append(
                        {
                            "name": name,
                            "min": int(g.get("min") or 1),
                            "max": int(g.get("max") or 1),
                            "count": int(g.get("count") or 1),
                        }
                    )
                except Exception:
                    continue
            if clean:
                out[code] = clean
        return out

    def _line_count_error(product_code: str, game_code: str, line_count: int) -> str | None:
        """
        The CRM rejects invalid line counts with a 400 (INVALID_LINES_COUNT), so
        check the product's own rules here and say what's wrong in the picker.
        Caps and minimums come from the product payload; only the Lotto (IE)
        two-line minimum is fixed by the API contract itself.
        """

        def _pint(value: Any) -> int:
            try:
                return int(float(value))
            except Exception:
                return 0

        product = _catalog_product(product_code) or {}
        max_lines = _pint(product.get("website_max_lines_per_item")) or 50
        if line_count > max_lines:
            return f"A maximum of {max_lines} lines per ticket is allowed. Please reduce your lines."

        bundle_min = _pint(product.get("bundle_min_lines"))
        if (
            str(product.get("pricing_kind") or "").strip().lower() == "bundle"
            and product.get("partial_bundle_sales_enabled") is not True
            and bundle_min > 1
        ):
            if line_count % bundle_min != 0:
                return (
                    f"This game is sold in blocks of {bundle_min} lines. "
                    f"Please choose {bundle_min}, {bundle_min * 2}, {bundle_min * 3}… lines."
                )
            return None

        min_lines = _pint(product.get("sale_unit_lines"))
        if str(game_code or "").strip().lower() == "lotto-ie":
            min_lines = max(min_lines, 2)
        if min_lines > 1 and line_count < min_lines:
            return f"This game requires a minimum of {min_lines} lines per ticket."
        return None

    @app.post("/resources/php_functions/<path:filename>")
    def legacy_php_functions(filename: str):
        """
        Compatibility shim for legacy JS (e.g. /resources/js/account.js) that POSTs to
        /resources/php_functions/*.php on the old site.

        The legacy PHP site handled these via server-side sessions + API calls.
        In this Flask site we return best-effort responses so the UI behaves and
        doesn't 404/405.
        """
        fn = os.path.basename(str(filename or "").strip())
        # Default: not implemented (but return a string the legacy JS expects).
        # NOTE: legacy JS shows non-"failed" values as user-visible error text.
        not_impl = "Not available yet on this site."

        def _crm_token() -> str | None:
            tok = session.get("crm_token")
            if not tok:
                return None
            return str(tok)

        def _boolish(v: str | None) -> bool:
            return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}

        def _clean_phone(v: str | None) -> str | None:
            if v is None:
                return None
            p = str(v).strip().replace(" ", "").replace("-", "")
            if p.startswith("0"):
                p = p.lstrip("0")
            return p or None

        def _crm_err_msg(e: Exception) -> str:
            msg = str(e)
            msg = re.sub(r"^CRM HTTP \d+:\s*", "", msg).strip()
            return msg or "failed"

        # Search/load actions: returning "success" is enough for legacy JS to re-render sections.
        if fn in {
            "account-transaction-history.php",
            "account-order-history.php",
            "account-winnings.php",
            "account-transaction-summary.php",
        }:
            session["legacy_last_php_function"] = fn

            # Persist best-effort filters/paging so GET /account can re-render accordingly.
            if fn == "account-transaction-history.php":
                if _boolish(request.form.get("loadMoreTransactions")):
                    session["acct_txn_show"] = int(session.get("acct_txn_show") or 5) + 5
                elif _boolish(request.form.get("transactionFormSubmitted")):
                    session["acct_txn_show"] = 5
                    session["acct_txn_filters"] = {
                        "date_range": (request.form.get("accountTransactionDateRange") or "").strip(),
                        "type": (request.form.get("transactionHistoryType") or "").strip(),
                        "status": (request.form.get("transactionHistoryStatus") or "").strip(),
                    }
                return "success"

            if fn == "account-order-history.php":
                if _boolish(request.form.get("loadMoreOrderHistory")):
                    session["acct_order_show"] = int(session.get("acct_order_show") or 5) + 5
                elif _boolish(request.form.get("orderFormSubmitted")):
                    session["acct_order_show"] = 5
                    session["acct_order_filters"] = {
                        "date_range": (request.form.get("orderHistoryDateSearch") or "").strip(),
                        "order_id": (request.form.get("orderId") or "").strip(),
                        "status": (request.form.get("orderStatus") or "").strip(),
                        "settled": (request.form.get("orderSettled") or "").strip(),
                        "type": (request.form.get("orderType") or "").strip(),
                    }
                return "success"

            if fn == "account-winnings.php":
                if _boolish(request.form.get("loadMoreWinnings")):
                    session["acct_winnings_show"] = int(session.get("acct_winnings_show") or 5) + 5
                elif _boolish(request.form.get("accountWinningsFormSubmitted")):
                    session["acct_winnings_show"] = 5
                    session["acct_winnings_filters"] = {
                        "date_range": (request.form.get("accountWinningsDateRange") or "").strip(),
                    }
                return "success"

            return "success"

        # Mutations are not wired to CRM yet in this Flask site.
        if fn in {
            "update-account-details.php",
            "account-notifications.php",
            "change-password.php",
            "account-security-question.php",
            "account-set-limits.php",
            "account-cancel-pending-limits.php",
            "account-suspension.php",
            "account-withdrawal.php",
            "account-payment-methods.php",
        }:
            token = _crm_token()
            if not token:
                return "failed"

            if fn == "update-account-details.php":
                email = (request.form.get("acctDetailsEmail") or "").strip() or None
                phone = _clean_phone(request.form.get("acctDetailsPhone"))
                street = (request.form.get("acctDetailsAddress") or "").strip() or None
                postal_code = (request.form.get("acctDetailsPostCode") or "").strip() or None
                city = (request.form.get("acctDetailsCity") or "").strip() or None
                state = (request.form.get("acctDetailsState") or "").strip() or None

                payload: dict[str, Any] = {}
                if email is not None:
                    payload["email"] = email
                if phone is not None:
                    payload["phone"] = phone
                addr = {k: v for k, v in {"street": street, "city": city, "postal_code": postal_code, "state": state}.items() if v}
                if addr:
                    payload["mailing_address"] = addr

                try:
                    if payload:
                        get_crm().customer_update(token, payload)
                    me = get_crm().customer_me(token).get("customer")
                    if isinstance(me, dict):
                        session["customer"] = me
                    return "success"
                except CRMError as e:
                    return _crm_err_msg(e)
                except Exception as e:
                    return _crm_err_msg(e)

            if fn == "account-notifications.php":
                sms_marketing = _boolish(request.form.get("smsNotifiction"))
                acct_notifications = (request.form.get("acctNotifications") or "").strip()
                email_marketing = acct_notifications == "allNotifications"

                session["acct_notification_prefs"] = {
                    "email_marketing": bool(email_marketing),
                    "sms_marketing": bool(sms_marketing),
                }

                payload: dict[str, Any] = {
                    "notification": {
                        "is_allow_email": True,
                        "is_allow_marketing_email": bool(email_marketing),
                        "is_allow_sms": True,
                        "is_allow_marketing_sms": bool(sms_marketing),
                        "is_allow_phone_call": False,
                    }
                }
                try:
                    get_crm().customer_update(token, payload)
                    me = get_crm().customer_me(token).get("customer")
                    if isinstance(me, dict):
                        session["customer"] = me
                    return "success"
                except CRMError:
                    # Best-effort: keep UI responsive even if CRM doesn't support this schema.
                    return "success"

            if fn == "change-password.php":
                return "Please use 'Forgot your password?' to reset your password."

            return not_impl

        return not_impl

    def _parse_iso2_list(raw: str | None) -> set[str]:
        if not raw:
            return set()
        # `[,\\s]` in a raw string is a class of comma, backslash and the letter
        # s — not whitespace. "MT GB" arrived as one token and matched nothing.
        parts = re.split(r"[,\s]+", str(raw))
        return {p.strip().upper() for p in parts if p and p.strip()}

    def _client_ip() -> str | None:
        # Prefer proxy headers, then fall back to remote_addr.
        xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            # First entry is original client.
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
        xri = (request.headers.get("X-Real-IP") or "").strip()
        if xri:
            return xri
        ra = (request.remote_addr or "").strip()
        return ra or None

    def _geo_country_iso2() -> str | None:
        # Best-effort: rely on proxy/CDN geo headers when present.
        #
        # Only the header our own edge sets can be trusted: the rest are just as
        # settable by the caller, and taking the first match off a fixed list let
        # anyone defeat a country block by sending `CF-IPCountry`. The trusted
        # one wins outright when present; the others stay as a fallback for
        # deployments behind a different CDN.
        trusted = (os.environ.get("GEO_COUNTRY_HEADER") or "X-Geo-Country").strip()
        fallbacks = (
            "CF-IPCountry",
            "CloudFront-Viewer-Country",
            "X-Geo-Country",
            "X-Country",
            "X-Country-Code",
            "X-AppEngine-Country",
        )
        for k in (trusted, *(h for h in fallbacks if h.lower() != trusted.lower())):
            if not k:
                continue
            v = (request.headers.get(k) or "").strip().upper()
            if v and re.fullmatch(r"[A-Z]{2}", v):
                return v
        return None

    def _env_blocked_countries() -> set[str]:
        """
        Countries the site blocks on its own authority, ISO2, from
        `WEBSITE_BLOCKED_COUNTRIES_ISO2`.

        This exists so a country can be cut off with an env change and a restart
        — no CRM edit, no deploy, no waiting on the countries sync.
        """
        return _parse_iso2_list(os.environ.get("WEBSITE_BLOCKED_COUNTRIES_ISO2"))

    # The CRM returns this wording on a 403; the site says the same thing when
    # it stops the submit itself, so a customer sees one message either way.
    REGISTRATION_SOFT_BLOCK_MESSAGE = "Registration is not available in your country."

    def _country_restriction(iso2: str | None) -> str:
        """
        The website mode for a country: `active`, `soft_block`, `block_website`
        or `unknown`.

        The env list is consulted first and on its own authority, so a country
        can still be cut off with a restart while the CRM catches up.
        """
        code = (iso2 or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", code or ""):
            return "unknown"
        if code in _env_blocked_countries():
            return "block_website"
        try:
            return get_cache().country_restriction(code)
        except Exception:
            return "unknown"

    def _is_static_request() -> bool:
        p = request.path or ""
        return (
            p.startswith("/resources/")
            or p.startswith("/static/")
            or p.startswith("/favicon")
            or p.startswith("/Favicon.ico")
            or p == "/health"
        )

    def _countries_refresh_seconds() -> int:
        try:
            return max(30, int(os.environ.get("COUNTRY_BLOCKS_REFRESH_SECONDS") or 300))
        except Exception:
            return 300

    # Latches per cache file once a list has arrived. A table that has rows never
    # loses them, so after the first load this stops counting on every request.
    _countries_seeded: set[str] = set()

    def _countries_table_is_empty(cache: CRMCache) -> bool:
        key = cache.cfg.db_path
        if key in _countries_seeded:
            return False
        try:
            seeded = int((cache.counts() or {}).get("countries") or 0) > 0
        except Exception:
            # Unreadable is not the same as empty; treat it as seeded so a broken
            # cache cannot put a CRM fetch in front of every request.
            return False
        if seeded:
            _countries_seeded.add(key)
        return not seeded

    def _refresh_country_blocks_if_stale() -> None:
        """
        Keep the CRM's country list current on the site's own initiative.

        Blocking a country is a compliance control, so it cannot ride on
        `CRM_SYNC_ENABLE`. That switch is off unless someone sets it, and with it
        off the site never fetched the table at all: a country blocked in CRM
        Admin looked applied and stopped nobody. There is no switch here — the
        CRM's answer is the site's answer.

        An empty table is fetched in the request. Answering "not blocked" from a
        list we have never loaded is the one case worth making a visitor wait
        for; once there is something to serve, refreshes happen behind them.
        """
        cache = get_cache()
        cold = _countries_table_is_empty(cache)

        # With no list at all the site is waving everyone through, so it retries
        # far sooner than the steady-state interval rather than staying open for
        # the full five minutes. Still throttled: a CRM that is refusing must not
        # be asked again on every request.
        interval = 30 if cold else _countries_refresh_seconds()
        try:
            attempted = cache.get_state("last_countries_attempt_at")
        except Exception:
            return
        if not should_sync(attempted, interval):
            return
        if not cache.try_acquire_lock("countries", ttl_seconds=300):
            return

        # Stamped before the call, not after, so a CRM outage backs off to the
        # same interval instead of retrying on every single request.
        try:
            cache.set_state("last_countries_attempt_at", _now_iso_utc())
        except Exception:
            pass

        # Built here rather than taken from `get_crm()`: that one is request
        # scoped, and off the request there is no `g` to take it from.
        client = CRMClient(load_crm_config_from_env())

        def _run(timeout_seconds: int | None) -> None:
            try:
                sync_countries_once(client, cache, timeout_seconds=timeout_seconds)
            except Exception as exc:
                app.logger.warning("country block list refresh failed: %s", exc)
            finally:
                try:
                    cache.release_lock("countries")
                except Exception:
                    pass

        if cold:
            _run(_layout_timeout_seconds())
            return
        threading.Thread(target=_run, args=(None,), name="country_blocks_refresh", daemon=True).start()

    @app.before_request
    def _enforce_country_blocks():
        if _is_static_request():
            return None

        # The admin console is exempt. It is password-protected, and it carries
        # the controls for the block list itself — locking it behind the block
        # would mean a mistake in the list could only be undone on the server.
        if (request.path or "").startswith("/admin"):
            return None

        _refresh_country_blocks_if_stale()

        # Derive best-effort geo context for this request.
        g.client_ip = _client_ip()
        g.geo_country = _geo_country_iso2()

        # If we don't know the country, do not block (best-effort).
        if not g.geo_country:
            return None

        country = str(g.geo_country).upper()
        # Held for the rest of the request: registration needs to know a soft
        # block is in force even though the visitor is free to browse.
        g.geo_restriction = _country_restriction(country)

        # Only a full website block stops entry. A soft block is a registration
        # rule, and turning it into a door policy would lock out the existing
        # customers it is explicitly meant to keep serving.
        if g.geo_restriction == "block_website":
            return _blocked_country_response(country)
        return None

    def _blocked_country_response(country: str | None) -> Response:
        # IMPORTANT: Do not render templates here; blocked pages must be fast and
        # must not trigger template context processors that call CRM.
        c = (country or "").strip().upper()
        extra = f"<p style='opacity:.85'>Detected country: <code>{c}</code></p>" if c else ""
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Service Unavailable | LottosOnline</title>
  <link rel="stylesheet" href="/resources/css/style.css?v=2" />
</head>
<body>
  <div class="container">
    <div class="row lePages">
      <div class="col-xs-12 col-sm-12 col-md-12">
        <h1 class="pageHeading">Service Unavailable</h1>
        <p class="sub-heading">Sorry, we are not able to provide services in your country.</p>
        {extra}
        <p style="margin-top:18px;">If you believe this is a mistake, please contact support.</p>
        <a class="linkAsButton" href="/contact-us">Contact Us</a>
      </div>
    </div>
  </div>
</body>
</html>
"""
        return Response(html, status=403, mimetype="text/html")

    @app.get("/Favicon.ico")
    def legacy_favicon():
        return send_from_directory(app.config["LEGACY_RESOURCES_DIR"], "Favicon.ico")

    @app.before_request
    def _load_context() -> None:
        g.brand = app.config["BRAND_CONFIG"]
        if request.path.startswith("/support/login-as"):
            # A staff handoff is not a visit. Recording it as one would file the
            # support tool as the campaign that brought the customer in, and
            # this URL carries a credential that has no business being kept
            # anywhere - not in attribution, not in a session, not in a log.
            return
        # Capture marketing attribution on entry and persist it server-side so it survives navigation.
        # Canonical params (per Marketing Module guide): src, cmp, tid, intent
        src = (request.args.get("src") or "").strip() or None
        cmp = (request.args.get("cmp") or "").strip() or None
        tid = (request.args.get("tid") or "").strip() or None
        intent = (request.args.get("intent") or "").strip() or None

        mkt = session.get("mkt", {}) if isinstance(session.get("mkt", {}), dict) else {}
        if tid:
            mkt["tid"] = tid
        if cmp:
            mkt["cmp"] = cmp
        if intent in {"acquisition", "lifecycle"}:
            mkt["intent"] = intent
        # Avoid overwriting acquisition source with lifecycle touches.
        if src and (mkt.get("intent") != "lifecycle"):
            mkt["src"] = src
        session["mkt"] = mkt

        # The set-password token travels with the campaign link but is a
        # credential, not attribution. It is held apart from `mkt` so it cannot
        # be swept into a marketing event, and it is never logged.
        spt = (request.args.get("spt") or "").strip()
        if spt and re.fullmatch(r"[A-Za-z0-9._\-]{16,512}", spt):
            session["set_password_token"] = spt

        # A reactivation link carries a token for a former customer who has no
        # account at all, where `spt` is for one who has an account and no
        # password. The two are mutually exclusive and this is held apart from
        # `mkt` for the same reason: it is a lookup key for someone's name and
        # date of birth, not attribution, and it is never logged.
        #
        # The pattern is deliberately loose. The token is opaque and the Module
        # may change how it mints them; the bound is here to keep something
        # absurd out of the session, not to second-guess its format.
        rt = (request.args.get("rt") or "").strip()
        if rt and re.fullmatch(r"[A-Za-z0-9._~=\-]{8,1024}", rt):
            session["reactivation_token"] = rt

        # An invite to a former mail-order customer from the AS400. Where `rt`
        # maps to details the Marketing Module holds, this maps to a record the
        # CRM holds, including an email address it has already verified.
        #
        # Captured here rather than in the register view for the same reason as
        # the other two: someone can open the link, read about the games for ten
        # minutes, and still have their invite when they reach the form. It is
        # a lookup key for a name and a date of birth, so it stays out of `mkt`
        # and out of the log.
        lst = (request.args.get("lst") or "").strip()
        if lst and re.fullmatch(r"[A-Za-z0-9._~=\-]{8,1024}", lst):
            session["legacy_signup_token"] = lst

    @app.context_processor
    def _inject_brand() -> dict:
        brand: BrandConfig = app.config["BRAND_CONFIG"]
        # Treat a user as logged in only if a CRM token exists. This avoids a confusing
        # UI state where `customer` remains in session but the signed cookie/token is gone.
        customer = session.get("customer") if session.get("crm_token") else None

        # Template-facing capability/feature map.
        # This lets templates hide unsupported sections while keeping required ones visible.
        api_capabilities = {
            "email_verification": True,
            "winnings_tickets": True,
            "orders": True,
            "wallet_transactions": True,
            "draw_results": True,
            "refund_request_api": False,
            "withdrawal_request_api": False,
        }
        features = {
            "account_password_change": False,
            "account_security_questions": False,
            "account_limits": False,
            "account_self_exclusion": False,
            "account_withdrawal": True,
            "account_refund": True,
            "email_verification_banner": True,
            "orders_scan_refresh": True,
            "reports_winnings_tickets": True,
        }

        # Top-bar helpers (legacy style): name, cached wallet balance, and session time.
        cust_full_name = ""
        if isinstance(customer, dict):
            first = (customer.get("first_name") or customer.get("firstName") or "").strip()
            last = (customer.get("last_name") or customer.get("lastName") or "").strip()
            cust_full_name = (first + " " + last).strip()
            if not cust_full_name:
                cust_full_name = (customer.get("email") or "").strip()

        header_balance_currency = ""
        header_balance_amount = "0.00"
        header_balance_added = ""
        header_balance_wins = ""
        header_balance_split = False
        w = session.get("wallet") if isinstance(session.get("wallet"), dict) else None
        if isinstance(w, dict):
            header_balance_currency = (w.get("currency") or "").strip()
            funding = _wallet_funding(w)
            # The total stays the headline figure - it is their money and they
            # know what it should be - but it never appears on its own, because
            # checkout will not spend the winnings half of it without being
            # asked. The split is what stops the header contradicting the cart.
            header_balance_amount = f"{(funding['total_cents'] or 0) / 100:.2f}"
            header_balance_added = f"{(funding['spendable_cents'] or 0) / 100:.2f}"
            header_balance_wins = f"{(funding['available_wins_cents'] or 0) / 100:.2f}"
            header_balance_split = funding["available_wins_cents"] > 0
            # Legacy UI shows a space before the amount.
            header_balance_amount = f" {header_balance_amount}"

        time_on_site_seconds = None
        if session.get("crm_token"):
            started = session.get("time_on_site_started_at")
            try:
                if started is None:
                    session["time_on_site_started_at"] = int(time.time())
                    started = session["time_on_site_started_at"]
                time_on_site_seconds = max(0, int(time.time()) - int(started))
            except Exception:
                time_on_site_seconds = None
        
        # Calculate cart item count
        header_cart_count = 0
        cart_items = session.get("cart_items")
        if isinstance(cart_items, list):
            for item in cart_items:
                if isinstance(item, dict):
                    if item.get("kind") == "single":
                        lines = item.get("lines")
                        if isinstance(lines, list):
                            header_cart_count += len(lines)
                        else:
                            header_cart_count += 1
                    else:
                        header_cart_count += 1
        
        return {
            "brand": brand,
            "gtm_id": os.environ.get("ANALYTICS_GTM_ID") or brand.gtm_id,
            "ga4_id": os.environ.get("ANALYTICS_GA4_ID") or brand.ga4_id,
            "customer": customer,
            "layout": layout_model(),
            "build_id": app.config.get("BUILD_ID"),
            "customer_full_name": cust_full_name,
            # Every page, for as long as the session lasts. Staff need to know
            # whose account they are looking at and that nothing they do here
            # will land, and one page telling them once is not enough.
            "support_read_only": _support_session_active(),
            "support_banner_message": SUPPORT_BANNER_MESSAGE,
            "header_balance_currency": header_balance_currency,
            "header_balance_amount": header_balance_amount,
            "header_balance_added": header_balance_added,
            "header_balance_wins": header_balance_wins,
            "header_balance_split": header_balance_split,
            "header_cart_count": header_cart_count,
            "time_on_site_seconds": time_on_site_seconds,
            "api_capabilities": api_capabilities,
            "features": features,
        }

    def get_crm() -> CRMClient:
        if "crm" not in g:
            g.crm = CRMClient(load_crm_config_from_env())
        return g.crm

    def get_mkt() -> MktClient | None:
        """
        The Marketing Module's service API, or None where it is not configured.

        Only reactivation prefill talks to the Module directly - everything
        else marketing-related goes through the CRM - so the site has to run
        perfectly well without it, including on a machine that has never heard
        of it.
        """
        if "mkt_client" not in g:
            cfg = load_mkt_config_from_env()
            g.mkt_client = MktClient(cfg) if cfg else None
        return g.mkt_client

    def get_cache() -> CRMCache:
        return app.config["CRM_CACHE"]

    def _crm_cache_only_mode() -> bool:
        return os.environ.get("CRM_CACHE_ONLY", "0").strip() in {"1", "true", "True", "yes", "YES"}

    def _cache_ttl_seconds() -> int:
        try:
            return int(os.environ.get("CRM_LAYOUT_CACHE_TTL_SECONDS", "300"))
        except Exception:
            return 300

    def _marketing_banners_ttl_seconds() -> int:
        """
        Banners change when a campaign starts or ends rather than continuously,
        so this sits well above the layout TTL. It only needs to be short enough
        that a campaign going live is not held back by the cache.
        """
        try:
            return int(os.environ.get("CRM_MARKETING_BANNERS_TTL_SECONDS", "900"))
        except Exception:
            return 900

    def _store_games_ttl_seconds() -> int:
        """
        Store catalog must update quickly so newly added CRM products appear without deploys.
        """
        try:
            return int(os.environ.get("CRM_STORE_GAMES_TTL_SECONDS", "60"))
        except Exception:
            return 60

    def _layout_timeout_seconds() -> int:
        # Keep page loads fast even if CRM is slow; we fall back to SQLite cache.
        try:
            return int(os.environ.get("CRM_LAYOUT_TIMEOUT_SECONDS", "2"))
        except Exception:
            return 2

    def _first_jackpots_timeout_seconds() -> int:
        # When cache is empty, allow a longer first fetch so jackpots can appear at least once.
        try:
            return int(os.environ.get("CRM_FIRST_JACKPOTS_TIMEOUT_SECONDS", "15"))
        except Exception:
            return 15

    def get_token() -> str | None:
        # A token belongs to a visitor, so off a request there is not one to
        # find. Background work shares these helpers and must not fail on the
        # session lookup before it reaches the part that does not need one.
        if not has_request_context():
            return None
        return session.get("crm_token")

    def require_login() -> str:
        token = get_token()
        if not token:
            return ""
        return token

    def _record_pricing_warning(reason: str) -> None:
        """
        Persist warning telemetry for admin visibility when live CRM pricing data is incomplete.
        """
        try:
            cache = get_cache()
            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            key_count = "pricing_warning:count"
            prev = cache.get_state(key_count) or "0"
            try:
                next_count = int(prev) + 1
            except Exception:
                next_count = 1
            cache.set_state("pricing_warning:last_event_at", now_iso)
            cache.set_state("pricing_warning:last_reason", str(reason or "unknown")[:240])
            cache.set_state(key_count, str(next_count))
        except Exception:
            pass

    def _csrf_token() -> str:
        tok = (session.get("csrf_token") or "").strip() if isinstance(session.get("csrf_token"), str) else ""
        if not tok:
            tok = secrets.token_urlsafe(32)
            session["csrf_token"] = tok
        return tok

    @app.context_processor
    def _inject_csrf() -> dict[str, Any]:
        return {"csrf_token": _csrf_token}

    def _canonical_base() -> str:
        """
        The one hostname search engines should see.

        Everything else — the staging host, the apex, http — is a duplicate of
        it, so absolute URLs in the markup and the sitemap are built from
        WEBSITE_CANONICAL_DOMAIN when it is set rather than from the Host header
        the request happened to arrive on.
        """
        brand: BrandConfig = app.config["BRAND_CONFIG"]
        if brand.canonical_domain:
            return f"https://{brand.canonical_domain}"
        return request.url_root.rstrip("/")

    @app.template_global("schedule_sentence")
    def _schedule_sentence_global(schedule: Any) -> str:
        """The draw run in words, for any template holding a quote line."""
        return _schedule_sentence(schedule)

    @app.template_filter("term_slug")
    def _term_slug(value: str) -> str:
        """A blog category or tag name as it appears in its archive URL."""
        return blog_content.slugify(value)

    @app.context_processor
    def _inject_seo() -> dict[str, Any]:
        endpoint = request.endpoint or ""
        view_args = request.view_args or {}
        meta: dict[str, str] = {}
        share_image = ""
        try:
            if endpoint in {"play", "results_game"}:
                code = str(view_args.get("game_code") or "")
                game = _catalog_game(code)
                crm_name = (game or {}).get("game_name")
                meta = seo.play_seo(code, crm_name) if endpoint == "play" else seo.results_seo(code, crm_name)
                _lot = lo_lotteries.by_game_code(code)
                share_image = f"/images/lottery-assets/logo_main_{_lot.legacy_code}.png" if _lot else ""
            else:
                meta = seo.page_seo(endpoint)
        except Exception:
            meta = {}

        # LottosOnline: a page that exists on the live site keeps the exact title and description it
        # was captured with (approved description fixes applied). This beats every table above.
        try:
            captured = (app.config.get("LO_LEGACY_PAGES") or {}).get(request.path) if app.config.get("LO_LEGACY_PAGES") else None
        except Exception:
            captured = None
        if captured and captured.get("title"):
            meta = {"title": captured["title"], "description": seo.description_for(request.path, captured.get("description") or "")}

        # Pages whose metadata is data rather than configuration — a blog post
        # carries its own title and description — set these on `g`.
        override: dict[str, str] = getattr(g, "seo_override", None) or {}
        title = override.get("title") or meta.get("title") or seo.DEFAULT_TITLE
        description = override.get("description") or meta.get("description") or seo.DEFAULT_DESCRIPTION
        share_image = override.get("og_image") or share_image
        base = _canonical_base()
        # Social previews ignore SVG, so the share image is a raster — the game's
        # own logo where the page is about one game, the brand card otherwise.
        # `images/logo.png` is a stock template banner, not ours; it was the
        # default here and every shared link previewed as "React Core Boilerplate".
        if share_image.startswith("/"):
            share_image = base + share_image
        elif not share_image.startswith("http"):
            share_image = base + url_for("static", filename=SHARE_CARD_PATH)
        # Query strings (month pickers, pagination, tracking tags) are all views
        # of the same page.
        canonical = base + (request.path if request.path != "/" else "/")
        return {
            "seo": {
                "title": title,
                "description": description,
                "canonical": canonical,
                "canonical_root": base + "/",
                "robots": "noindex, follow" if seo.is_noindex(endpoint) else "index, follow",
                "og_image": share_image,
                "og_type": override.get("og_type") or "website",
                "brand_logo": base + url_for("static", filename=BRAND_LOGO_PATH),
                "site_name": seo.BRAND,
            }
        }

    def _validate_admin_csrf() -> bool:
        sent = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "").strip()
        want = (session.get("csrf_token") or "").strip() if isinstance(session.get("csrf_token"), str) else ""
        if not sent or not want:
            return False
        try:
            return secrets.compare_digest(sent, want)
        except Exception:
            return sent == want

    def _sanitize_admin_next(raw: str | None) -> str | None:
        s = (raw or "").strip()
        if not s:
            return None
        if "://" in s or s.startswith("//"):
            return None
        if not s.startswith("/admin"):
            return None
        # Never allow login to target itself (prevents recursive next=/admin/login?... loops).
        s_path = s.split("?", 1)[0]
        if s_path in ("/admin/login", "/admin/login/"):
            return None
        # Normalize trailing slash so /admin/crm-cache/ resolves to the defined route.
        if len(s) > 1 and s.endswith("/"):
            s = s.rstrip("/")
        return s

    def _require_admin() -> bool:
        try:
            if bool(session.get("admin_authed")):
                return True
        except Exception:
            pass

        token = (os.getenv("WEBSITE_ADMIN_TOKEN") or "").strip()
        if token:
            got = (
                request.headers.get("X-Admin-Token")
                or request.args.get("admin_token")
                or request.args.get("token")
                or ""
            ).strip()
            if got == token:
                try:
                    session["admin_authed"] = True
                    session.permanent = True
                except Exception:
                    pass
                return True

        if (os.getenv("WEBSITE_ADMIN_PASSWORD") or "").strip():
            return False
        return not bool(token)

    @app.before_request
    def _admin_auth_gate():
        try:
            path = (request.path or "").strip()
        except Exception:
            path = ""
        path_norm = path.rstrip("/") if path.endswith("/") and path != "/" else path
        if not path.startswith("/admin"):
            return None
        if path_norm in ("/admin/login", "/admin/logout"):
            return None
        if not (os.getenv("WEBSITE_ADMIN_PASSWORD") or "").strip() and not (os.getenv("WEBSITE_ADMIN_TOKEN") or "").strip():
            return None
        if not _require_admin():
            nxt = (request.full_path or path).strip()
            if nxt.endswith("?"):
                nxt = nxt[:-1]
            nxt = _sanitize_admin_next(nxt) or "/admin/crm-cache"
            return redirect(url_for("admin_login", next=nxt))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not _validate_admin_csrf():
                flash("Your admin session has expired. Please try again.", "danger")
                return redirect(url_for("admin_login", next="/admin/crm-cache"))
        return None

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    def _slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    def _find_local_logo(code: str, name: str) -> str | None:
        """
        Try to find a legacy logo file shipped in /resources/images.
        Prefers small logos (s-lotto-logo-*) then falls back to other sizes.
        """
        # LottosOnline: its own lottery artwork, by CRM game code (the round logo the old site used).
        _lot = lo_lotteries.by_game_code(code)
        if _lot:
            return f"/images/lottery-assets/logo_large_round_{_lot.legacy_code}.png"

        images_dir = os.path.join(app.config["LEGACY_RESOURCES_DIR"], "images")
        base_name = re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()

        # Start with explicit mappings (highest confidence).
        mapped = (g.brand.legacy_game_name_to_logo_small_path or {}).get(norm(name))
        if not mapped:
            mapped = (g.brand.legacy_game_name_to_logo_small_path or {}).get(norm(code))
        if not mapped:
            mapped = (g.brand.legacy_game_name_to_logo_small_path or {}).get(norm(base_name))
        if mapped:
            return mapped

        # Heuristic: try common filename patterns.
        slugs: list[str] = []
        for raw in (code, base_name, base_name.replace(" ", "-")):
            if not raw:
                continue
            s = _slug(raw)
            if s:
                slugs.append(s)
                slugs.append(s.replace("australian", "aus"))
                slugs.append(s.replace("american", "usa"))
                slugs.append(s.replace("euro-millions", "euro-millions"))
        seen: set[str] = set()
        for s in slugs:
            if s in seen:
                continue
            seen.add(s)
            for prefix in ("s-lotto-logo-", "l-lotto-logo-", "xs-lotto-logo-"):
                fn = f"{prefix}{s}.png"
                if os.path.exists(os.path.join(images_dir, fn)):
                    return f"/resources/images/{fn}"
        return None

    def _hero_logo_url(code: str, name: str) -> str | None:
        """
        The banner-sized logo for a game, falling back to the small one.

        `_find_local_logo` prefers `s-lotto-logo-*` because most callers are
        listings; anything showing a game at banner size wants the `l-` twin of
        the same file where one was shipped.
        """
        logo = _find_local_logo(str(code), str(name or code))
        if logo and logo.startswith("/resources/images/s-lotto-logo-"):
            candidate = logo.replace("/resources/images/s-lotto-logo-", "/resources/images/l-lotto-logo-")
            images_dir = os.path.join(app.config["LEGACY_RESOURCES_DIR"], "images")
            if os.path.exists(os.path.join(images_dir, os.path.basename(candidate))):
                logo = candidate
        return logo

    def tokens(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", s.lower()))

    def store_games_cached() -> list[dict]:
        # Store games cached in SQLite sync_state.
        # IMPORTANT: must refresh periodically so new CRM products appear automatically.
        cache = get_cache()
        cached_json = cache.get_state("store_games_json")
        fetched_at_s = cache.get_state("store_games_fetched_at")
        now = int(datetime.now(timezone.utc).timestamp())
        ttl = _store_games_ttl_seconds()

        def _parse_cached() -> list[dict]:
            if not cached_json:
                return []
            try:
                data = json.loads(cached_json)
                if isinstance(data, dict) and isinstance(data.get("games"), list):
                    return [g for g in data.get("games") if isinstance(g, dict)]
            except Exception:
                return []
            return []

        cached_games = _parse_cached()

        # If cache exists and is fresh enough, serve it.
        is_stale = True
        if fetched_at_s:
            try:
                is_stale = (now - int(float(fetched_at_s))) > ttl
            except Exception:
                is_stale = True
        else:
            # Treat missing fetched_at as stale, but still serve cached if present.
            is_stale = True

        if cached_games and not is_stale:
            return cached_games

        # If we have cached data but it's stale, kick a background refresh (don't block render).
        if cached_games and is_stale and not _crm_cache_only_mode():
            if cache.try_acquire_lock("store_games_refresh", ttl_seconds=120):
                def _run_refresh() -> None:
                    try:
                        client = CRMClient(load_crm_config_from_env())
                        data = client._request(
                            "GET",
                            "/api/v1/store/games",
                            service_key=True,
                            timeout_seconds=_layout_timeout_seconds(),
                        )
                        if isinstance(data, dict) and isinstance(data.get("games"), list):
                            cache.set_state("store_games_json", json.dumps(data, ensure_ascii=False))
                            cache.set_state("store_games_fetched_at", str(int(datetime.now(timezone.utc).timestamp())))
                    except Exception:
                        pass
                    finally:
                        cache.release_lock("store_games_refresh")
                threading.Thread(target=_run_refresh, name="store_games_refresh", daemon=True).start()
            return cached_games

        # If no cached data, attempt a synchronous fetch.
        if cached_json:
            # Could be corrupted; fall through to live fetch if allowed.
            pass

        if not _crm_cache_only_mode():
            try:
                data = get_crm()._request("GET", "/api/v1/store/games", service_key=True, timeout_seconds=_layout_timeout_seconds())
                if isinstance(data, dict) and isinstance(data.get("games"), list):
                    cache.set_state("store_games_json", json.dumps(data, ensure_ascii=False))
                    cache.set_state("store_games_fetched_at", str(now))
                    return [g for g in data.get("games") if isinstance(g, dict)]
            except Exception:
                pass
        return []

    # --- Marketing Module tracking (server-side posting) ---
    MKT_EVENT_ALLOWLIST = {
        "click",
        "pageview",
        "campaign_touch",
        "signup_started",
        "signup_completed",
        "checkout_started",
        "submit_attempt",
        "purchase_failed",
        "purchase_completed",
        "first_purchase_completed",
    }

    def _now_iso_utc() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _mkt_ctx() -> dict:
        mkt = session.get("mkt", {}) if isinstance(session.get("mkt", {}), dict) else {}
        return {
            "src": mkt.get("src"),
            "cmp": mkt.get("cmp"),
            "tid": mkt.get("tid"),
            "intent": mkt.get("intent"),
        }

    def _stable_key(name: str) -> str:
        # Stored stable keys in session so retries/reloads dedupe correctly.
        k = session.get(name)
        if isinstance(k, str) and k:
            return k
        k = uuid.uuid4().hex
        session[name] = k
        return k

    def emit_marketing_event(
        event_type: str,
        *,
        stable_key: str,
        metadata: dict | None = None,
        customer_id: int | None = None,
    ) -> bool:
        """
        Posts to CRM /api/v1/marketing/events using the service key.
        Returns True if sent successfully; False otherwise (we don't want to break UX).
        """
        if event_type not in MKT_EVENT_ALLOWLIST:
            return False

        ctx = _mkt_ctx()
        payload: dict = {
            "event_id": f"web:{g.brand.slug}:{event_type}:{stable_key}",
            "event_type": event_type,
            "occurred_at": _now_iso_utc(),
        }
        if ctx.get("cmp"):
            payload["campaign_code"] = ctx["cmp"]
        if ctx.get("src") and ctx.get("intent") != "lifecycle":
            payload["source_code"] = ctx["src"]
        if ctx.get("tid"):
            payload["click_id"] = ctx["tid"]
        if customer_id is not None:
            payload["customer_id"] = customer_id
        if metadata is not None:
            payload["metadata"] = metadata

        try:
            get_crm().marketing_events(payload, token=get_token())
            return True
        except Exception:
            return False

    # `rt` and `spt` are lookup keys for somebody's name and date of birth, and
    # an analytics payload is precisely the kind of record that is kept for
    # years and read by people who were never told what is in it. Attribution
    # reaches the Module separately and server-side, from the session, so
    # nothing of analytical value is lost by taking a query string out.
    _TOKEN_IN_TEXT_RE = re.compile(r"(?i)(\b(?:rt|spt|token)=)[^&\s\"']+")

    def _analytics_safe(value: Any) -> Any:
        if isinstance(value, str):
            return _TOKEN_IN_TEXT_RE.sub(r"\1[redacted]", value)
        return value

    def _analytics_safe_path(raw: str) -> str:
        # The browser sends a bare pathname today. This does not depend on it:
        # the page decides what to report, and the guarantee has to hold on
        # this side of the wire.
        return str(raw).split("#", 1)[0].split("?", 1)[0]

    @app.post("/api/track/click")
    def track_click():
        data = request.get_json(silent=True) or {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        # This dict is whatever the page chose to send, forwarded wholesale, so
        # any page that ever puts a URL in it must not be able to leak a token.
        metadata = {k: _analytics_safe(v) for k, v in metadata.items()}
        cta = (metadata.get("cta") or "").strip()
        # Marketing guide requires register click be click + metadata.cta="register"
        if cta and cta.lower() != cta:
            metadata["cta"] = cta.lower()
            cta = metadata["cta"]

        ctx = _mkt_ctx()
        if cta:
            stable_key = f"{ctx.get('tid') or _stable_key('mkt_click_uuid')}:{cta}"
        else:
            stable_key = ctx.get("tid") or _stable_key("mkt_click_uuid")

        sent = emit_marketing_event("click", stable_key=stable_key, metadata=metadata)
        return {"success": True, "sent": sent}

    @app.post("/api/track/pageview")
    def track_pageview():
        data = request.get_json(silent=True) or {}
        path = _analytics_safe_path((data.get("path") or request.path or "").strip())
        ctx = _mkt_ctx()
        stable_key = f"{ctx.get('tid') or _stable_key('mkt_pageview_uuid')}:{path}"
        sent = emit_marketing_event("pageview", stable_key=stable_key, metadata={"path": path})
        return {"success": True, "sent": sent}

    def _is_sales_closed(jp: dict[str, Any]) -> bool:
        # Winnow logic: explicit closed flags/state OR cutoff passed OR remaining_seconds <= 0
        try:
            for k in ("sales_closed", "is_sales_closed", "salesClosed", "closed"):
                if k in jp and jp.get(k) is True:
                    return True
        except Exception:
            pass
        try:
            st = str(jp.get("status") or jp.get("state") or jp.get("draw_status") or "").strip().lower()
            if st in ("sales_closed", "closed", "results_pending", "pending_results"):
                return True
        except Exception:
            pass
        rem = None
        try:
            rem = int(jp.get("remaining_seconds"))
        except Exception:
            rem = None
        cutoff_raw = jp.get("cutoff_at_utc") or jp.get("next_draw_utc")
        cutoff_dt = None
        if cutoff_raw:
            try:
                cutoff_dt = datetime.fromisoformat(str(cutoff_raw).replace("Z", "+00:00"))
                # The CRM sends these with no offset ("2026-09-02T16:00:00"), so
                # they parse naive. Comparing naive against an aware `now` raises,
                # and the caller reads that as "sales open" for every game.
                if cutoff_dt.tzinfo is None:
                    cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
            except Exception:
                cutoff_dt = None
        now = datetime.now(timezone.utc)
        return (cutoff_dt is not None and now >= cutoff_dt) or (rem is not None and rem <= 0)

    def _get_jackpots_live_or_cache(*, timeout_seconds: int | None = None) -> tuple[list[dict[str, Any]], bool]:
        """
        Returns (jackpots, from_cache).
        Live-first; on failure (or cache-only mode) returns cached jackpots.
        """
        cache = get_cache()
        if _crm_cache_only_mode():
            return cache.get_cached_jackpots(), True

        try:
            data = get_crm()._request(
                "GET",
                "/api/v1/jackpots",
                params={"configured_only": 1},
                service_key=True,
                timeout_seconds=timeout_seconds if timeout_seconds is not None else _layout_timeout_seconds(),
            )
            jackpots = data.get("jackpots") or []
            jackpots = [j for j in jackpots if isinstance(j, dict)]
            try:
                cache.upsert_jackpots(jackpots)
            except Exception:
                pass
            return jackpots, False
        except Exception:
            return cache.get_cached_jackpots(), True

    def marketing_banners_cached(placement: str) -> list[dict]:
        cache = get_cache()
        key = f"mkt_banners_json:{placement}"
        cached_json = cache.get_state(key)

        def _banners_of(raw: str | None) -> list[dict] | None:
            if not raw:
                return None
            try:
                data = json.loads(raw)
            except Exception:
                return None
            if isinstance(data, dict) and isinstance(data.get("banners"), list):
                return [b for b in data.get("banners") if isinstance(b, dict)]
            return None

        # The timestamp written beside the payload was never read back, so the
        # first answer the CRM gave was kept for good and an empty list from a
        # gap between campaigns became permanent. This cache had been serving
        # an empty payload fetched in March ever since.
        now = int(datetime.now(timezone.utc).timestamp())
        try:
            fetched_at = int(cache.get_state(f"{key}:fetched_at") or 0)
        except Exception:
            fetched_at = 0
        if cached_json and (now - fetched_at) < _marketing_banners_ttl_seconds():
            cached = _banners_of(cached_json)
            if cached is not None:
                return cached

        live_key = f"mkt_banners:{placement}"
        if not _crm_cache_only_mode():
            token = get_token()
            try:
                data = get_crm()._request(
                    "GET",
                    "/api/v1/marketing/banners",
                    service_key=True,
                    token=token,
                    params={"placement": placement},
                    timeout_seconds=_layout_timeout_seconds(),
                )
                if isinstance(data, dict) and isinstance(data.get("banners"), list):
                    cache.set_state(key, json.dumps(data, ensure_ascii=False))
                    cache.set_state(f"{key}:fetched_at", str(now))
                    return [b for b in data.get("banners") if isinstance(b, dict)]
            except Exception:
                pass

        # A CRM that is slow or briefly down should leave the banners that are
        # already up in place rather than blank the strip.
        stale = _banners_of(cached_json)
        return stale if stale is not None else []

    def layout_model() -> dict:
        """
        CRM-driven layout model for legacy-look templates.

        This is the key mechanism that makes new CRM games/products appear on the website
        automatically (nav/footer/catalog), matching Winnow behavior.
        """
        def _kick_refresh_jackpots_if_needed(cache: CRMCache) -> None:
            # Never block page render on jackpots API; refresh in background.
            now = int(datetime.now(timezone.utc).timestamp())
            last = cache.get_state("last_jackpots_fetch_at")
            ttl = _cache_ttl_seconds()
            is_stale = True
            if last:
                try:
                    # last stored as ISO; best-effort parse to epoch
                    last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    is_stale = (now - int(last_dt.timestamp())) > ttl
                except Exception:
                    is_stale = True
            if not is_stale:
                return
            if not cache.try_acquire_lock("jackpots_refresh", ttl_seconds=120):
                return

            def _run() -> None:
                try:
                    client = CRMClient(load_crm_config_from_env())
                    data = client._request(
                        "GET",
                        "/api/v1/jackpots",
                        params={"configured_only": 1},
                        service_key=True,
                    )
                    jackpots = data.get("jackpots") or []
                    jackpots = [j for j in jackpots if isinstance(j, dict)]
                    cache.upsert_jackpots(jackpots)
                except Exception:
                    pass
                finally:
                    cache.release_lock("jackpots_refresh")

            threading.Thread(target=_run, name="jackpots_refresh", daemon=True).start()

        debug_perf = _env_bool("DEBUG_PERF", False)
        t0 = time.perf_counter() if debug_perf else 0.0
        games = store_games_cached()
        t_games = time.perf_counter() if debug_perf else 0.0

        # Winnow-style: live-first with cache fallback. Use a longer timeout only if cache is empty.
        cache = get_cache()
        cached_jackpots = cache.get_cached_jackpots()
        # Keep jackpots fresh without blocking page render (important when CRM is slow).
        if not _crm_cache_only_mode():
            try:
                _kick_refresh_jackpots_if_needed(cache)
            except Exception:
                pass
        tmo = _first_jackpots_timeout_seconds() if (not cached_jackpots and not _crm_cache_only_mode()) else _layout_timeout_seconds()
        jackpots, _from_cache = _get_jackpots_live_or_cache(timeout_seconds=tmo)
        t_jp = time.perf_counter() if debug_perf else 0.0

        jackpot_by_code: dict[str, str] = {}
        jackpot_total_by_code: dict[str, float] = {}
        jackpot_currency_by_code: dict[str, str] = {}
        jackpot_currency_symbol_by_code: dict[str, str] = {}
        jackpot_amount_str_by_code: dict[str, str] = {}
        cutoff_by_code: dict[str, str] = {}
        logo_by_code: dict[str, str] = {}
        remaining_by_code: dict[str, int] = {}
        sales_closed_by_code: dict[str, bool] = {}

        # Adjust remaining_seconds for cached jackpots based on age, so countdowns don't start stale.
        elapsed = 0
        if _from_cache:
            last = cache.get_state("last_jackpots_fetch_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    elapsed = max(0, int(datetime.now(timezone.utc).timestamp() - last_dt.timestamp()))
                except Exception:
                    elapsed = 0

        for j in jackpots:
            code = j.get("game_code")
            if not code:
                continue
            if j.get("logo_url"):
                logo_by_code[code] = j["logo_url"]
            if j.get("cutoff_at_utc"):
                cutoff_by_code[code] = j["cutoff_at_utc"]
            try:
                rem = int(j.get("remaining_seconds"))
                if elapsed:
                    rem = rem - elapsed
                remaining_by_code[code] = rem
            except Exception:
                pass
            try:
                sales_closed_by_code[code] = _is_sales_closed(j)
            except Exception:
                sales_closed_by_code[code] = False
            # Numeric jackpot total for sorting.
            try:
                jt = j.get("jackpot_total")
                if jt is None and isinstance(j.get("jackpot"), dict):
                    jt = (j.get("jackpot") or {}).get("amount")
                if jt is not None:
                    jackpot_total_by_code[code] = float(jt)
            except Exception:
                pass
            try:
                cur = j.get("currency")
                if not cur and isinstance(j.get("jackpot"), dict):
                    cur = (j.get("jackpot") or {}).get("currency")
                if cur:
                    jackpot_currency_by_code[code] = str(cur)
            except Exception:
                pass

            # Display strings (legacy style): symbol + comma formatted amount
            cur_code = jackpot_currency_by_code.get(code)
            sym = _currency_symbol(cur_code)
            jt = jackpot_total_by_code.get(code)
            if jt is not None and sym:
                amt_str = f"{jt:,.0f}"
                jackpot_currency_symbol_by_code[code] = sym
                jackpot_amount_str_by_code[code] = amt_str
                jackpot_by_code[code] = f"{sym}{amt_str}"
            else:
                # Fallback: preserve upstream string if no numeric total.
                try:
                    if isinstance(j.get("jackpot"), dict):
                        cur = j["jackpot"].get("currency")
                        amt = j["jackpot"].get("amount")
                        if cur and amt is not None:
                            jackpot_by_code[code] = f"{_currency_symbol(str(cur))}{float(amt):,.0f}"
                except Exception:
                    pass

        def _format_results_date(draw_date: str | None) -> str | None:
            raw = (draw_date or "").strip()
            if not raw or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                return None
            try:
                d = datetime.strptime(raw, "%Y-%m-%d").date()
                # Legacy style (e.g. "Tue 3, Feb")
                return f"{d.strftime('%a')} {d.day}, {d.strftime('%b')}"
            except Exception:
                return None

        def _fmt2(n: int) -> str:
            try:
                return f"{int(n):02d}"
            except Exception:
                return str(n)

        def _format_results_board(numbers: dict[str, Any] | None) -> str | None:
            if not isinstance(numbers, dict) or not numbers:
                return "<span class='pendingResults'>Pending</span>"

            main = numbers.get("main")
            if not isinstance(main, list) or not main:
                # Fallback: treat any int-ish values as main (best effort).
                main = []
                for k, v in numbers.items():
                    if isinstance(v, list) and all(isinstance(x, (int, float, str)) for x in v):
                        # Don't treat obvious bonus lists as main.
                        if str(k).lower() in {"supplementary", "bonus", "lucky_stars", "stars"}:
                            continue
                        main = v
                        break

            main_html: list[str] = []
            for x in main or []:
                try:
                    main_html.append(f"<span class='resultsBall'>{_fmt2(int(x))}</span>")
                except Exception:
                    continue

            # Bonus/supp numbers (render in legacy blue).
            bonus_vals: list[int] = []
            for k in ("bonus", "supplementary", "megaball", "powerball", "lucky_stars", "stars"):
                v = numbers.get(k)
                if isinstance(v, list):
                    for x in v:
                        try:
                            bonus_vals.append(int(x))
                        except Exception:
                            continue
                else:
                    try:
                        if v is not None and str(v).strip() != "":
                            bonus_vals.append(int(v))
                    except Exception:
                        continue

            bonus_html: list[str] = [f"<span class='resultsBall resultBonusNumber'>{_fmt2(b)}</span>" for b in bonus_vals]

            parts = main_html + bonus_html
            if not parts:
                return "<span class='pendingResults'>Pending</span>"
            # Legacy board string has commas without spaces.
            return ",".join(parts)

        def _latest_cached_draw_for_game(cache: CRMCache, game_code: str) -> dict[str, Any] | None:
            try:
                draws = cache.get_draw_results_for_game(game_code, limit=5)
                for d in draws:
                    if not isinstance(d, dict):
                        continue
                    if str(d.get("status") or "").strip().lower() not in {"completed", ""}:
                        continue
                    return d
            except Exception:
                return None
            return None

        nav_lotteries: list[dict] = []
        footer_lotteries: list[dict] = []
        nav_results: list[dict] = []
        footer_results: list[dict] = []
        nav_promos: list[dict] = []
        home_promos: list[dict] = []

        def _banner_to_promo(b: dict[str, Any]) -> dict[str, Any]:
            href = b.get("cta_href") or "#"
            return {
                "title": b.get("title") or "Offer",
                "subtitle": b.get("body") or None,
                "href": href,
                "logo_url": b.get("image_url") or b.get("logo_url") or None,
                "cta_label": b.get("cta_label") or "View offer",
            }

        # Promotions menu should mirror /lotteries/promotions listing placement.
        banners_catalog = marketing_banners_cached("catalog")
        # Homepage featured promotions are driven by "home" placement.
        banners_home = marketing_banners_cached("home")
        if debug_perf:
            t_banners = time.perf_counter()
            try:
                total_ms = int((t_banners - t0) * 1000)
                games_ms = int((t_games - t0) * 1000)
                jp_ms = int((t_jp - t_games) * 1000)
                banners_ms = int((t_banners - t_jp) * 1000)
                _debug_print(
                    f"[perf] layout_model total={total_ms}ms store_games={games_ms}ms jackpots={jp_ms}ms banners={banners_ms}ms",
                    flush=True,
                )
            except Exception:
                pass

        for b in banners_catalog:
            nav_promos.append(_banner_to_promo(b))

        # Featured promotions: prefer home placement, fallback to catalog if empty.
        if banners_home:
            for b in banners_home:
                home_promos.append(_banner_to_promo(b))
        else:
            home_promos = list(nav_promos)

        for game in games:
            code = game.get("game_code")
            name = game.get("game_name") or code
            # Normalize display names when CRM uses internal/region labels.
            if str(code).strip().lower() == "megamillions":
                name = "Mega Millions"
            if str(code).strip().lower() == "lotto-fr":
                name = "French Lotto"
            if str(code).strip().lower() == "lotto-ie":
                name = "Irish Lotto"
            if not code:
                continue

            # Prefer local legacy logo assets (reliable + matches the old design).
            logo_url = _find_local_logo(str(code), str(name))
            if not logo_url:
                logo_url = game.get("logo_url") or logo_by_code.get(code)
            jackpot = jackpot_by_code.get(code)
            jackpot_total = jackpot_total_by_code.get(code)
            jackpot_currency = jackpot_currency_by_code.get(code)
            jackpot_currency_symbol = jackpot_currency_symbol_by_code.get(code)
            jackpot_amount = jackpot_amount_str_by_code.get(code)
            cutoff_at_utc = cutoff_by_code.get(code)
            remaining_seconds = remaining_by_code.get(code)
            sales_closed = sales_closed_by_code.get(code, False)

            # Link straight at the canonical URL. Pointing the site's own
            # navigation at the legacy slug sent every visitor and crawler
            # through a redirect on the way to the same page.
            href = url_for("play", game_code=code)

            # Winnow-style countdown uses remaining_seconds (seconds) rendered into HTML.
            # If missing, derive from cutoff_at_utc.
            if remaining_seconds is None and cutoff_at_utc:
                try:
                    cutoff_dt = datetime.fromisoformat(str(cutoff_at_utc).replace("Z", "+00:00"))
                    # A naive value would be read as server-local by `.timestamp()`.
                    if cutoff_dt.tzinfo is None:
                        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
                    remaining_seconds = int(cutoff_dt.timestamp() - datetime.now(timezone.utc).timestamp())
                except Exception:
                    remaining_seconds = None
            if remaining_seconds is not None and remaining_seconds < 0:
                remaining_seconds = 0

            nav_lotteries.append(
                {
                    "name": name,
                    "href": href,
                    "logo_url": logo_url,
                    "jackpot": jackpot,
                    "jackpot_total": jackpot_total,
                    "jackpot_currency": jackpot_currency,  # ISO code
                    "jackpot_currency_symbol": jackpot_currency_symbol,  # legacy symbol
                    "jackpot_amount": jackpot_amount,  # comma formatted number string
                    "cutoff_at_utc": cutoff_at_utc,
                    "remaining_seconds": remaining_seconds,
                    "sales_closed": sales_closed,
                }
            )
            footer_lotteries.append({"name": name, "href": href})

            rhref = url_for("results_game", game_code=code)
            # Legacy results dropdown shows most recent draw date + board, with "Pending" fallback.
            draw = _latest_cached_draw_for_game(cache, str(code))
            date_disp = _format_results_date(draw.get("draw_date") if isinstance(draw, dict) else None)
            nums = None
            if isinstance(draw, dict):
                if isinstance(draw.get("numbers"), dict):
                    nums = draw.get("numbers")
            board_disp = _format_results_board(nums)
            nav_results.append({"name": name, "href": rhref, "logo_url": logo_url, "date": date_disp, "board": board_disp})
            footer_results.append({"name": name, "href": rhref})

        # Legacy homepage sorts by jackpot size (highest first).
        nav_lotteries.sort(key=lambda x: (x.get("jackpot_total") or 0.0, x.get("name") or ""), reverse=True)

        return {
            "nav_lotteries": nav_lotteries,
            "nav_promos": nav_promos,
            "home_promos": home_promos,
            "nav_results": nav_results,
            "footer_lotteries": footer_lotteries,
            "footer_results": footer_results,
        }

    def _legacy_slug_candidates(legacy_slug: str, *, kind: str) -> list[str]:
        """
        The forms one old URL can take, most specific first.

        Google has these indexed as the old site linked them: mixed case, some
        with `.php`, some with a sub-page ("EuroMillions/Lucky-5"), some naming a
        one-off event ("EuroMillions-Superdraw"). They all belong to one game, so
        each is tried down to the bare game slug.
        """
        s = (legacy_slug or "").strip().strip("/").lower()
        if s.endswith(".php"):
            s = s[: -len(".php")]
        out: list[str] = []

        def add(v: str) -> None:
            v = v.strip("/")
            if v and v not in out:
                out.append(v)

        add(s)
        if "/" in s:
            add(s.split("/", 1)[0])
        if kind == "results" and s.endswith("-winning-numbers"):
            add(s[: -len("-winning-numbers")])
        for value in list(out):
            if value.endswith("-superdraw"):
                add(value[: -len("-superdraw")])
        return out

    def resolve_game_code(legacy_slug: str, *, kind: str) -> str | None:
        brand: BrandConfig = app.config["BRAND_CONFIG"]
        candidates = _legacy_slug_candidates(legacy_slug, kind=kind)
        legacy_slug = candidates[0] if candidates else ""

        code_map = (
            (brand.legacy_lottery_slug_to_game_code or {})
            if kind == "lottery"
            else (brand.legacy_results_slug_to_game_code or {})
            if kind == "results"
            else {}
        )
        name_map = (
            (brand.legacy_lottery_slug_to_game_name or {})
            if kind == "lottery"
            else (brand.legacy_results_slug_to_game_name or {})
            if kind == "results"
            else {}
        )
        code_map = {str(k).strip().strip("/").lower(): v for k, v in code_map.items()}
        name_map = {str(k).strip().strip("/").lower(): v for k, v in name_map.items()}

        desired_name = None
        for candidate in candidates:
            if candidate in code_map:
                return code_map[candidate]
            if desired_name is None:
                desired_name = name_map.get(candidate)

        games = store_games_cached()

        # Rank by a simple score (exact > substring > token overlap).
        desired_norm = norm(desired_name or "")
        desired_tokens = tokens(desired_name or "")

        slug_norm = norm(legacy_slug.replace("-", " "))
        slug_tokens = tokens(legacy_slug.replace("-", " "))

        best_score = -1
        best_code: str | None = None

        for g_ in games:
            name = g_.get("game_name", "") or ""
            code = g_.get("game_code")
            if not code:
                continue

            name_norm = norm(name)
            name_tokens = tokens(name)

            score = 0
            if desired_norm:
                if name_norm == desired_norm:
                    score = max(score, 100)
                elif desired_norm in name_norm or name_norm in desired_norm:
                    score = max(score, 80)
                elif desired_tokens:
                    score = max(score, 10 * len(desired_tokens & name_tokens))

            if slug_norm:
                if name_norm == slug_norm:
                    score = max(score, 90)
                elif slug_norm in name_norm or name_norm in slug_norm:
                    score = max(score, 70)
                elif slug_tokens:
                    score = max(score, 8 * len(slug_tokens & name_tokens))

            # Tiny nudge for common legacy prefixes like "American ".
            if "american" in slug_tokens and "american" not in name_tokens:
                score -= 5

            if score > best_score:
                best_score = score
                best_code = code

        # Require at least *some* signal to avoid wrong matches.
        if best_score >= 16:
            return best_code
        return None

    # --- Core routes ---
    @app.get("/health")
    def health() -> tuple[dict, int]:
        # Local app health check (for nginx/systemd). CRM health is separate.
        return {"ok": True, "brand": g.brand.slug}, 200

    @app.get("/")
    def home():
        # LottosOnline home (templates/lo/home.html): every lottery the site sells, ordered by
        # "% above base" as the old home page ordered them, with the old page's copy word for word.
        import lo_banners
        rows = app.config["LO_HOME_ROWS"]()
        featured = app.jinja_env.globals["lo_featured_rows"](rows)
        try:
            crm_banners = marketing_banners_cached("home")
        except Exception:
            crm_banners = []
        slides = lo_banners.home_slides(rows, featured, crm_banners, logged_in=bool(get_token()),
                                        lo_ball=app.jinja_env.globals["lo_ball"])
        return render_template("lo/home.html", rows=rows, slides=slides, page=app.config["LO_LEGACY_PAGES"].get("/"))

    @app.get("/lottery-tickets")
    def catalog():
        return render_template("lo/lottery_tickets.html", rows=app.config["LO_HOME_ROWS"](),
                               page=app.config["LO_LEGACY_PAGES"].get("/lottery-tickets"))

    def _play_unavailable(game_code: str):
        # 503 + Retry-After: search engines retry later and keep the page's
        # ranking; a 500 reads as a broken page.
        lot = lo_lotteries.by_game_code(game_code)
        html_out = render_template("lo/play_unavailable.html", lottery=lot,
                                   results_href=lo_lotteries.results_path(lot) if lot and lot.results else None)
        return html_out, 503, {"Retry-After": "300", "Cache-Control": "no-store"}

    @app.get("/lottery-tickets/<lo_play:game_code>")
    def play(game_code: str):
        # Legacy-like "edit your order" fallback target.
        session["last_play_url"] = request.path
        try:
            resp = get_crm().store_game(game_code)
        except CRMError:
            # Every code reaching here is one of LottosOnline's own lotteries (the
            # lo_play converter only matches those), so a CRM 404 means the
            # brand's product is missing or switched off: temporary. A 404 here
            # would tell search engines a ranking page is gone.
            return _play_unavailable(game_code)
        except Exception:
            # CRM unreachable (connection refused, timeout): a temporary outage,
            # shown as such rather than as an error page.
            return _play_unavailable(game_code)
        game = resp.get("game") if isinstance(resp, dict) else None
        if not isinstance(game, dict):
            game = None

        # Normalize products: some CRM variants return products under different keys.
        products = []
        if isinstance(game, dict):
            for k in ("products", "default_products", "skus"):
                v = game.get(k)
                if isinstance(v, list) and v:
                    products = [p for p in v if isinstance(p, dict)]
                    break
        if not products and isinstance(resp, dict) and isinstance(resp.get("products"), list):
            products = [p for p in resp.get("products") if isinstance(p, dict)]
        if not products:
            # Fallback: filter store products by game_code (safe, still store-scoped).
            try:
                allp = get_crm().store_products()
                if isinstance(allp, dict) and isinstance(allp.get("products"), list):
                    products = [
                        p
                        for p in allp.get("products")
                        if isinstance(p, dict) and (p.get("game_code") == game_code or p.get("game") == game_code)
                    ]
            except Exception:
                pass
        # The per-currency retail prices are documented on the store *products*
        # endpoint; some CRM builds omit them from the game payload. Without them
        # the picker can only quote the base-currency amount, which is not what
        # the cart charges, so fill the gap from the products endpoint.
        try:
            if products and any(not isinstance(p.get("prices_by_currency"), dict) for p in products):
                allp = get_crm().store_products()
                by_code: dict[str, dict[str, Any]] = {}
                if isinstance(allp, dict) and isinstance(allp.get("products"), list):
                    for p in allp["products"]:
                        if not isinstance(p, dict):
                            continue
                        code = str(p.get("code") or p.get("product_code") or "").strip().upper()
                        if code:
                            by_code[code] = p
                for p in products:
                    if isinstance(p.get("prices_by_currency"), dict):
                        continue
                    src = by_code.get(str(p.get("code") or p.get("product_code") or "").strip().upper())
                    if isinstance(src, dict) and isinstance(src.get("prices_by_currency"), dict):
                        p["prices_by_currency"] = src["prices_by_currency"]
        except CRMError:
            pass

        # No product to sell (empty payload, or the game with nothing enabled):
        # an empty picker would be a soft error page, and a 404 would de-index
        # one of LottosOnline's own lottery pages. Temporarily unavailable.
        if not products:
            return _play_unavailable(game_code)

        if isinstance(game, dict):
            game["products"] = products
            # Normalize display name for legacy parity.
            if str(game_code).strip().lower() == "megamillions":
                game["game_name"] = "Mega Millions"
            if str(game_code).strip().lower() == "lotto-fr":
                game["game_name"] = "French Lotto"
            if str(game_code).strip().lower() == "lotto-ie":
                game["game_name"] = "Irish Lotto"

        # Legacy page IDs are hard-coded in the legacy CSS (e.g. #usMegaMillionsLottoPage).
        legacy_page_id = {
            "megamillions": "usMegaMillionsLottoPage",
            "powerball": "usPowerballLottoPage",
            "australianpowerball": "ausPowerballLottoPage",
            "superenalotto": "superEnalottoLottoPage",
            "euromillions": "euromillionsLottoPage",
            "eurojackpot": "eurojackpotLottoPage",
            "sat-lotto-au": "ozLottoPage",
            "oz-lotto-au": "ozLottoPage",
            "irishlotto": "irishLottoPage",
            "lotto-ie": "irishLottoPage",
            "frenchlotto": "frenchLottoPage",
            "lotto-fr": "frenchLottoPage",
            "ozlotto": "ozLottoPage",
            "canadianlotto": "canadianLottoPage",
            "canadianlottomax": "canadianLottoPage",
            "spanishlotto": "spanishLottoPage",
        }.get(str(game_code).strip().lower())
        if not legacy_page_id:
            legacy_page_id = f"lottoPage_{re.sub(r'[^a-zA-Z0-9_\\-]+', '_', str(game_code))}"

        picker_products: list[dict[str, Any]] = []
        fallback_prices = _get_cached_product_price_lookup()
        fallback_currency = (os.environ.get("CRM_PRICE_FALLBACK_CURRENCY") or "EUR").strip().upper() or "EUR"
        try:
            for p in products:
                if not isinstance(p, dict):
                    continue
                p_code = p.get("code") or p.get("product_code")
                p_code_u = str(p_code or "").strip().upper()
                p_price = p.get("price_in_base_cents")
                if p_price is None and p_code_u and (p_code_u in fallback_prices):
                    p_price = fallback_prices.get(p_code_u)
                picker_products.append(
                    {
                        "code": p_code,
                        "game_code": p.get("game_code") or p.get("game"),
                        "product_type": p.get("product_type"),
                        "price_in_base_cents": p_price,
                        "base_currency": p.get("base_currency") or fallback_currency,
                        # Per-currency retail prices, so the picker quotes the price
                        # the customer will actually be charged instead of labelling
                        # a base-currency amount with their currency symbol.
                        "prices_by_currency": p.get("prices_by_currency"),
                        "line_schema": p.get("line_schema"),
                        "addons": p.get("addons"),
                    }
                )
        except Exception:
            picker_products = []

        # Jackpot context for hero/banner (from cached jackpots).
        jp = None
        try:
            for j in get_cache().get_cached_jackpots():
                if isinstance(j, dict) and j.get("game_code") == game_code:
                    jp = j
                    break
        except Exception:
            jp = None

        jackpot_display = None
        remaining_seconds = None
        try:
            if isinstance(jp, dict):
                cur = jp.get("currency") or (jp.get("jackpot") or {}).get("currency")
                amt = jp.get("jackpot_total")
                if amt is None and isinstance(jp.get("jackpot"), dict):
                    amt = (jp.get("jackpot") or {}).get("amount")
                if cur and amt is not None:
                    jackpot_display = f"{_currency_symbol(str(cur))}{float(amt):,.0f}"

                remaining_seconds = jp.get("remaining_seconds")
                try:
                    remaining_seconds = int(remaining_seconds) if remaining_seconds is not None else None
                except Exception:
                    remaining_seconds = None

                # Adjust remaining_seconds based on how old the cached jackpots are.
                if remaining_seconds is not None:
                    last = get_cache().get_state("last_jackpots_fetch_at")
                    if last:
                        try:
                            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                            elapsed = max(0, int(datetime.now(timezone.utc).timestamp() - last_dt.timestamp()))
                            remaining_seconds = max(0, remaining_seconds - elapsed)
                        except Exception:
                            pass
        except Exception:
            pass

        # LottosOnline: the long copy under the picker is the live page's captured copy (lo_page in play.html),
        # not the per-game content partials Lotto Express used.
        content_details_template = None
        content_copy_template = None

        hero_logo = _hero_logo_url(str(game_code), str(game.get("game_name") if isinstance(game, dict) else game_code))

        banner_title = f"Next {game.get('game_name') if isinstance(game, dict) else game_code}"
        if game_code == "megamillions":
            banner_title = "Next American Mega Millions"
        play_display_currency = _resolve_display_currency(
            wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
            customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
        )

        # What the picker will quote, and in which currency. If this disagrees
        # with the cart, the CRM quote is authoritative and the gap is here.
        for _p in picker_products:
            _map = _p.get("prices_by_currency")
            _entry = _map.get(play_display_currency) if isinstance(_map, dict) else None
            app.logger.info(
                "play picker price %s: display_currency=%s display_cents=%s "
                "base_currency=%s base_cents=%s prices_by_currency=%s",
                _p.get("code"),
                play_display_currency,
                (_entry or {}).get("amount_cents") if isinstance(_entry, dict) else None,
                _p.get("base_currency"),
                _p.get("price_in_base_cents"),
                "present" if isinstance(_map, dict) else "absent",
            )

        pending_line_edit = session.get("pending_line_edit") if isinstance(session.get("pending_line_edit"), dict) else None
        line_edit_ctx = None
        if isinstance(pending_line_edit, dict):
            if str(pending_line_edit.get("game_code") or "").strip().lower() == str(game_code).strip().lower():
                line_edit_ctx = {
                    "item_idx": pending_line_edit.get("item_idx"),
                    "line_idx": pending_line_edit.get("line_idx"),
                    "product_code": pending_line_edit.get("product_code"),
                    "line": pending_line_edit.get("line"),
                }

        return render_template(
            "play.html",
            game=game,
            jackpot=jp,
            jackpot_display=jackpot_display,
            remaining_seconds=remaining_seconds,
            content_details_template=content_details_template,
            content_copy_template=content_copy_template,
            hero_logo_url=hero_logo,
            banner_title=banner_title,
            legacy_page_id=legacy_page_id,
            picker_products=picker_products,
            picker_display_currency=play_display_currency,
            picker_display_currency_symbol=_currency_symbol(play_display_currency) or play_display_currency,
            line_edit_ctx=line_edit_ctx,
            disable_legacy_ticket_js=True,
            jackpot_payload=jp if isinstance(jp, dict) else {},
        )

    @app.post("/cart/add")
    def cart_add():
        token = require_login()
        if not token:
            # Preserve the attempted add-to-cart so we can complete it after login.
            try:
                session["pending_cart_add"] = {
                    "product_code": (request.form.get("product_code") or "").strip(),
                    "lines_json": (request.form.get("lines_json") or "").strip(),
                    "options_json": (request.form.get("options_json") or "").strip(),
                    "edit_order_url": (request.form.get("edit_order_url") or "").strip(),
                    "game_code": (request.form.get("game_code") or "").strip(),
                    "game_name": (request.form.get("game_name") or "").strip(),
                    "line_edit_item_idx": (request.form.get("line_edit_item_idx") or "").strip(),
                    "line_edit_line_idx": (request.form.get("line_edit_line_idx") or "").strip(),
                    "ts": int(time.time()),
                }
            except Exception:
                pass
            flash("Please sign in before adding tickets to your cart.", "warning")
            # Don't redirect back to this POST-only route.
            return redirect(url_for("login", next=url_for("cart")))

        product_code = (request.form.get("product_code") or "").strip()
        lines_json = (request.form.get("lines_json") or "").strip()
        options_json = (request.form.get("options_json") or "").strip()
        game_code = _safe_game_code(request.form.get("game_code"))
        game_name = (request.form.get("game_name") or "").strip()
        if len(game_name) > 120:
            game_name = game_name[:120]
        edit_order_url = (request.form.get("edit_order_url") or "").strip()
        if not edit_order_url and game_code:
            edit_order_url = url_for("play", game_code=game_code)
        if not edit_order_url:
            try:
                ref = urlparse(request.referrer or "")
                ref_path = (ref.path or "").strip()
                if ref_path.startswith("/") and not ref_path.startswith("//"):
                    edit_order_url = ref_path
            except Exception:
                edit_order_url = ""

        if not product_code:
            abort(400, "Missing product_code")

        try:
            lines = _parse_lines_json(lines_json)
        except Exception as e:
            abort(400, f"Invalid lines_json: {e}")
        lines = [ln for ln in lines if _line_has_any_selection(ln)]
        if not lines:
            flash("Please complete at least one valid line before clicking Play Now.", "warning")
            return redirect(_resolve_edit_order_url(edit_order_url))
        line_error = _line_count_error(product_code, game_code, len(lines))
        if line_error:
            flash(line_error, "warning")
            return redirect(_resolve_edit_order_url(edit_order_url))

        try:
            options = json.loads(options_json) if options_json else {}
            if not isinstance(options, dict):
                raise ValueError("options_json must be a JSON object")
        except Exception as e:
            abort(400, f"Invalid options_json: {e}")

        raw_edit_item_idx = (request.form.get("line_edit_item_idx") or "").strip()
        raw_edit_line_idx = (request.form.get("line_edit_line_idx") or "").strip()
        try:
            edit_item_idx = int(raw_edit_item_idx) if raw_edit_item_idx else -1
            edit_line_idx = int(raw_edit_line_idx) if raw_edit_line_idx else -1
        except Exception:
            edit_item_idx = -1
            edit_line_idx = -1

        cart = session.get("cart_items", [])
        if not isinstance(cart, list):
            cart = []
        if 0 <= edit_item_idx < len(cart):
            item = cart[edit_item_idx] if isinstance(cart[edit_item_idx], dict) else {}
            item_lines = item.get("lines") if isinstance(item, dict) else None
            if not isinstance(item_lines, list) or not (0 <= edit_line_idx < len(item_lines)):
                flash("Could not update that line.", "warning")
                return redirect(url_for("cart", open_item_idx=edit_item_idx))
            if len(lines) != 1:
                flash("Please edit one line at a time.", "warning")
                return redirect(_resolve_edit_order_url(edit_order_url))
            item_lines[edit_line_idx] = lines[0]
            item["lines"] = item_lines
            cart[edit_item_idx] = item
            session["cart_items"] = cart
            session.pop("checkout_quote_id", None)
            session.pop("pending_line_edit", None)
            flash("Line updated.", "success")
            return redirect(url_for("cart", open_item_idx=edit_item_idx))

        cart.append(
            {
                "kind": "single",
                "product_code": product_code,
                "lines": lines,
                "options": options,
                "game_code": game_code or None,
                "game_name": game_name or None,
            }
        )
        session["cart_items"] = cart
        session["cart_edit_order_url"] = _resolve_edit_order_url(edit_order_url)
        if game_code:
            session["cart_last_game_code"] = game_code
        session.pop("pending_line_edit", None)
        # Mark this journey as Play-Now purchase flow so /cart can enforce legacy-like top-up redirect.
        session["cart_force_purchase_topup"] = True

        flash("Added to cart.", "success")
        return redirect(url_for("cart"))

    @app.get("/cart/add")
    def cart_add_get():
        # Friendly redirect for accidental direct navigation (or stale 'next' URLs).
        flash("Please use the ticket picker to add items to your cart.", "warning")
        return redirect(url_for("cart"))

    @app.post("/cart/add-upsell")
    def cart_add_upsell():
        """Add a pre-configured upsell offer to the cart (quickpick lines)."""
        token = require_login()
        if not token:
            flash("Please sign in before adding tickets to your cart.", "warning")
            return redirect(url_for("login", next=url_for("cart")))

        product_code = (request.form.get("product_code") or "").strip()
        lines_json = (request.form.get("lines_json") or "").strip()
        game_code = _safe_game_code(request.form.get("game_code"))
        game_name = (request.form.get("game_name") or "").strip()
        if len(game_name) > 120:
            game_name = game_name[:120]
        # The CRM offer rule this upsell corresponds to. Only a rule the CRM itself
        # listed as eligible is accepted; anything else is dropped rather than trusted,
        # since the CRM will re-price against its own config regardless.
        # Ids are echoed back as the CRM issued them (numeric on this tenant, but
        # not guaranteed), so accept any short opaque token and no more.
        offer_rule_id = (request.form.get("offer_rule_id") or "").strip()
        if offer_rule_id and not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", offer_rule_id):
            app.logger.warning("add-upsell: refusing malformed offer_rule_id %r", offer_rule_id[:80])
            offer_rule_id = ""

        if not product_code:
            abort(400, "Missing product_code")
        if not lines_json:
            abort(400, "Missing lines_json")

        try:
            lines = _parse_lines_json(lines_json)
        except Exception as e:
            abort(400, f"Invalid lines_json: {e}")

        # Default options: 1 week, all draw days
        options = {"_weeks": 1}

        # Best-effort estimated item total used when quote item totals are missing.
        estimated_item_total_cents = 0
        upsell_display_currency = _resolve_display_currency(
            wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
            customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
        )
        try:
            unit_price_cents = 0
            for g_ in store_games_cached():
                if not isinstance(g_, dict):
                    continue
                products = []
                for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
                    v = g_.get(k)
                    if isinstance(v, list):
                        products = [p for p in v if isinstance(p, dict)]
                        if products:
                            break
                    elif isinstance(v, dict):
                        products = [v]
                        break
                for p in products:
                    code = str(p.get("code") or p.get("product_code") or p.get("sku") or "").strip().upper()
                    if code != product_code:
                        continue
                    display_price = _product_price_cents(p, upsell_display_currency)
                    if display_price:
                        unit_price_cents = display_price
                    else:
                        try:
                            raw = p.get("price_in_base_cents")
                            if raw is not None:
                                unit_price_cents = int(float(raw))
                        except Exception:
                            unit_price_cents = 0
                    if unit_price_cents > 0:
                        break
                if unit_price_cents > 0:
                    break
            if unit_price_cents > 0:
                estimated_item_total_cents = unit_price_cents * max(1, len(lines))
        except Exception:
            estimated_item_total_cents = 0

        cart = session.get("cart_items", [])
        cart.append(
            {
                "kind": "single",
                "product_code": product_code,
                "lines": lines,
                "options": {**options, "_is_upsell": True},
                "game_code": game_code or None,
                "game_name": game_name or None,
                "is_upsell": True,
                "offer_rule_id": offer_rule_id or None,
                "estimated_item_total_cents": estimated_item_total_cents,
            }
        )
        session["cart_items"] = cart
        if game_code:
            session["cart_last_game_code"] = game_code
            session["cart_edit_order_url"] = url_for("play", game_code=game_code)
        session["cart_force_purchase_topup"] = True
        # Tell the CRM to apply the offer, so its quote matches what we display.
        _sync_selected_offers_from_cart()

        flash("Upsell offer added to cart.", "success")
        return redirect(url_for("cart"))

    @app.get("/cart")
    def cart():
        items = session.get("cart_items", [])
        if not isinstance(items, list):
            items = []
        cart_view_items: list[dict[str, Any]] = [x for x in items if isinstance(x, dict)]
        # Normalize legacy carts where upsell marker may live only in options.
        for x in cart_view_items:
            if not isinstance(x, dict):
                continue
            if x.get("is_upsell"):
                continue
            opts = x.get("options")
            if isinstance(opts, dict) and opts.get("_is_upsell"):
                x["is_upsell"] = True
        has_upsell_items = any(isinstance(x, dict) and bool(x.get("is_upsell")) for x in cart_view_items)
        has_base_items = any(isinstance(x, dict) and not bool(x.get("is_upsell")) for x in cart_view_items)
        if cart_view_items and not has_base_items:
            # Upsell-only carts are not allowed; upsells require qualifying base items.
            session["cart_items"] = []
            session.pop("checkout_quote_id", None)
            session.pop("checkout_selected_checkout_offers", None)
            cart_view_items = []
            items = []
            has_upsell_items = False
            flash("Upsell items were removed because no qualifying cart items remain.", "warning")
        quote = None
        quote_id = session.get("checkout_quote_id")
        eligible_offers: list[dict] = []
        token = get_token()
        promo_code_active = _checkout_promo_get()
        cart_total_cents = 0
        order_total_cents = 0
        offer_discount_amount_cents = 0
        session_customer = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        session_wallet = session.get("wallet") if isinstance(session.get("wallet"), dict) else {}
        cart_currency = _resolve_display_currency(wallet=session_wallet, customer=session_customer)
        cart_edit_order_url = _resolve_edit_order_url(
            session.get("cart_edit_order_url") if isinstance(session.get("cart_edit_order_url"), str) else None
        )
        open_item_idx_raw = (request.args.get("open_item_idx") or "").strip()
        try:
            open_item_idx = int(open_item_idx_raw) if open_item_idx_raw else None
        except Exception:
            open_item_idx = None
        topup_needed = False
        topup_amount_cents = 0
        topup_cta_url = ""
        # Set when deposits fall short but the customer's winnings would close
        # the gap. That is a question to ask, not a refusal to issue.
        wins_authorization_needed = False
        wins_cover_cents = 0
        cart_funding: dict[str, Any] | None = None

        def is_mm_cart(it: list[dict]) -> bool:
            return any(isinstance(x, dict) and ("product_id" in x) for x in it)

        # A quote the CRM refuses over a promo code or an offer selection is
        # recoverable: drop what it refused and quote again, so the customer sees
        # a priced cart instead of an error banner.
        for _quote_attempt in range(3):
            if not items:
                break
            try:
                if is_mm_cart(items):
                    # MM-managed quote: may be called with service key; token optional.
                    payload: dict[str, Any] = {
                        "items": [
                            {
                                "product_id": int(i.get("product_id")),
                                "quantity": int(i.get("quantity") or 1),
                                "config_json": _as_config_object(i.get("config_json")),
                            }
                            for i in items
                            if isinstance(i, dict) and i.get("product_id") is not None
                        ],
                    }
                    bundle_slug = session.get("checkout_bundle_slug")
                    promo_code = _checkout_promo_get()
                    selected = session.get("checkout_selected_checkout_offers") or []
                    if bundle_slug:
                        payload["bundle_slug"] = bundle_slug
                    if promo_code:
                        payload["promo_code"] = promo_code
                    if selected:
                        payload["selected_checkout_offers"] = selected

                    # Pass marketing context if present.
                    mkt = _mkt_ctx()
                    if mkt.get("tid"):
                        payload["tid"] = mkt.get("tid")
                    if mkt.get("cmp"):
                        payload["cmp"] = mkt.get("cmp")
                    if mkt.get("intent"):
                        payload["intent"] = mkt.get("intent")
                    # Lifecycle touches must not overwrite/source acquisition attribution.
                    if mkt.get("src") and mkt.get("intent") != "lifecycle":
                        payload["src"] = mkt.get("src")

                    resp = get_crm().checkout_quote(payload, token=token, service_key=True)
                    quote = resp.get("quote")
                    new_quote_id = _quote_id_from(resp, context="cart quote (managed)", critical=False)
                    if new_quote_id is not None:
                        session["checkout_quote_id"] = new_quote_id
                        quote_id = new_quote_id
                    eligible_offers = _eligible_offers_from(resp)  # type: ignore[assignment]
                else:
                    # An offer's tickets are ordinary lottery SKUs, so a bundle
                    # cart comes down this branch. Without the slug the CRM has
                    # no reason to apply the locked price and the offer quietly
                    # prices at full.
                    bundle_slug = session.get("checkout_bundle_slug")
                    # The CRM takes the service key alone for a lottery cart, and
                    # a promo customer who has no password yet arrives at the
                    # cart signed out. That is the ordinary promo path, not an
                    # edge case: quoting only when a bearer existed is what
                    # showed a locked £22.50 bundle at the £5 catalog unit price.
                    # Plain play-page carts still wait for a sign-in, so their
                    # behaviour is untouched.
                    if token or bundle_slug:
                        # A bundle's schedule belongs to the CRM, which overwrites
                        # it from the bundle's own config. Sending ours anyway
                        # invites a caller schedule to inflate a locked price.
                        payload: dict[str, Any] = {
                            "items": _crm_cart_items(items, drop_schedule=bool(bundle_slug))
                        }
                        if bundle_slug:
                            payload["bundle_slug"] = bundle_slug
                        promo_code = _checkout_promo_get()
                        selected = session.get("checkout_selected_checkout_offers") or []
                        if promo_code:
                            payload["promo_code"] = promo_code
                        if selected:
                            payload["selected_checkout_offers"] = selected
                        # Keep attribution consistent across cart types.
                        mkt = _mkt_ctx()
                        if mkt.get("tid"):
                            payload["tid"] = mkt.get("tid")
                        if mkt.get("cmp"):
                            payload["cmp"] = mkt.get("cmp")
                        if mkt.get("intent"):
                            payload["intent"] = mkt.get("intent")
                        if mkt.get("src") and mkt.get("intent") != "lifecycle":
                            payload["src"] = mkt.get("src")
                        resp = get_crm().checkout_quote(payload, token=token, service_key=not token)
                        quote = resp.get("quote")
                        new_quote_id = _quote_id_from(resp, context="cart quote", critical=False)
                        # An anonymous quote prices the cart for display and
                        # nothing more: checkout needs a bearer, so keeping its id
                        # would only offer `/checkout/submit` a quote raised
                        # against no customer. Leaving it unset is also what makes
                        # signing in re-quote, here and at submit.
                        if new_quote_id is not None and token:
                            session["checkout_quote_id"] = new_quote_id
                            quote_id = new_quote_id
                        eligible_offers = _eligible_offers_from(resp)  # type: ignore[assignment]
                        # A bundle is priced by its locked price, not by upsell
                        # rules, so their absence says nothing about it.
                        if not eligible_offers and not bundle_slug:
                            app.logger.warning(
                                "cart quote returned no checkout offer rules; no upsell card can "
                                "carry a rule id, so the CRM will price every line at full. keys=%s",
                                sorted(resp.keys()) if isinstance(resp, dict) else type(resp).__name__,
                            )
                    else:
                        flash("Sign in to see your cart quote and checkout.", "warning")
                break

            except CRMError as e:
                action = _checkout_recovery_action(e)
                if action and _apply_checkout_recovery(action, e):
                    continue
                # A timeout, a 403 from the IP allowlist and a deliberate 400
                # all reach the customer as one sentence, and each needs a
                # different fix. Without the status and the body they are
                # indistinguishable from the outside, which is what turned the
                # GBP 5.00 mispricing into days of guessing.
                app.logger.warning(
                    "cart quote failed: status=%s bundle=%s body=%.500s",
                    getattr(e, "status_code", None),
                    session.get("checkout_bundle_slug") or "-",
                    e.payload if getattr(e, "payload", None) is not None else str(e),
                )
                flash(_friendly_crm_error(e), "error")
                break

        # Resolve human-friendly lottery names for cart display (avoid raw product codes like MSX).
        product_code_to_game_name: dict[str, str] = {}
        game_code_to_game_name: dict[str, str] = {}
        product_code_to_game_code: dict[str, str] = {}
        product_code_to_price_cents: dict[str, int] = {}
        fallback_currency = (os.environ.get("CRM_PRICE_FALLBACK_CURRENCY") or "EUR").strip().upper() or "EUR"
        try:
            product_code_to_price_cents.update(_get_cached_product_price_lookup())
        except Exception:
            pass
        try:
            games = store_games_cached()
            for g_ in games:
                if not isinstance(g_, dict):
                    continue
                game_name = str(g_.get("game_name") or "").strip()
                game_code = str(g_.get("game_code") or "").strip().lower()
                if game_name and game_code:
                    game_code_to_game_name[game_code] = game_name
                products = []
                for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
                    v = g_.get(k)
                    if isinstance(v, list):
                        products = [p for p in v if isinstance(p, dict)]
                        if products:
                            break
                    elif isinstance(v, dict):
                        products = [v]
                        break
                for p in products:
                    code = str(p.get("code") or p.get("product_code") or p.get("sku") or "").strip().upper()
                    if code and game_name:
                        product_code_to_game_name[code] = game_name
                    if code and game_code:
                        product_code_to_game_code[code] = game_code
                    if code:
                        # Display-currency price first; the base amount is in
                        # another currency and would misquote the item.
                        display_price = _product_price_cents(p, cart_currency)
                        if display_price:
                            product_code_to_price_cents[code] = display_price
                        else:
                            try:
                                raw_price = p.get("price_in_base_cents")
                                if raw_price is not None:
                                    pc = int(float(raw_price))
                                    if pc > 0:
                                        product_code_to_price_cents[code] = pc
                            except Exception:
                                pass
        except Exception:
            pass
        # Extra safety for common codes if catalog data is temporarily unavailable.
        product_code_to_game_name.setdefault("MSX", "Mega Millions")
        product_code_to_game_code.setdefault("MSX", "megamillions")

        for i, src in enumerate(cart_view_items):
            if not isinstance(src, dict):
                continue
            if src.get("game_name"):
                continue
            pc = str(src.get("product_code") or "").strip().upper()
            gc = str(src.get("game_code") or "").strip().lower()
            if pc and product_code_to_game_name.get(pc):
                src["game_name"] = product_code_to_game_name[pc]
            elif gc and game_code_to_game_name.get(gc):
                src["game_name"] = game_code_to_game_name[gc]
            # Best-effort per-item estimate used when quote item totals are unavailable.
            # A bundle is sold at one locked price for the whole run, so a unit
            # price is not a smaller version of it and there is no honest
            # per-line figure to show. Better a line with no price than the
            # catalog price for a single draw.
            if session.get("checkout_bundle_slug"):
                continue
            if not src.get("estimated_item_total_cents") and pc and product_code_to_price_cents.get(pc):
                try:
                    unit_cents = int(product_code_to_price_cents.get(pc) or 0)
                    if unit_cents > 0:
                        qty_lines = len(src.get("lines") or []) if isinstance(src.get("lines"), list) else int(src.get("quantity") or 1)
                        if qty_lines > 0:
                            src["estimated_item_total_cents"] = unit_cents * qty_lines
                except Exception:
                    pass

        # The game's own logo, so a cart card is recognisable at a glance rather
        # than being a name in a box. A separate pass because the loop above
        # skips any item that already knows its game name. `_find_local_logo`
        # returns None where we ship no artwork, and the card lays out without.
        for src in cart_view_items:
            if not isinstance(src, dict) or src.get("logo_url"):
                continue
            gc = str(src.get("game_code") or "").strip().lower()
            if not gc:
                gc = product_code_to_game_code.get(str(src.get("product_code") or "").strip().upper(), "")
            if not gc:
                continue
            try:
                src["logo_url"] = _find_local_logo(gc, str(src.get("game_name") or gc))
            except Exception:
                pass

        # Curated lottery upsells for cart page:
        # 1) Best odds, 2) Highest jackpot, 3) Next draw.
        lottery_upsells: list[dict[str, Any]] = []
        
        # Always try to generate upsells, even if cart is empty
        try:
            all_games = store_games_cached()
            games_by_code: dict[str, dict[str, Any]] = {}
            for g_ in all_games:
                if not isinstance(g_, dict):
                    continue
                c = str(g_.get("game_code") or "").strip().lower()
                if c:
                    games_by_code[c] = g_

            cart_game_codes: set[str] = set()
            for it in cart_view_items:
                gc = str(it.get("game_code") or "").strip().lower()
                if gc:
                    cart_game_codes.add(gc)
                    continue
                pc = str(it.get("product_code") or "").strip().upper()
                if pc and product_code_to_game_code.get(pc):
                    cart_game_codes.add(str(product_code_to_game_code.get(pc) or "").strip().lower())

            candidate_codes = [c for c in games_by_code.keys() if c and c not in cart_game_codes]
            _debug_print(f"DEBUG: cart_game_codes={cart_game_codes}, candidate_codes={candidate_codes[:5]}... (total: {len(candidate_codes)})", flush=True)

            # Odds are static approximations (smaller = better odds).
            odds_rank: dict[str, int] = {
                "sat-lotto-au": 8145060,
                "lotto-fr": 19068399,
                "lotto-ie": 10737418,
                "superenalotto": 622614630,
                "oz-lotto-au": 45724512,
                "euromillions": 139838160,
                "eurojackpot": 139838160,
                "powerball": 292201338,
                "megamillions": 302575350,
            }

            jackpots_cached = get_cache().get_cached_jackpots()
            jackpot_total_by_code: dict[str, float] = {}
            jackpot_currency_by_code: dict[str, str] = {}
            cutoff_dt_by_code: dict[str, datetime] = {}
            
            # Simple exchange rates (approximate, for comparison only)
            # These should ideally come from a live exchange rate API
            exchange_rates_to_eur: dict[str, float] = {
                "EUR": 1.0,
                "USD": 0.92,  # 1 USD ≈ 0.92 EUR (approximate)
                "GBP": 1.17,  # 1 GBP ≈ 1.17 EUR (approximate)
                "AUD": 0.61,  # 1 AUD ≈ 0.61 EUR (approximate)
                "CAD": 0.68,  # 1 CAD ≈ 0.68 EUR (approximate)
                "NZD": 0.56,  # 1 NZD ≈ 0.56 EUR (approximate)
            }
            
            for j in jackpots_cached:
                if not isinstance(j, dict):
                    continue
                code = str(j.get("game_code") or "").strip().lower()
                if not code:
                    continue
                try:
                    jt = j.get("jackpot_total")
                    currency = str(j.get("currency") or j.get("jackpot", {}).get("currency") or "EUR").strip().upper()
                    if jt is None and isinstance(j.get("jackpot"), dict):
                        jt = (j.get("jackpot") or {}).get("amount")
                        if not currency:
                            currency = str((j.get("jackpot") or {}).get("currency") or "EUR").strip().upper()
                    if jt is not None:
                        jackpot_total_by_code[code] = float(jt)
                        jackpot_currency_by_code[code] = currency
                except Exception:
                    pass
                cutoff_raw = str(j.get("cutoff_at_utc") or j.get("next_draw_utc") or "").strip()
                if cutoff_raw:
                    try:
                        cutoff_dt = datetime.fromisoformat(cutoff_raw.replace("Z", "+00:00"))
                        # Ensure timezone-aware
                        if cutoff_dt.tzinfo is None:
                            cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
                        cutoff_dt_by_code[code] = cutoff_dt
                    except Exception:
                        pass

            best_odds_code = None
            ranked = [c for c in candidate_codes if c in odds_rank]
            if ranked:
                best_odds_code = sorted(ranked, key=lambda c: odds_rank.get(c) or 10**12)[0]

            highest_jackpot_code = None
            with_jackpot = [c for c in candidate_codes if c in jackpot_total_by_code]
            if with_jackpot:
                # Convert all jackpots to EUR for fair comparison
                jackpot_eur_by_code: dict[str, float] = {}
                for c in with_jackpot:
                    amount = jackpot_total_by_code.get(c) or 0.0
                    currency = jackpot_currency_by_code.get(c) or "EUR"
                    rate = exchange_rates_to_eur.get(currency, 1.0)
                    jackpot_eur_by_code[c] = amount * rate
                    _debug_print(f"DEBUG: {c}: {amount:,.0f} {currency} = {jackpot_eur_by_code[c]:,.0f} EUR (rate: {rate})", flush=True)
                
                # Sort by EUR-equivalent value
                highest_jackpot_code = sorted(with_jackpot, key=lambda c: jackpot_eur_by_code.get(c) or 0.0, reverse=True)[0]
                _debug_print(f"DEBUG: Highest jackpot selected: {highest_jackpot_code} with {jackpot_eur_by_code.get(highest_jackpot_code, 0):,.0f} EUR equivalent", flush=True)

            next_draw_code = None
            now_utc = datetime.now(timezone.utc)
            # Ensure now_utc is timezone-aware for comparison
            if now_utc.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=timezone.utc)
            with_cutoff = []
            for c in candidate_codes:
                if c in cutoff_dt_by_code:
                    cutoff_dt = cutoff_dt_by_code[c]
                    # Ensure cutoff_dt is timezone-aware
                    if cutoff_dt.tzinfo is None:
                        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
                    if cutoff_dt > now_utc:
                        with_cutoff.append(c)
            if with_cutoff:
                next_draw_code = sorted(with_cutoff, key=lambda c: cutoff_dt_by_code[c])[0]

            # Build 3 specific upsell offers with product codes and quickpick lines
            def _build_upsell_offer(
                game_code: str | None,
                title: str,
                num_lines: int,
                reason: str
            ) -> dict[str, Any] | None:
                if not game_code:
                    _debug_print(f"DEBUG: _build_upsell_offer: no game_code for {title}", flush=True)
                    return None
                g_ = games_by_code.get(game_code) or {}
                if not g_:
                    _debug_print(f"DEBUG: _build_upsell_offer: game {game_code} not found in games_by_code", flush=True)
                    return None
                
                name = str(g_.get("game_name") or game_code_to_game_name.get(game_code) or game_code).strip()
                if game_code == "lotto-fr":
                    name = "French Lotto"
                if game_code == "lotto-ie":
                    name = "Irish Lotto"
                
                # Find the first "single" product for this game
                product_code = None
                line_schema = None
                products = []
                
                # Try multiple ways to get products from the game data (same as fallback)
                for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
                    v = g_.get(k)
                    if isinstance(v, list) and v:
                        products = [p for p in v if isinstance(p, dict)]
                        if products:
                            _debug_print(f"DEBUG: _build_upsell_offer: found {len(products)} products in '{k}' for {game_code}", flush=True)
                            break
                    elif isinstance(v, dict):
                        # Sometimes it's a single product dict, not a list
                        products = [v]
                        _debug_print(f"DEBUG: _build_upsell_offer: found single product in '{k}' for {game_code}", flush=True)
                        break
                
                # If still no products, try fetching from CRM directly
                if not products:
                    _debug_print(f"DEBUG: _build_upsell_offer: no products in game dict for {game_code}, trying CRM fetch...", flush=True)
                    try:
                        resp = get_crm().store_game(game_code)
                        game_direct = resp.get("game") if isinstance(resp, dict) else None
                        if isinstance(game_direct, dict):
                            for k in ("products", "default_products", "skus", "single_products", "syndicate_products"):
                                v = game_direct.get(k)
                                if isinstance(v, list) and v:
                                    products = [p for p in v if isinstance(p, dict)]
                                    if products:
                                        _debug_print(f"DEBUG: _build_upsell_offer: found {len(products)} products via CRM fetch in '{k}'", flush=True)
                                        break
                                elif isinstance(v, dict):
                                    products = [v]
                                    _debug_print(f"DEBUG: _build_upsell_offer: found single product via CRM in '{k}'", flush=True)
                                    break
                    except Exception as fetch_err:
                        _debug_print(f"DEBUG: _build_upsell_offer: CRM fetch failed: {fetch_err}", flush=True)
                
                if not products:
                    _debug_print(f"DEBUG: _build_upsell_offer: no products found for {game_code} after all attempts", flush=True)
                    return None
                
                for p in products:
                    ptype = str(p.get("product_type") or "").strip().lower()
                    if ptype == "single":
                        product_code = str(p.get("code") or p.get("product_code") or "").strip().upper()
                        line_schema = p.get("line_schema")
                        if product_code and line_schema:
                            break
                
                if not product_code:
                    _debug_print(f"DEBUG: _build_upsell_offer: no single product_code found for {game_code}", flush=True)
                    return None
                if not line_schema:
                    _debug_print(f"DEBUG: _build_upsell_offer: no line_schema found for {game_code} product {product_code}", flush=True)
                    return None
                
                # Generate quickpick lines
                quickpick_lines = _generate_quickpick_lines(line_schema, num_lines)
                if not quickpick_lines:
                    _debug_print(f"DEBUG: _build_upsell_offer: failed to generate quickpick lines for {game_code}", flush=True)
                    return None
                
                # Format description as "X Quickpick lines in [game name]"
                description = f"{num_lines} Quickpick line{'s' if num_lines != 1 else ''} in {name}"
                
                row: dict[str, Any] = {
                    "title": title,
                    "reason": description,
                    "game_code": game_code,
                    "game_name": name,
                    "product_code": product_code,
                    "lines": quickpick_lines,
                    "num_lines": num_lines,
                    # Kept so the card can be re-cut to the line count the CRM
                    # actually has an offer rule for (see the binding below).
                    "_line_schema": line_schema,
                }
                if game_code in jackpot_total_by_code:
                    row["jackpot_total"] = jackpot_total_by_code[game_code]
                if game_code in cutoff_dt_by_code:
                    row["next_draw_at"] = cutoff_dt_by_code[game_code].isoformat().replace("+00:00", "Z")
                _debug_print(f"DEBUG: _build_upsell_offer: SUCCESS for {game_code} -> {title}", flush=True)
                return row

            # Find worst odds in cart for comparison
            cart_worst_odds = None
            if cart_game_codes:
                cart_odds = [odds_rank.get(c) for c in cart_game_codes if c in odds_rank]
                if cart_odds:
                    cart_worst_odds = max(cart_odds)  # Worst odds = highest number
                    _debug_print(f"DEBUG: Cart worst odds: {cart_worst_odds}", flush=True)
            
            # 1. 3 lines quickpicked in the current highest jackpot
            _debug_print(f"DEBUG: highest_jackpot_code={highest_jackpot_code}, best_odds_code={best_odds_code}, next_draw_code={next_draw_code}", flush=True)
            _debug_print(f"DEBUG: jackpot_total_by_code has {len(jackpot_total_by_code)} games, cutoff_dt_by_code has {len(cutoff_dt_by_code)} games", flush=True)
            if highest_jackpot_code:
                offer = _build_upsell_offer(
                    highest_jackpot_code,
                    "3 Lines - Highest Jackpot",
                    3,
                    ""  # Reason will be auto-generated in _build_upsell_offer
                )
                if offer:
                    # Add jackpot display info (format as "344M")
                    if highest_jackpot_code in jackpot_total_by_code:
                        jp_amount = jackpot_total_by_code[highest_jackpot_code]
                        if jp_amount >= 1_000_000_000:
                            offer["jackpot_display"] = f"{int(jp_amount / 1_000_000_000)}B"
                        elif jp_amount >= 1_000_000:
                            offer["jackpot_display"] = f"{int(jp_amount / 1_000_000)}M"
                        elif jp_amount >= 1_000:
                            offer["jackpot_display"] = f"{int(jp_amount / 1_000)}K"
                        else:
                            offer["jackpot_display"] = f"{int(jp_amount):,}"
                    lottery_upsells.append(offer)
            
            # 2. 4 lines in the current best odds game
            if best_odds_code:
                offer = _build_upsell_offer(
                    best_odds_code,
                    "4 Lines - Best Odds",
                    4,
                    ""  # Reason will be auto-generated in _build_upsell_offer
                )
                if offer:
                    # Calculate % better odds compared to cart
                    if cart_worst_odds and best_odds_code in odds_rank:
                        best_odds_value = odds_rank[best_odds_code]
                        if best_odds_value < cart_worst_odds:
                            # Calculate improvement: (cart_odds - best_odds) / cart_odds * 100
                            improvement_pct = ((cart_worst_odds - best_odds_value) / cart_worst_odds) * 100
                            offer["odds_improvement_pct"] = int(improvement_pct)
                            _debug_print(f"DEBUG: Best odds improvement: {improvement_pct:.1f}% better than cart", flush=True)
                    lottery_upsells.append(offer)
            
            # 3. 3 lines in the current closest draw
            if next_draw_code:
                offer = _build_upsell_offer(
                    next_draw_code,
                    "3 Lines - Next Draw",
                    3,
                    ""  # Reason will be auto-generated in _build_upsell_offer
                )
                if offer:
                    # Add countdown timestamp
                    if next_draw_code in cutoff_dt_by_code:
                        offer["countdown_to"] = cutoff_dt_by_code[next_draw_code].isoformat().replace("+00:00", "Z")
                    lottery_upsells.append(offer)
            
            _debug_print(f"DEBUG: Generated {len(lottery_upsells)} lottery upsells", flush=True)
        except Exception as e:
            # Log error for debugging (remove in production)
            import traceback
            print(f"ERROR generating lottery_upsells: {e}", flush=True)
            traceback.print_exc()
            lottery_upsells = []
        
        # ALWAYS try fallback if no upsells (even if main logic "succeeded" with 0 results)
        _debug_print(f"DEBUG: Before fallback check: lottery_upsells length = {len(lottery_upsells)}")
        if len(lottery_upsells) == 0:
            _debug_print("*** DEBUG: No upsells generated, trying simple fallback... ***")
            try:
                fallback_games = store_games_cached()
                _debug_print(f"DEBUG: Fallback has {len(fallback_games)} games to try", flush=True)
                cart_games_set = {str(it.get("game_code") or "").strip().lower() for it in cart_view_items if isinstance(it, dict)}
                _debug_print(f"DEBUG: Cart has games: {cart_games_set}", flush=True)
                for g in fallback_games[:10]:  # Try first 10 games
                    if not isinstance(g, dict):
                        continue
                    gc = str(g.get("game_code") or "").strip().lower()
                    if not gc:
                        continue
                    if gc in cart_games_set:
                        _debug_print(f"DEBUG: Skipping {gc} (already in cart)", flush=True)
                        continue
                    _debug_print(f"DEBUG: Trying fallback for {gc}...", flush=True)
                    # Find product - try multiple keys and also fetch from CRM if needed
                    products = []
                    # Try all possible product keys
                    for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
                        v = g.get(k)
                        if isinstance(v, list) and v:
                            products = [p for p in v if isinstance(p, dict)]
                            if products:
                                _debug_print(f"DEBUG: Found {len(products)} products in '{k}' for {gc}", flush=True)
                                break
                        elif isinstance(v, dict):
                            products = [v]
                            _debug_print(f"DEBUG: Found single product in '{k}' for {gc}", flush=True)
                            break
                    # If still no products, try CRM fetch
                    if not products:
                        _debug_print(f"DEBUG: No products in cache for {gc}, fetching from CRM...", flush=True)
                        try:
                            resp = get_crm().store_game(gc)
                            game_direct = resp.get("game") if isinstance(resp, dict) else None
                            if isinstance(game_direct, dict):
                                for k in ("products", "default_products", "skus", "single_products", "syndicate_products"):
                                    v = game_direct.get(k)
                                    if isinstance(v, list) and v:
                                        products = [p for p in v if isinstance(p, dict)]
                                        if products:
                                            _debug_print(f"DEBUG: Found {len(products)} products via CRM for {gc}", flush=True)
                                            break
                                    elif isinstance(v, dict):
                                        products = [v]
                                        _debug_print(f"DEBUG: Found single product via CRM for {gc}", flush=True)
                                        break
                            # Also check if products are at top level of response
                            if not products and isinstance(resp, dict):
                                top_products = resp.get("products")
                                if isinstance(top_products, list):
                                    products = [p for p in top_products if isinstance(p, dict)]
                                    if products:
                                        _debug_print(f"DEBUG: Found {len(products)} products at response top level for {gc}", flush=True)
                        except Exception as fetch_err:
                            _debug_print(f"DEBUG: CRM fetch for {gc} failed: {fetch_err}", flush=True)
                            import traceback
                            traceback.print_exc()
                    
                    for p in products:
                        ptype = str(p.get("product_type") or "").strip().lower()
                        if ptype == "single":
                            pc = str(p.get("code") or p.get("product_code") or "").strip().upper()
                            ls = p.get("line_schema")
                            if pc and ls:
                                _debug_print(f"DEBUG: Generating quickpick for {gc} product {pc}...", flush=True)
                                qp_lines = _generate_quickpick_lines(ls, 3)
                                if qp_lines:
                                    # Determine title based on which offer this is
                                    offer_num = len(lottery_upsells)
                                    game_name = g.get("game_name") or gc
                                    if offer_num == 0:
                                        title = "3 Lines - Highest Jackpot"
                                        num_lines = 3
                                    elif offer_num == 1:
                                        title = "4 Lines - Best Odds"
                                        num_lines = 4
                                        # Update to 4 lines for best odds
                                        qp_lines = _generate_quickpick_lines(ls, 4)
                                        if not qp_lines:
                                            continue
                                    else:
                                        title = "3 Lines - Next Draw"
                                        num_lines = 3
                                    
                                    # Format description as "X Quickpick lines in [game name]"
                                    reason = f"{num_lines} Quickpick line{'s' if num_lines != 1 else ''} in {game_name}"
                                    
                                    lottery_upsells.append({
                                        "title": title,
                                        "reason": reason,
                                        "game_code": gc,
                                        "game_name": game_name,
                                        "product_code": pc,
                                        "lines": qp_lines,
                                        "num_lines": num_lines,
                                        "_line_schema": ls,
                                    })
                                    _debug_print(f"DEBUG: SUCCESS! Added upsell for {gc} with title '{title}'", flush=True)
                                    break
                    if len(lottery_upsells) >= 3:
                        _debug_print(f"DEBUG: Got 3 upsells, stopping fallback", flush=True)
                        break
                _debug_print(f"*** DEBUG: Fallback generated {len(lottery_upsells)} offers ***", flush=True)
            except Exception as fallback_err:
                _debug_print(f"*** DEBUG: Fallback failed: {fallback_err} ***", flush=True)
                import traceback
                traceback.print_exc()
        
        # Bind each locally-built upsell to the CRM rule that will actually discount it.
        # These cards are assembled here from the product catalogue, so nothing about
        # them is known to the CRM until we send back a rule id. A card with no matching
        # rule keeps its place but must not advertise a discount: the CRM would quote it
        # at full price and the order would be rejected for a price mismatch at submit.
        # Rules match on SKU AND line count — offered_quantity is a locked line count,
        # so a 4-line card cannot borrow a 3-line rule.
        def _offer_rule_field(offer: dict[str, Any], *names: str) -> Any:
            for name in names:
                value = offer.get(name)
                if value not in (None, "", 0):
                    return value
            return None

        _elig_by_key: dict[tuple[str, int], dict] = {}
        for _e in (eligible_offers if isinstance(eligible_offers, list) else []):
            if not isinstance(_e, dict):
                continue
            _code = str(_offer_rule_field(_e, "product_code", "offered_product_code", "sku") or "").strip().upper()
            try:
                _qty = int(_offer_rule_field(_e, "offered_quantity", "quantity", "lines") or 0)
            except Exception:
                _qty = 0
            _rid = _offer_rule_field(_e, "rule_id", "id", "offer_rule_id", "mm_offer_rule_id")
            if _rid in (None, ""):
                app.logger.warning("cart quote offer has no rule id, ignoring it: %s", _truncate_for_log(_e, 400))
                continue
            if _code and _qty > 0:
                _elig_by_key.setdefault((_code, _qty), {**_e, "rule_id": _rid})
        _elig_qty_by_code: dict[str, list[int]] = {}
        for (_code, _qty) in _elig_by_key:
            _elig_qty_by_code.setdefault(_code, []).append(_qty)
        for _u in lottery_upsells:
            if not isinstance(_u, dict):
                continue
            try:
                _n = int(_u.get("num_lines") or 0)
            except Exception:
                _n = 0
            _pc = str(_u.get("product_code") or "").strip().upper()
            # A rule is keyed to a locked line count, so a card offering a
            # different quantity can never be discounted. Re-cut the card to a
            # quantity the CRM has a rule for rather than offering one it will
            # quote at full price.
            if (_pc, _n) not in _elig_by_key and _elig_qty_by_code.get(_pc):
                _target = min(_elig_qty_by_code[_pc], key=lambda q: (abs(q - _n), q))
                _recut = _generate_quickpick_lines(_u.get("_line_schema"), _target)
                if _recut:
                    app.logger.info(
                        "cart upsell card %s re-cut from %s to %s lines to match a CRM offer rule",
                        _pc,
                        _n,
                        _target,
                    )
                    _u["lines"] = _recut
                    _u["num_lines"] = _target
                    _n = _target
                    _u["title"] = re.sub(r"^\d+\s+Lines?", f"{_target} Line{'s' if _target != 1 else ''}", str(_u.get("title") or ""))
                    _u["reason"] = re.sub(
                        r"^\d+\s+Quickpick lines?",
                        f"{_target} Quickpick line{'s' if _target != 1 else ''}",
                        str(_u.get("reason") or ""),
                    )
            _u.pop("_line_schema", None)
            _m = _elig_by_key.get((_pc, _n))
            _u["offer_rule_id"] = str(_m["rule_id"]).strip() if _m else None
            # The discount size is the CRM's to decide (its rules hold the
            # cart-value thresholds). A card with no CRM percent advertises none.
            _u["discount_percent"] = _offer_rule_field(_m or {}, "discount_percent", "percent_off", "discount_pct")
            app.logger.info(
                "cart upsell card %s x%s lines: rule_id=%s crm_discount_percent=%s",
                _u.get("product_code"),
                _n,
                _u.get("offer_rule_id"),
                _u.get("discount_percent"),
            )

        # ALWAYS clear eligible_offers if we have ANY lottery_upsells
        if lottery_upsells:
            eligible_offers = []
            _debug_print(f"DEBUG: SUCCESS - Showing {len(lottery_upsells)} lottery upsells, cleared eligible_offers", flush=True)
        else:
            _debug_print(f"DEBUG: FAILED - lottery_upsells is STILL empty, showing {len(eligible_offers) if isinstance(eligible_offers, list) else 0} eligible_offers instead", flush=True)

        # Precompute a cart total for discount tiers.
        # We derive this before discount logic so tiers reflect the current quote value.
        cart_total_for_discount_cents = cart_total_cents or 0
        if isinstance(quote, dict) and not cart_total_for_discount_cents:
            for k in (
                "subtotal_in_customer_cents",
                "subtotal_cents",
                "total_in_customer_cents",
                "total_cents",
                "subtotal_eur_cents",
                "total_eur_cents",
            ):
                v = quote.get(k)
                if v is not None:
                    try:
                        cart_total_for_discount_cents = int(float(v))
                        break
                    except Exception:
                        pass
            if not cart_total_for_discount_cents and isinstance(quote.get("items"), list):
                try:
                    cart_total_for_discount_cents = int(
                        sum(
                            int((it or {}).get("item_total_in_customer_cents") or 0)
                            for it in (quote.get("items") or [])
                            if isinstance(it, dict)
                        )
                    )
                except Exception:
                    cart_total_for_discount_cents = 0

        # Resolve CRM-authoritative discount fields from quote.
        discount_amount_cents = 0
        quote_discount_percent = None
        subtotal_for_discount_cents = None
        if isinstance(quote, dict):
            def _to_int_or_none(v: Any) -> int | None:
                try:
                    if v is None:
                        return None
                    return int(float(v))
                except Exception:
                    return None

            for k in ("subtotal_in_customer_cents", "subtotal_cents", "subtotal_eur_cents"):
                parsed = _to_int_or_none(quote.get(k))
                if parsed is not None and parsed > 0:
                    subtotal_for_discount_cents = parsed
                    break

            for k in ("discount_in_customer_cents", "discount_eur_cents", "discount_cents"):
                parsed = _to_int_or_none(quote.get(k))
                if parsed is not None and parsed > 0:
                    discount_amount_cents = parsed
                    break

            if discount_amount_cents <= 0 and subtotal_for_discount_cents:
                total_cents_for_diff = None
                for k in ("total_in_customer_cents", "total_cents", "total_eur_cents"):
                    parsed_total = _to_int_or_none(quote.get(k))
                    if parsed_total is not None and parsed_total >= 0:
                        total_cents_for_diff = parsed_total
                        break
                if total_cents_for_diff is not None and subtotal_for_discount_cents > total_cents_for_diff:
                    discount_amount_cents = subtotal_for_discount_cents - total_cents_for_diff

            raw_quote_pct = quote.get("discount_percent") or quote.get("discount_pct")
            if raw_quote_pct is not None:
                try:
                    quote_discount_percent = int(float(raw_quote_pct))
                except Exception:
                    quote_discount_percent = None

            if quote_discount_percent is None and discount_amount_cents > 0 and subtotal_for_discount_cents:
                try:
                    quote_discount_percent = int(round((float(discount_amount_cents) / float(subtotal_for_discount_cents)) * 100))
                except Exception:
                    quote_discount_percent = None

            # Also check quote.lines for per-line discounts when quote-level percent is missing.
            if quote_discount_percent is None and isinstance(quote.get("lines"), list):
                for line in quote.get("lines", []):
                    if isinstance(line, dict):
                        line_discount = line.get("discount_percent") or line.get("discount_pct")
                        if line_discount is not None:
                            try:
                                quote_discount_percent = int(float(line_discount))
                                _debug_print(f"DEBUG: Found discount_percent={quote_discount_percent}% from quote.lines", flush=True)
                                break
                            except Exception:
                                pass

        _debug_print(
            f"DEBUG: quote discount resolved amount_cents={discount_amount_cents}, percent={quote_discount_percent}",
            flush=True,
        )

        # Whether the CRM honoured the offer rules we asked it to apply. Without
        # this it is impossible to tell a missing CRM offer rule apart from the
        # website failing to request one.
        if isinstance(quote, dict):
            app.logger.info(
                "cart quote offers: sent_rule_ids=%s eligible_returned=%s "
                "quote_discount_cents=%s discount_breakdown=%s",
                session.get("checkout_selected_checkout_offers") or [],
                len(eligible_offers) if isinstance(eligible_offers, list) else 0,
                discount_amount_cents,
                quote.get("discount_breakdown") if quote.get("discount_breakdown") is not None else "absent",
            )

        # Compute offer-card discount from NON-upsell item value only.
        # Upsell items must never qualify or increase upsell tiers.
        base_items_subtotal_cents = 0
        quote_items_for_base = quote.get("items") if isinstance(quote, dict) and isinstance(quote.get("items"), list) else []
        if not isinstance(quote_items_for_base, list):
            quote_items_for_base = []
        for idx, it in enumerate(cart_view_items):
            if not isinstance(it, dict) or it.get("is_upsell"):
                continue
            qit = quote_items_for_base[idx] if idx < len(quote_items_for_base) and isinstance(quote_items_for_base[idx], dict) else {}
            base_item_cents = 0
            for k in (
                "item_total_in_customer_cents",
                "item_total_cents",
                "line_total_cents",
                "subtotal_in_customer_cents",
                "subtotal_cents",
                "total_in_customer_cents",
                "total_cents",
            ):
                try:
                    v = qit.get(k)
                    if v is not None:
                        base_item_cents = int(float(v))
                        if base_item_cents > 0:
                            break
                except Exception:
                    pass
            if base_item_cents <= 0:
                for k in ("item_total", "line_total", "subtotal", "total"):
                    try:
                        v = qit.get(k)
                        if v is not None:
                            base_item_cents = int(round(float(v) * 100.0))
                            if base_item_cents > 0:
                                break
                    except Exception:
                        pass
            if base_item_cents <= 0:
                try:
                    est = it.get("estimated_item_total_cents")
                    if est is not None:
                        base_item_cents = int(float(est))
                except Exception:
                    pass
            if base_item_cents > 0:
                base_items_subtotal_cents += base_item_cents

        # If base-item rollup couldn't be derived from quote items, keep qualifying
        # carts eligible by falling back to quote subtotal/order totals.
        if base_items_subtotal_cents <= 0 and has_base_items:
            base_items_subtotal_cents = int(
                subtotal_for_discount_cents
                or order_total_cents
                or cart_total_for_discount_cents
                or 0
            )

        # The discount size is the CRM's to decide: its offer rules hold the
        # cart-value thresholds and it re-prices the cart again at submit. A
        # percentage derived here would be a figure the CRM never agreed to, so
        # this stays None until the quote evidences a discount.
        offer_discount_percent = None
        offer_tier_base_cents = base_items_subtotal_cents

        # Qualification floor for upsell offers: 5 EUR+ in base (non-upsell) items.
        if offer_tier_base_cents < 500:
            lottery_upsells = []
            eligible_offers = []
            offer_discount_percent = None

        # Promo discount is independent from upsell discount.
        promo_discount_amount_cents = discount_amount_cents if promo_code_active else 0
        promo_discount_percent = quote_discount_percent if promo_code_active else None
        if promo_discount_percent is None and promo_discount_amount_cents > 0 and subtotal_for_discount_cents:
            try:
                promo_discount_percent = int(round((float(promo_discount_amount_cents) / float(subtotal_for_discount_cents)) * 100))
            except Exception:
                promo_discount_percent = None
        if promo_discount_percent is None and promo_discount_amount_cents > 0:
            promo_discount_percent = 10

        _debug_print(
            f"DEBUG: Final promo_discount_percent={promo_discount_percent}%, promo_discount_amount_cents={promo_discount_amount_cents}",
            flush=True,
        )

        # Derived totals for legacy-styled confirm-order UI.
        if isinstance(quote, dict):
            quote_currency = _normalized_currency_code(quote.get("currency"))
            if quote_currency:
                cart_currency = quote_currency
            wallet_currency = _normalized_currency_code(session_wallet.get("currency") if isinstance(session_wallet, dict) else "")
            if quote_currency and wallet_currency and quote_currency != wallet_currency:
                _debug_print(
                    f"DEBUG: Currency mismatch quote={quote_currency} wallet={wallet_currency}; using quote currency for cart display",
                    flush=True,
                )
            parsed_total_cents = None
            parsed_subtotal_cents = None

            for k in ("total_in_customer_cents", "total_cents", "total_eur_cents"):
                v = quote.get(k)
                if v is not None:
                    try:
                        parsed_total_cents = int(float(v))
                        break
                    except Exception:
                        pass

            for k in ("subtotal_in_customer_cents", "subtotal_cents", "subtotal_eur_cents"):
                v = quote.get(k)
                if v is not None:
                    try:
                        parsed_subtotal_cents = int(float(v))
                        break
                    except Exception:
                        pass

            # Compute both pre-discount and payable totals for the UI.
            if parsed_subtotal_cents is not None and parsed_subtotal_cents > 0:
                order_total_cents = parsed_subtotal_cents
            elif parsed_total_cents is not None and parsed_total_cents > 0:
                order_total_cents = parsed_total_cents

            if promo_discount_amount_cents > 0:
                if parsed_subtotal_cents is not None and parsed_subtotal_cents > 0:
                    cart_total_cents = max(0, parsed_subtotal_cents - promo_discount_amount_cents)
                elif parsed_total_cents is not None and parsed_total_cents > 0:
                    # Some quote variants only expose a total field that is pre-discount.
                    cart_total_cents = max(0, parsed_total_cents - promo_discount_amount_cents)
            elif parsed_total_cents is not None and parsed_total_cents > 0:
                cart_total_cents = parsed_total_cents
            elif parsed_subtotal_cents is not None and parsed_subtotal_cents > 0:
                cart_total_cents = parsed_subtotal_cents

            if not cart_total_cents and isinstance(quote.get("items"), list):
                try:
                    cart_total_cents = int(
                        sum(
                            int((it or {}).get("item_total_in_customer_cents") or 0)
                            for it in (quote.get("items") or [])
                            if isinstance(it, dict)
                        )
                    )
                except Exception:
                    cart_total_cents = 0

            if not order_total_cents:
                if parsed_subtotal_cents is not None:
                    order_total_cents = max(0, parsed_subtotal_cents)
                elif parsed_total_cents is not None:
                    if promo_discount_amount_cents > 0:
                        order_total_cents = max(0, parsed_total_cents)
                    else:
                        order_total_cents = max(0, parsed_total_cents)
                elif cart_total_cents:
                    order_total_cents = max(0, cart_total_cents + max(0, promo_discount_amount_cents))

            # Final fallback if CRM provided explicit zero values.
            if not cart_total_cents:
                if parsed_total_cents is not None:
                    cart_total_cents = max(0, parsed_total_cents)
                elif parsed_subtotal_cents is not None:
                    cart_total_cents = max(0, parsed_subtotal_cents - max(0, promo_discount_amount_cents))

            # The offer saving comes from the quote's own discount breakdown
            # below; the totals here already have it deducted, so nothing is
            # subtracted a second time.

            # V5-authoritative pricing path: prefer customer-currency totals + breakdown.
            # Fall back to base/legacy variants only when customer-currency fields are absent.
            try:
                def _to_int(v: Any) -> int | None:
                    try:
                        if v is None:
                            return None
                        return int(float(v))
                    except Exception:
                        return None

                contract_version = str(quote.get("contract_version") or "").strip()
                canonical_present = all(
                    quote.get(k) is not None
                    for k in ("base_currency", "subtotal_base_cents", "discount_base_cents", "total_base_cents")
                )
                customer_present = all(
                    quote.get(k) is not None
                    for k in ("currency", "subtotal_in_customer_cents", "discount_in_customer_cents", "total_in_customer_cents")
                )
                legacy_present = any(quote.get(k) is not None for k in ("subtotal_eur_cents", "discount_eur_cents", "total_eur_cents"))

                use_canonical = False
                use_legacy = False
                if canonical_present or customer_present:
                    # Fail safely if CRM returns an unknown contract version.
                    if contract_version and contract_version != "mm_offers_quote_v5":
                        session.pop("checkout_quote_id", None)
                    else:
                        use_canonical = True
                elif legacy_present:
                    use_legacy = True

                if use_canonical or use_legacy:
                    if use_canonical:
                        subtotal_auth = _to_int(quote.get("subtotal_in_customer_cents"))
                        if subtotal_auth is None:
                            subtotal_auth = _to_int(quote.get("subtotal_base_cents"))
                        if subtotal_auth is None:
                            subtotal_auth = _to_int(quote.get("subtotal_eur_cents"))
                        discount_auth = _to_int(quote.get("discount_in_customer_cents"))
                        if discount_auth is None:
                            discount_auth = _to_int(quote.get("discount_base_cents"))
                        if discount_auth is None:
                            discount_auth = _to_int(quote.get("discount_eur_cents"))
                        total_auth = _to_int(quote.get("total_in_customer_cents"))
                        if total_auth is None:
                            total_auth = _to_int(quote.get("total_base_cents"))
                        if total_auth is None:
                            total_auth = _to_int(quote.get("total_eur_cents"))
                        subtotal_auth = subtotal_auth or 0
                        discount_auth = discount_auth or 0
                        total_auth = total_auth or 0
                        currency_auth = _resolve_display_currency(
                            quote=quote,
                            wallet=session_wallet if isinstance(session_wallet, dict) else None,
                            customer=session_customer if isinstance(session_customer, dict) else None,
                            prefer_quote=True,
                        )
                    else:
                        subtotal_auth = _to_int(quote.get("subtotal_eur_cents")) or 0
                        discount_auth = _to_int(quote.get("discount_eur_cents")) or 0
                        total_auth = _to_int(quote.get("total_eur_cents")) or 0
                        currency_auth = _resolve_display_currency(
                            quote=quote,
                            wallet=session_wallet if isinstance(session_wallet, dict) else None,
                            customer=session_customer if isinstance(session_customer, dict) else None,
                            prefer_quote=True,
                        )

                    promo_auth = 0
                    offer_auth = 0
                    breakdown = quote.get("discount_breakdown") if isinstance(quote.get("discount_breakdown"), list) else []
                    for row in breakdown:
                        if not isinstance(row, dict):
                            continue
                        source_type = str(row.get("source_type") or "").strip().lower()
                        amount = None
                        if use_canonical:
                            amount = _to_int(row.get("amount_in_customer_cents"))
                        if amount is None and use_canonical:
                            amount = _to_int(row.get("amount_base_cents"))
                        if amount is None:
                            amount = _to_int(row.get("amount_eur_cents"))
                        if amount is None:
                            amount = _to_int(row.get("amount_cents"))
                        amt = max(0, amount or 0)
                        if source_type == "promo_code":
                            promo_auth += amt
                        elif source_type == "checkout_offer_rule":
                            offer_auth += amt

                    # Compatibility fallback for tenants not yet sending discount_breakdown.
                    if promo_code_active and promo_auth <= 0 and discount_auth > 0:
                        promo_auth = discount_auth

                    # Tenants that don't send discount_breakdown still state a
                    # total discount; whatever isn't the promo is offer-driven.
                    # Nothing is inferred beyond the quote's own numbers.
                    if offer_auth <= 0 and discount_auth > 0:
                        offer_auth = max(0, discount_auth - max(0, promo_auth))

                    # Keep promo line explicit only when promo is active.
                    if not promo_code_active:
                        promo_auth = 0

                    cart_currency = currency_auth
                    order_total_cents = max(0, subtotal_auth)
                    cart_total_cents = max(0, total_auth)
                    promo_discount_amount_cents = max(0, promo_auth)
                    offer_discount_amount_cents = max(0, offer_auth)
                    promo_discount_percent = int(round((promo_auth / subtotal_auth) * 100)) if subtotal_auth > 0 and promo_auth > 0 else None
                    if subtotal_auth > 0 and offer_auth > 0:
                        offer_discount_percent = int(round((offer_auth / subtotal_auth) * 100))
            except Exception:
                pass

            # Offer saving, straight from the quote. This also covers the legacy
            # lotto quote shape, which carries a discount breakdown without the
            # v5 canonical totals the block above requires.
            crm_offer_discount_cents = _quote_offer_discount_cents(quote)
            if crm_offer_discount_cents > 0:
                offer_discount_amount_cents = crm_offer_discount_cents
                if order_total_cents > 0:
                    offer_discount_percent = int(round((crm_offer_discount_cents / order_total_cents) * 100))

            # Per-item saving for the item rows, so each line shows the CRM's
            # own number rather than a share of a percentage applied here.
            item_discounts = _quote_item_discounts_cents(quote)
            for idx, view_item in enumerate(cart_view_items):
                if not isinstance(view_item, dict):
                    continue
                view_item["crm_discount_cents"] = item_discounts[idx] if idx < len(item_discounts) else 0

            applied_rule_ids = _quote_applied_offer_rule_ids(quote)
            app.logger.info(
                "cart quote applied offers: requested=%s applied_by_crm=%s "
                "offer_discount_cents=%s promo_discount_cents=%s",
                session.get("checkout_selected_checkout_offers") or [],
                applied_rule_ids,
                offer_discount_amount_cents,
                promo_discount_amount_cents,
            )
            if (session.get("checkout_selected_checkout_offers") or []) and not applied_rule_ids and offer_discount_amount_cents <= 0:
                app.logger.warning(
                    "cart quote: CRM applied none of the requested offer rules %s "
                    "(cart product/line counts may not match the rule)",
                    session.get("checkout_selected_checkout_offers"),
                )

        # Controlled customer-safe fallback:
        # if CRM quote payload is present but missing usable totals, derive a temporary
        # display total from cached daily product pricing so prices remain visible.
        crm_quote_has_totals = False
        if isinstance(quote, dict):
            for k in (
                "total_base_cents",
                "total_in_customer_cents",
                "total_eur_cents",
                "total_cents",
                "subtotal_base_cents",
                "subtotal_in_customer_cents",
                "subtotal_eur_cents",
                "subtotal_cents",
            ):
                if quote.get(k) is not None:
                    crm_quote_has_totals = True
                    break

        if items and (not crm_quote_has_totals) and (cart_total_cents <= 0):
            try:
                fallback_total = 0
                # With a bundle in play the only honest fallback is its locked
                # price. Summing unit prices answers a different question - one
                # draw at catalog rates - and that is the £5 a £22.50 offer was
                # showing. Preferred from the session so a failed quote does not
                # also mean a second CRM call, with a lookup behind it for a cart
                # that predates this being remembered.
                locked_bundle_cents = 0
                if session.get("checkout_bundle_slug"):
                    try:
                        locked_bundle_cents = max(0, int(session.get("checkout_bundle_locked_cents") or 0))
                    except Exception:
                        locked_bundle_cents = 0
                    if locked_bundle_cents <= 0:
                        looked_up, looked_up_currency = _bundle_locked_price(
                            _bundle_by_slug(str(session.get("checkout_bundle_slug")))[0]
                        )
                        locked_bundle_cents = max(0, int(looked_up or 0))
                        if locked_bundle_cents > 0:
                            session["checkout_bundle_locked_cents"] = locked_bundle_cents
                            session["checkout_bundle_currency"] = looked_up_currency

                if locked_bundle_cents > 0:
                    fallback_total = locked_bundle_cents
                    cart_currency = str(session.get("checkout_bundle_currency") or "").strip().upper() or cart_currency

                if not fallback_total:
                    for it in cart_view_items:
                        if not isinstance(it, dict):
                            continue
                        est = it.get("estimated_item_total_cents")
                        if est is not None:
                            try:
                                fallback_total += max(0, int(float(est)))
                                continue
                            except Exception:
                                pass
                        pc = str(it.get("product_code") or "").strip().upper()
                        unit = int(product_code_to_price_cents.get(pc) or 0)
                        if unit <= 0:
                            continue
                        qty_lines = len(it.get("lines") or []) if isinstance(it.get("lines"), list) else int(it.get("quantity") or 1)
                        fallback_total += max(0, unit * max(1, qty_lines))

                if fallback_total > 0:
                    cart_total_cents = fallback_total
                    order_total_cents = fallback_total
                    if not cart_currency:
                        cart_currency = _resolve_display_currency(
                            wallet=session_wallet if isinstance(session_wallet, dict) else None,
                            customer=session_customer if isinstance(session_customer, dict) else None,
                        ) or fallback_currency
                    try:
                        now_ts = int(time.time())
                        last_ts = int(session.get("pricing_fallback_warned_at") or 0)
                        if (now_ts - last_ts) > 3600:
                            flash(
                                "Live CRM pricing is temporarily unavailable. Showing cached fallback prices.",
                                "warning",
                            )
                            session["pricing_fallback_warned_at"] = now_ts
                    except Exception:
                        flash(
                            "Live CRM pricing is temporarily unavailable. Showing cached fallback prices.",
                            "warning",
                        )
                    _record_pricing_warning("crm_quote_missing_totals_using_product_price_fallback")
                else:
                    _record_pricing_warning("crm_quote_missing_totals_no_fallback_prices")
            except Exception:
                _record_pricing_warning("crm_quote_missing_totals_fallback_error")

        # A saving is only shown once the quote evidences it. Anything else would
        # be the website advertising a discount the CRM will not honour, and the
        # order is then refused at submit over the price.
        offer_discount_confirmed = offer_discount_amount_cents > 0
        quote_payable_cents = _quote_payable_cents(quote) if isinstance(quote, dict) else 0
        if quote_payable_cents > 0 and cart_total_cents < quote_payable_cents:
            app.logger.warning(
                "cart display total %s is below CRM quote payable %s "
                "(offer_discount=%s promo_discount=%s); using the CRM amount",
                cart_total_cents,
                quote_payable_cents,
                offer_discount_amount_cents,
                promo_discount_amount_cents,
            )
            cart_total_cents = quote_payable_cents
            offer_discount_amount_cents = 0
            offer_discount_confirmed = False
            if order_total_cents < cart_total_cents:
                order_total_cents = cart_total_cents

        # Legacy-like flow: if cart quote exceeds wallet, route straight to Add Funds.
        #
        # "They are short" and "we could not find out" are different answers and
        # only one of them justifies asking a customer for money. They were the
        # same answer here until this was split, and that is why A1007986 was
        # sent back to the payment page for the €25 already sitting in their
        # wallet.
        wallet_read_failed = False
        if items and quote and token:
            try:
                required_cents = _quote_payable_cents(quote if isinstance(quote, dict) else {})
                w_resp = get_crm().wallet(token)
                wallet = w_resp.get("wallet") if isinstance(w_resp, dict) else {}
                if isinstance(wallet, dict):
                    session["wallet"] = wallet

                # Two shortfalls, not one: what is missing if the winnings stay
                # where they are, and what is missing if the customer lets us
                # spend them. The CRM works both out against this exact quote,
                # including its reservations, so its answer wins over anything
                # derived here.
                funding = _cart_funding(quote, wallet, required_cents)
                short_without_wins = funding["shortfall_without_wins_cents"]
                short_with_wins = funding["shortfall_with_wins_cents"]
                balance_cents = funding["spendable_cents"]
                wins_cover_cents = funding["wins_cover_cents"]
                cart_funding = funding
                wallet_currency = str(wallet.get("currency") or "").strip().upper() if isinstance(wallet, dict) else ""
                # The code rather than the symbol, because every other amount
                # on this page is written "USD 5.80" and a notice that reads
                # "$5.80" next to them looks like it is about something else.
                money = (wallet_currency + " ") if wallet_currency else ""

                if short_without_wins > 0:
                    app.logger.info(
                        "cart deposits do not cover it: required=%s added=%s wins=%s "
                        "short_without_wins=%s short_with_wins=%s source=%s currency=%s intent=%s",
                        required_cents,
                        funding["spendable_cents"],
                        funding["available_wins_cents"],
                        short_without_wins,
                        short_with_wins,
                        funding["source"],
                        wallet_currency or "unknown",
                        _pending_checkout_get().get("intent_id") or "-",
                    )

                if short_without_wins > 0 and short_with_wins <= 0:
                    # Her case. Deposits are short, winnings close the gap, and
                    # the only thing standing between her and the order is
                    # permission we never asked for. Calling this "insufficient
                    # funds" is what sent A1009227 to add funds four times over
                    # a wallet holding nearly three times the cart.
                    wins_authorization_needed = True
                    session.pop("cart_force_purchase_topup", None)
                    # No pending top-up: nothing is owed until she declines.
                    _pending_checkout_set(required_cents=None, balance_cents=None, amount_cents=None)
                    flash(
                        f"Your added funds ({money}{funding['spendable_cents'] / 100:.2f}) do not cover "
                        f"this {money}{required_cents / 100:.2f} order. You can use "
                        f"{money}{wins_cover_cents / 100:.2f} of your "
                        f"{money}{funding['available_wins_cents'] / 100:.2f} winnings for the remainder, "
                        "or add funds instead.",
                        "warning",
                    )
                    topup_amount_cents = max(500, short_without_wins)
                    topup_cta_url = url_for(
                        "wallet_add_funds",
                        next=url_for("checkout_after_topup"),
                        amount_cents=str(topup_amount_cents),
                        required_cents=str(required_cents),
                        balance_cents=str(balance_cents),
                        edit_order_url=_resolve_edit_order_url(cart_edit_order_url),
                    )
                elif short_without_wins > 0:
                    # Genuinely short: everything they hold, winnings included,
                    # still does not reach the total. This is the only case
                    # that gets to say insufficient funds.
                    #
                    # The amount asked for is the gap with the winnings left
                    # alone, because preserving them is the default and we are
                    # not going to bank on permission the customer has not
                    # given.
                    needed_cents = max(500, short_without_wins)
                    session.pop("cart_force_purchase_topup", None)
                    _pending_checkout_set(
                        source="cart",
                        next_url=url_for("checkout_after_topup"),
                        required_cents=required_cents,
                        balance_cents=balance_cents,
                        amount_cents=needed_cents,
                        edit_order_url=_resolve_edit_order_url(cart_edit_order_url),
                    )
                    if funding["available_wins_cents"] > 0:
                        flash(
                            f"This order needs {money}{required_cents / 100:.2f}. Your added funds "
                            f"({money}{funding['spendable_cents'] / 100:.2f}) and winnings "
                            f"({money}{funding['available_wins_cents'] / 100:.2f}) together are "
                            f"{money}{short_with_wins / 100:.2f} short. "
                            "Use the payment button below to add funds and continue checkout.",
                            "warning",
                        )
                    else:
                        flash(
                            f"This order needs {money}{required_cents / 100:.2f} and your added funds are "
                            f"{money}{funding['spendable_cents'] / 100:.2f}, "
                            f"{money}{short_without_wins / 100:.2f} short. "
                            "Use the payment button below to add funds and continue checkout.",
                            "warning",
                        )
                    topup_needed = True
                    topup_amount_cents = needed_cents
                    topup_cta_url = url_for(
                        "wallet_add_funds",
                        next=url_for("checkout_after_topup"),
                        amount_cents=str(needed_cents),
                        required_cents=str(required_cents),
                        balance_cents=str(balance_cents),
                        edit_order_url=_resolve_edit_order_url(cart_edit_order_url),
                    )
                else:
                    # Deposits cover it. Winnings stay where they are.
                    _wins_prompt_clear()
                    _pending_checkout_set(required_cents=None, balance_cents=None, amount_cents=None)
            except Exception as e:  # noqa: BLE001 - the cart stays usable either way
                # Not silent. A cart that cannot read a balance and a cart that
                # read one and found it short used to leave the same trace,
                # which is none, and they need opposite responses.
                wallet_read_failed = True
                app.logger.warning(
                    "cart could not read the wallet balance, so it is not asking for money: %s: %s",
                    type(e).__name__,
                    e,
                )

        # Only when we have no live answer at all. Asking again on figures we
        # worked out before the customer paid is how money leaves an account
        # twice; if they really are short, checkout says so at submit and
        # routes them properly.
        if not topup_needed and not wallet_read_failed and not wins_authorization_needed:
            pending_ctx = _pending_checkout_get()
            topup_needed = bool(pending_ctx.get("amount_cents")) and str(pending_ctx.get("next_url") or "") == url_for("checkout_after_topup")
            topup_amount_cents = int(pending_ctx.get("amount_cents") or 0) if topup_needed else 0
            if topup_needed:
                topup_cta_url = url_for(
                    "wallet_add_funds",
                    next=url_for("checkout_after_topup"),
                    amount_cents=str(max(0, topup_amount_cents)),
                    required_cents=str(int(pending_ctx.get("required_cents") or 0)),
                    balance_cents=str(int(pending_ctx.get("balance_cents") or 0)),
                    edit_order_url=_resolve_edit_order_url(cart_edit_order_url),
                )

        # An offer is a promise about a price, and the CRM is the only thing
        # that can confirm it. When the quote does not arrive we can still show
        # the locked price the customer was emailed, but we must not take money
        # against a total the website assembled by itself: the submit re-quotes,
        # so a cart that checks out here is a payment taken for an order the
        # CRM may then refuse over the price. Ordinary carts are unaffected -
        # they have no locked price to be wrong about.
        pricing_unconfirmed = bool(session.get("checkout_bundle_slug")) and not crm_quote_has_totals
        if pricing_unconfirmed:
            app.logger.warning(
                "cart is showing bundle %s at its locked price with no CRM quote; checkout is closed",
                session.get("checkout_bundle_slug"),
            )
        return render_template(
            "cart.html",
            items=cart_view_items,
            quote=quote,
            quote_id=quote_id,
            pricing_unconfirmed=pricing_unconfirmed,
            cart_total_cents=cart_total_cents,
            order_total_cents=order_total_cents,
            cart_currency=cart_currency,
            cart_edit_order_url=cart_edit_order_url,
            lottery_upsells=lottery_upsells,
            eligible_offers=eligible_offers if isinstance(eligible_offers, list) else [],
            discount_percent=promo_discount_percent,
            promo_discount_percent=promo_discount_percent,
            offer_discount_percent=offer_discount_percent,
            discount_amount_cents=promo_discount_amount_cents,
            upsell_discount_amount_cents=offer_discount_amount_cents,
            offer_discount_confirmed=offer_discount_confirmed,
            promo_code=_checkout_promo_get(),
            bundle_slug=session.get("checkout_bundle_slug"),
            selected_offers=session.get("checkout_selected_checkout_offers") or [],
            is_mm_cart=is_mm_cart(items),
            cart_line_schemas=_cart_line_schemas(cart_view_items),
            has_saved_purchase_cart=bool(_last_purchase_cart_items()),
            saved_purchase_cart_count=len(_last_purchase_cart_items()),
            topup_needed=topup_needed,
            topup_cta_url=topup_cta_url,
            topup_amount_cents=topup_amount_cents,
            wins_authorization_needed=wins_authorization_needed,
            wins_cover_cents=wins_cover_cents,
            cart_funding=cart_funding,
            open_item_idx=open_item_idx,
        )

    @app.post("/cart/apply-promo")
    def cart_apply_promo():
        items = session.get("cart_items", [])
        if not isinstance(items, list) or not items:
            flash("Add items to your cart before applying a promo code.", "warning")
            return redirect(url_for("cart"))

        promo = (request.form.get("promo_code") or "").strip() or None
        if promo:
            _checkout_promo_set(promo)
            flash("Promo code applied.", "success")
        else:
            _checkout_promo_set(None)
            flash("Promo code cleared.", "success")
        session.pop("checkout_quote_id", None)
        return redirect(url_for("cart"))

    @app.post("/cart/toggle-offer")
    def cart_toggle_offer():
        offer_id = (request.form.get("offer_id") or "").strip()
        if not offer_id:
            abort(400, "Missing offer_id")
        selected = session.get("checkout_selected_checkout_offers") or []
        if not isinstance(selected, list):
            selected = []
        if offer_id in selected:
            selected = [x for x in selected if x != offer_id]
        else:
            selected.append(offer_id)
        session["checkout_selected_checkout_offers"] = selected
        session.pop("checkout_quote_id", None)
        return redirect(url_for("cart"))

    @app.post("/cart/clear")
    def cart_clear():
        session.pop("cart_items", None)
        session.pop("cart_edit_order_url", None)
        session.pop("cart_last_game_code", None)
        _pending_checkout_clear()
        session.pop("checkout_quote_id", None)
        _checkout_promo_set(None)
        session.pop("checkout_bundle_slug", None)
        session.pop("checkout_bundle_locked_cents", None)
        session.pop("checkout_bundle_currency", None)
        session.pop("checkout_selected_checkout_offers", None)
        flash("Cart cleared.", "success")
        return redirect(url_for("cart"))

    @app.post("/cart/reuse-last-purchase")
    def cart_reuse_last_purchase():
        saved_items = _last_purchase_cart_items()
        if not saved_items:
            flash("No previous purchase is available to reuse yet.", "warning")
            return redirect(url_for("cart"))
        session["cart_items"] = saved_items
        session.pop("checkout_quote_id", None)
        first_game_code = ""
        for it in saved_items:
            if isinstance(it, dict):
                first_game_code = str(it.get("game_code") or "").strip()
                if first_game_code:
                    break
        if first_game_code:
            session["cart_last_game_code"] = first_game_code
            session["cart_edit_order_url"] = url_for("play", game_code=first_game_code)
        flash("Your previous purchase has been loaded into the cart.", "success")
        return redirect(url_for("cart"))

    @app.post("/cart/remove-item")
    def cart_remove_item():
        raw_idx = (request.form.get("item_idx") or "").strip()
        try:
            idx = int(raw_idx)
        except Exception:
            idx = -1
        items = session.get("cart_items", [])
        if not isinstance(items, list):
            items = []
        if 0 <= idx < len(items):
            items.pop(idx)
            session["cart_items"] = items
            # Drops the offer selection too if that item was the offered one.
            _sync_selected_offers_from_cart()
            if not items:
                _pending_checkout_clear()
            flash("Item removed from cart.", "success")
        else:
            flash("Could not remove that item.", "warning")
        return redirect(url_for("cart"))

    @app.post("/cart/remove-line")
    def cart_remove_line():
        raw_item_idx = (request.form.get("item_idx") or "").strip()
        raw_line_idx = (request.form.get("line_idx") or "").strip()
        try:
            item_idx = int(raw_item_idx)
            line_idx = int(raw_line_idx)
        except Exception:
            item_idx = -1
            line_idx = -1
        items = session.get("cart_items", [])
        if not isinstance(items, list):
            items = []
        if not (0 <= item_idx < len(items)):
            flash("Could not remove that line.", "warning")
            return redirect(url_for("cart"))
        item = items[item_idx] if isinstance(items[item_idx], dict) else {}
        lines = item.get("lines") if isinstance(item, dict) else None
        if not isinstance(lines, list) or not (0 <= line_idx < len(lines)):
            flash("Could not remove that line.", "warning")
            return redirect(url_for("cart"))
        lines.pop(line_idx)
        if lines:
            item["lines"] = lines
            items[item_idx] = item
        else:
            # If no lines left, remove the whole ticket item.
            items.pop(item_idx)
        session["cart_items"] = items
        session.pop("checkout_quote_id", None)
        if not items:
            _pending_checkout_clear()
        flash("Line removed from cart.", "success")
        if items and 0 <= item_idx < len(items):
            return redirect(url_for("cart", open_item_idx=item_idx))
        return redirect(url_for("cart"))

    @app.post("/cart/edit-line")
    def cart_edit_line():
        raw_item_idx = (request.form.get("item_idx") or "").strip()
        raw_line_idx = (request.form.get("line_idx") or "").strip()
        try:
            item_idx = int(raw_item_idx)
            line_idx = int(raw_line_idx)
        except Exception:
            item_idx = -1
            line_idx = -1

        items = session.get("cart_items", [])
        if not isinstance(items, list) or not (0 <= item_idx < len(items)):
            flash("Could not edit that line.", "warning")
            return redirect(url_for("cart"))
        item = items[item_idx] if isinstance(items[item_idx], dict) else {}
        lines = item.get("lines") if isinstance(item, dict) else None
        if not isinstance(lines, list) or not (0 <= line_idx < len(lines)):
            flash("Could not edit that line.", "warning")
            return redirect(url_for("cart", open_item_idx=item_idx))
        line = lines[line_idx] if isinstance(lines[line_idx], dict) else None
        if not isinstance(line, dict):
            flash("Could not edit that line.", "warning")
            return redirect(url_for("cart", open_item_idx=item_idx))

        game_code = _safe_game_code(item.get("game_code")) if isinstance(item, dict) else ""
        product_code = str(item.get("product_code") or "").strip().upper() if isinstance(item, dict) else ""
        if not game_code and product_code:
            try:
                for g_ in store_games_cached():
                    if not isinstance(g_, dict):
                        continue
                    gc = _safe_game_code(g_.get("game_code"))
                    if not gc:
                        continue
                    products = []
                    for k in ("products", "default_products", "skus", "single_products", "syndicate_products", "product", "default_product"):
                        v = g_.get(k)
                        if isinstance(v, list):
                            products = [p for p in v if isinstance(p, dict)]
                            if products:
                                break
                        elif isinstance(v, dict):
                            products = [v]
                            break
                    if any(str(p.get("code") or p.get("product_code") or p.get("sku") or "").strip().upper() == product_code for p in products):
                        game_code = gc
                        break
            except Exception:
                game_code = game_code or ""
        if not game_code:
            flash("Could not determine the game for this line.", "warning")
            return redirect(url_for("cart", open_item_idx=item_idx))

        session["pending_line_edit"] = {
            "item_idx": item_idx,
            "line_idx": line_idx,
            "product_code": product_code,
            "line": line,
            "game_code": game_code,
        }
        return redirect(url_for("play", game_code=game_code))

    @app.post("/cart/update-line")
    def cart_update_line():
        raw_item_idx = (request.form.get("item_idx") or "").strip()
        raw_line_idx = (request.form.get("line_idx") or "").strip()
        try:
            item_idx = int(raw_item_idx)
            line_idx = int(raw_line_idx)
        except Exception:
            item_idx = -1
            line_idx = -1

        items = session.get("cart_items", [])
        if not isinstance(items, list):
            items = []
        if not (0 <= item_idx < len(items)):
            flash("Could not update that line.", "warning")
            return redirect(url_for("cart"))
        item = items[item_idx] if isinstance(items[item_idx], dict) else {}
        lines = item.get("lines") if isinstance(item, dict) else None
        if not isinstance(lines, list) or not (0 <= line_idx < len(lines)):
            flash("Could not update that line.", "warning")
            return redirect(url_for("cart", open_item_idx=item_idx))
        line = lines[line_idx] if isinstance(lines[line_idx], dict) else {}
        if not isinstance(line, dict):
            flash("Could not update that line.", "warning")
            return redirect(url_for("cart", open_item_idx=item_idx))

        def _parse_numeric_tokens(raw: str) -> list[int]:
            tokens = re.split(r"[\s,]+", str(raw or "").strip())
            out: list[int] = []
            for t in tokens:
                if not t:
                    continue
                if not re.fullmatch(r"\d+", t):
                    raise ValueError("Only numbers separated by commas are allowed.")
                out.append(int(t))
            return out

        updated_line = dict(line)
        try:
            for key, old_val in line.items():
                field_name = f"field__{key}"
                if field_name not in request.form:
                    continue
                raw_val = (request.form.get(field_name) or "").strip()
                nums = _parse_numeric_tokens(raw_val)
                if not nums:
                    raise ValueError("Each number field must include at least one number.")
                if isinstance(old_val, list):
                    updated_line[key] = nums
                elif isinstance(old_val, (int, float)):
                    updated_line[key] = int(nums[0])
                elif isinstance(old_val, str):
                    if "," in old_val:
                        updated_line[key] = ",".join(str(n) for n in nums)
                    else:
                        updated_line[key] = str(nums[0])
                else:
                    updated_line[key] = ",".join(str(n) for n in nums)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("cart", open_item_idx=item_idx))

        lines[line_idx] = updated_line
        item["lines"] = lines
        items[item_idx] = item
        session["cart_items"] = items
        session.pop("checkout_quote_id", None)
        flash("Line updated.", "success")
        return redirect(url_for("cart", open_item_idx=item_idx))

    @app.post("/checkout")
    def checkout_submit():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("cart")))
        items = session.get("cart_items", [])
        if not items:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("cart"))

        # Winnings are only ever spent because the customer pressed the button
        # that says so. It is read from this request and never remembered: an
        # authorisation that outlived the order it was given for would spend
        # winnings on a later cart the customer never agreed to.
        use_wins = str(request.form.get("use_wins") or "").strip() in {"1", "true", "on", "yes"}
        if use_wins:
            _wins_prompt_clear()

        # Emit checkout_started when the customer explicitly enters checkout.
        checkout_started_id = session.get("mkt_checkout_started_uuid")
        if not isinstance(checkout_started_id, str) or not checkout_started_id:
            checkout_started_id = uuid.uuid4().hex
            session["mkt_checkout_started_uuid"] = checkout_started_id
        ctx = _mkt_ctx()
        emit_marketing_event(
            "checkout_started",
            stable_key=checkout_started_id,
            metadata={"items_count": len(items), "source": "checkout_submit"},
        )

        # Stable per-attempt key so retries don't duplicate events.
        attempt_id = session.get("mkt_checkout_attempt_id")
        if not attempt_id:
            attempt_id = uuid.uuid4().hex
            session["mkt_checkout_attempt_id"] = attempt_id
        emit_marketing_event(
            "submit_attempt",
            stable_key=f"{ctx.get('tid') or attempt_id}:submit",
            metadata={"items_count": len(items)},
        )

        def _attach_marketing(payload: dict[str, Any]) -> dict[str, Any]:
            if ctx.get("tid"):
                payload["tid"] = ctx.get("tid")
            if ctx.get("cmp"):
                payload["cmp"] = ctx.get("cmp")
            if ctx.get("intent"):
                payload["intent"] = ctx.get("intent")
            # Lifecycle touches must not overwrite acquisition attribution.
            if ctx.get("src") and ctx.get("intent") != "lifecycle":
                payload["src"] = ctx.get("src")
            return payload

        def _is_mm_items() -> bool:
            return any(isinstance(x, dict) and ("product_id" in x) for x in items)

        def _fresh_quote_id() -> Any:
            """Re-price the current cart and store the new quote id."""
            if _is_mm_items():
                payload: dict[str, Any] = {
                    "items": [
                        {
                            "product_id": int(i.get("product_id")),
                            "quantity": int(i.get("quantity") or 1),
                            "config_json": _as_config_object(i.get("config_json")),
                        }
                        for i in items
                        if isinstance(i, dict) and i.get("product_id") is not None
                    ],
                }
                bundle_slug = session.get("checkout_bundle_slug")
                if bundle_slug:
                    payload["bundle_slug"] = bundle_slug
            else:
                payload = {"items": _crm_cart_items(items)}
                # A bundle bought from an offer page is a cart of ordinary
                # lottery SKUs, so it re-prices down this branch and needs the
                # slug too or the locked price is lost at checkout.
                bundle_slug = session.get("checkout_bundle_slug")
                if bundle_slug:
                    payload["bundle_slug"] = bundle_slug
            promo_code = _checkout_promo_get()
            selected = session.get("checkout_selected_checkout_offers") or []
            if promo_code:
                payload["promo_code"] = promo_code
            if selected:
                payload["selected_checkout_offers"] = selected
            _attach_marketing(payload)
            q = (
                get_crm().checkout_quote(payload, token=token, service_key=True)
                if _is_mm_items()
                else get_crm().checkout_quote(payload, token=token)
            )
            new_id = _quote_id_from(q, context="checkout quote")
            if new_id is None:
                return None
            session["checkout_quote_id"] = new_id
            return new_id

        def _direct_checkout_payload() -> dict[str, Any]:
            # The customer's authorisation, carried onto the fallback path so a
            # choice they made does not evaporate when the quote path fails.
            #
            # This used to be hardcoded true, which spent winnings on every
            # order that came through here without anyone being asked. The CRM
            # preserves winnings by default precisely so that cannot happen by
            # accident, and sending the flag unconditionally overrode that.
            payload: dict[str, Any] = {"items": _crm_cart_items(items)}
            if use_wins:
                payload["use_wins"] = True
            promo_code = _checkout_promo_get()
            selected = session.get("checkout_selected_checkout_offers") or []
            bundle_slug = session.get("checkout_bundle_slug")
            if promo_code:
                payload["promo_code"] = promo_code
            if selected:
                payload["selected_checkout_offers"] = selected
            if bundle_slug:
                payload["bundle_slug"] = bundle_slug
            return _attach_marketing(payload)

        def _discount_at_stake() -> list[str]:
            """What this cart loses if the order is priced without a quote."""
            at_stake: list[str] = []
            selected = session.get("checkout_selected_checkout_offers") or []
            if selected:
                at_stake.append(f"offer rules {selected}")
            if _checkout_promo_get():
                at_stake.append("promo code")
            if session.get("checkout_bundle_slug"):
                at_stake.append("bundle")
            return at_stake

        try:
            quote_id = session.get("checkout_quote_id")
            if quote_id is None:
                quote_id = _fresh_quote_id()

            resp = None
            # Why the quote path produced no order, for the log and for deciding
            # whether the older endpoint may be used at all.
            quote_path_failure: str | None = None
            if quote_id is None:
                quote_path_failure = "/checkout/quote returned no quote id"
            else:
                # The CRM re-prices the stored quote and refuses it if the cart
                # moved on (409) or the quote expired (400). Both are recoverable
                # by re-quoting, so recover once instead of dead-ending the
                # customer on a generic failure.
                for attempt in range(2):
                    try:
                        resp = get_crm().checkout_submit(token, quote_id=quote_id, use_wins=use_wins)
                        break
                    except CRMError as e:
                        if e.status_code == 402:
                            raise
                        action = _checkout_recovery_action(e)
                        if action and attempt == 0 and _apply_checkout_recovery(action, e):
                            quote_id = _fresh_quote_id()
                            if quote_id is not None:
                                continue
                            quote_path_failure = "re-quote after recovery returned no quote id"
                            break
                        quote_path_failure = f"/checkout/submit refused quote {quote_id}: {e}"
                        break
                    except Exception as e:  # noqa: BLE001
                        quote_path_failure = f"/checkout/submit call failed for quote {quote_id}: {e!r}"
                        break

            if resp is None:
                # `/api/v1/checkout` prices the cart on its own terms. Using it
                # after a quote failure turns an offer into a full-price sale that
                # looks successful from both ends, which is how undiscounted
                # orders went unnoticed. It is now a logged, last-resort path and
                # is refused outright when there is a discount to lose.
                at_stake = _discount_at_stake()
                fallback_mode = (os.environ.get("CHECKOUT_DIRECT_FALLBACK") or "auto").strip().lower()
                app.logger.error(
                    "checkout could not use the quote path (%s); discount at stake: %s; fallback=%s",
                    quote_path_failure or "unknown",
                    "; ".join(at_stake) or "none",
                    fallback_mode,
                )
                allow_fallback = fallback_mode != "off" and (not at_stake or fallback_mode == "on")
                if not allow_fallback:
                    emit_marketing_event(
                        "purchase_failed",
                        stable_key=f"{ctx.get('tid') or attempt_id}:quote_unavailable",
                        metadata={"stage": "quote", "reason": "quote_unavailable"},
                    )
                    session.pop("checkout_quote_id", None)
                    session.pop("mkt_checkout_attempt_id", None)
                    session.pop("mkt_checkout_started_uuid", None)
                    flash(
                        (
                            "We couldn't confirm your discounted total just now, so nothing "
                            "was charged and your cart is unchanged. Please try again in a "
                            "moment."
                        )
                        if at_stake
                        else (
                            "We couldn't confirm your total just now, so nothing was charged "
                            "and your cart is unchanged. Please try again in a moment."
                        ),
                        "error",
                    )
                    return redirect(url_for("cart"))
                resp = get_crm().checkout(token, _direct_checkout_payload())
                app.logger.error(
                    "checkout used the /api/v1/checkout fallback; order=%s. This path does not "
                    "carry a quote, so the CRM priced the cart itself.",
                    resp.get("order_id") if isinstance(resp, dict) else "unknown",
                )
        except CRMError as e:
            # Clear attempt id so the next attempt uses a new id.
            session.pop("mkt_checkout_attempt_id", None)
            session.pop("mkt_checkout_started_uuid", None)
            if e.status_code == 402 and isinstance(e.payload, dict):
                emit_marketing_event(
                    "purchase_failed",
                    stable_key=f"{ctx.get('tid') or attempt_id}:insufficient_wallet",
                    metadata={"stage": "payment", "reason": "insufficient_wallet"},
                )
                # `balance_cents` here is the total, deposits and winnings
                # together, exactly as `GET /wallet` reports it. Subtracting a
                # cart from it gives a shortfall for money checkout will not
                # spend without being asked, which is how a customer holding
                # nearly three times the cart was told to add funds.
                total_bal = int(e.payload.get("balance_cents") or 0)
                added_bal = int(e.payload.get("added_funds_balance_cents") or 0)
                wins_bal = int(e.payload.get("wins_balance_cents") or 0)
                sent_use_wins = bool(e.payload.get("use_wins"))
                req = int(e.payload.get("required_cents") or 0)
                cur = str(e.payload.get("currency") or "").strip().upper()
                app.logger.warning(
                    "checkout 402: required=%s added=%s wins=%s total=%s use_wins=%s shortfall=%s "
                    "currency=%s (session wallet total=%s)",
                    req,
                    added_bal,
                    wins_bal,
                    total_bal,
                    sent_use_wins,
                    e.payload.get("shortfall_cents"),
                    cur or "unknown",
                    (session.get("wallet") or {}).get("balance_cents") if isinstance(session.get("wallet"), dict) else None,
                )

                sym = _currency_symbol(cur) or (cur + " " if cur else "")
                if not sent_use_wins and wins_bal > 0 and (added_bal + wins_bal) >= req > 0:
                    # The CRM is not saying she is broke. It is saying it will
                    # not touch winnings on its own, and it is right not to.
                    # This is a question, and the answer is hers.
                    _wins_prompt_set(required_cents=req, added_cents=added_bal, wins_cents=wins_bal)
                    _pending_checkout_set(required_cents=None, balance_cents=None, amount_cents=None)
                    app.logger.info(
                        "checkout 402 is recoverable by authorising winnings: added=%s wins=%s required=%s",
                        added_bal,
                        wins_bal,
                        req,
                    )
                    flash(
                        f"Your added funds ({sym}{added_bal / 100:.2f}) do not cover this "
                        f"{sym}{req / 100:.2f} order. You can use "
                        f"{sym}{max(0, req - added_bal) / 100:.2f} of your "
                        f"{sym}{wins_bal / 100:.2f} winnings for the remainder, or add funds instead.",
                        "warning",
                    )
                    return redirect(url_for("cart"))

                # Genuinely short. The gap is measured against deposits, since
                # that is what a default checkout spends, and the winnings are
                # left alone unless the customer says otherwise.
                bal = added_bal if (added_bal or wins_bal) else total_bal
                needed = max(0, req - bal)
                needed = max(500, needed)
                # Send user to Add Funds card flow; after success, auto-submit checkout.
                _pending_checkout_set(
                    source="checkout_submit",
                    next_url=url_for("checkout_after_topup"),
                    required_cents=req,
                    balance_cents=bal,
                    amount_cents=needed,
                    edit_order_url=_resolve_edit_order_url(
                        session.get("cart_edit_order_url")
                        if isinstance(session.get("cart_edit_order_url"), str)
                        else None
                    ),
                )
                # Show the CRM's authoritative numbers so a "but I have balance!"
                # mismatch is visible to the customer instead of looking like a
                # random rejection. Winnings are named separately when they
                # exist, so nobody is told they have nothing while holding
                # money the site simply will not spend unasked.
                if req > 0 and wins_bal > 0:
                    flash(
                        f"This order needs {sym}{req / 100:.2f}. Your added funds "
                        f"({sym}{added_bal / 100:.2f}) and winnings ({sym}{wins_bal / 100:.2f}) "
                        f"together are {sym}{max(0, req - added_bal - wins_bal) / 100:.2f} short. "
                        "Use the payment button below to add the difference.",
                        "warning",
                    )
                elif req > 0:
                    flash(
                        f"Insufficient wallet balance: this order needs {sym}{req / 100:.2f} "
                        f"but only {sym}{bal / 100:.2f} is available to spend. "
                        "Use the payment button below to add the difference.",
                        "warning",
                    )
                else:
                    flash("Insufficient wallet balance. Return to cart and use the payment button to continue.", "warning")
                return redirect(url_for("cart"))
            emit_marketing_event(
                "purchase_failed",
                stable_key=f"{ctx.get('tid') or attempt_id}:submit_failed",
                metadata={"stage": "submit", "error": str(e)[:200]},
            )
            flash(_friendly_crm_error(e), "error")
            return redirect(url_for("cart"))
        except Exception:
            session.pop("mkt_checkout_attempt_id", None)
            session.pop("mkt_checkout_started_uuid", None)
            flash("We couldn't submit your order just now. Please try again.", "error")
            return redirect(url_for("cart"))

        # Snapshot the purchased cart so "Reuse last purchase" can restore it.
        _save_last_purchase_cart(items, resp.get("order_id") if isinstance(resp, dict) else None)
        session.pop("cart_items", None)
        session.pop("cart_edit_order_url", None)
        session.pop("checkout_quote_id", None)
        _checkout_promo_set(None)
        session.pop("checkout_bundle_slug", None)
        session.pop("checkout_bundle_locked_cents", None)
        session.pop("checkout_bundle_currency", None)
        session.pop("checkout_selected_checkout_offers", None)
        session.pop("mkt_checkout_attempt_id", None)
        session.pop("mkt_checkout_started_uuid", None)
        _pending_checkout_clear()
        order_id = resp.get("order_id")
        if order_id is not None:
            emit_marketing_event(
                "purchase_completed",
                stable_key=str(order_id),
                metadata={"order_id": order_id},
            )
        flash("Order placed.", "success")
        return redirect(url_for("order_detail", order_id=order_id))

    def _results_numbers_main_bonus(draw: dict[str, Any]) -> tuple[list[int], list[int]]:
        numbers = draw.get("numbers")
        if not isinstance(numbers, dict):
            return [], []
        main = numbers.get("main")
        if not isinstance(main, list):
            main = []
            for k, v in numbers.items():
                if str(k).lower() in {"bonus", "supplementary", "megaball", "powerball", "lucky_stars", "stars"}:
                    continue
                if isinstance(v, list):
                    main = v
                    break
        out_main: list[int] = []
        for n in main or []:
            try:
                out_main.append(int(n))
            except Exception:
                continue
        out_bonus: list[int] = []
        for key in ("bonus", "supplementary", "megaball", "powerball", "lucky_stars", "stars"):
            v = numbers.get(key)
            if isinstance(v, list):
                for n in v:
                    try:
                        out_bonus.append(int(n))
                    except Exception:
                        continue
            else:
                try:
                    if v is not None and str(v).strip() != "":
                        out_bonus.append(int(v))
                except Exception:
                    continue
        out_main = sorted(list(dict.fromkeys(out_main)))
        out_bonus = sorted(list(dict.fromkeys(out_bonus)))
        return out_main, out_bonus

    def _results_draw_label(draw_date: str | None) -> str:
        raw = str(draw_date or "").strip()
        try:
            d = datetime.strptime(raw, "%Y-%m-%d")
            return d.strftime("%b %d")
        except Exception:
            return raw

    def _results_month_label(draw_date: str | None) -> str:
        raw = str(draw_date or "").strip()
        try:
            d = datetime.strptime(raw, "%Y-%m-%d")
            return d.strftime("%b %Y")
        except Exception:
            return "Unknown"

    def _results_human_tier_label(tier: dict[str, Any]) -> str:
        for k in ("description", "label", "name", "short_name", "shortName", "tier_code", "code"):
            v = tier.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return "Prize Tier"

    def _results_tier_signature(tier: dict[str, Any]) -> tuple[int | None, int | None]:
        for k in ("match_main", "main_matches", "main_match_count", "matched_main"):
            try:
                mv = int(tier.get(k))
                break
            except Exception:
                mv = None
        for k in ("match_bonus", "bonus_matches", "bonus_match_count", "matched_bonus"):
            try:
                bv = int(tier.get(k))
                break
            except Exception:
                bv = None
        if mv is not None:
            return mv, bv
        code = str(tier.get("tier_code") or tier.get("code") or "").strip().lower()
        nums = [int(x) for x in re.findall(r"\d+", code)]
        main_hits = nums[0] if nums else None
        bonus_hits = nums[1] if len(nums) > 1 else None
        if bonus_hits is None and re.search(r"(^|[-_])(s|b|bonus|star|stars|pb|mb)([-_]|$)", code):
            bonus_hits = 1
        return main_hits, bonus_hits

    def _normalize_results_draw(draw: dict[str, Any]) -> dict[str, Any]:
        main_numbers, bonus_numbers = _results_numbers_main_bonus(draw)
        tiers_raw = draw.get("prize_tiers") if isinstance(draw.get("prize_tiers"), list) else []
        tiers: list[dict[str, Any]] = []
        total_winners = 0
        total_payout = 0.0
        draw_currency = str(draw.get("currency") or "").strip().upper()
        for t in tiers_raw:
            if not isinstance(t, dict):
                continue
            try:
                winners = int(t.get("winners_count") or t.get("winners") or 0)
            except Exception:
                winners = 0
            try:
                amount = float(t.get("prize_amount") or t.get("amount") or 0.0)
            except Exception:
                amount = 0.0
            cur = str(t.get("currency") or draw_currency or "").strip().upper()
            payout = float(winners) * float(amount)
            total_winners += winners
            total_payout += payout
            tiers.append(
                {
                    "tier_code": str(t.get("tier_code") or t.get("code") or "").strip(),
                    "label": _results_human_tier_label(t),
                    "winners_count": winners,
                    "prize_amount": amount,
                    "currency": cur,
                    "payout_amount": payout,
                    "main_bonus_signature": _results_tier_signature(t),
                }
            )
        tiers.sort(key=lambda x: (x.get("prize_amount") or 0.0), reverse=True)
        draw_date = str(draw.get("draw_date") or "").strip()
        return {
            "id": str(draw.get("id") or "").strip(),
            "draw_date": draw_date,
            "draw_date_label": _results_draw_label(draw_date),
            "draw_month_label": _results_month_label(draw_date),
            "draw_number": str(draw.get("draw_number") or "").strip(),
            "status": str(draw.get("status") or "").strip().lower(),
            "currency": draw_currency,
            "jackpot_total": float(draw.get("jackpot_total") or 0.0) if str(draw.get("jackpot_total") or "").strip() else 0.0,
            "main_numbers": main_numbers,
            "bonus_numbers": bonus_numbers,
            "prize_tiers": tiers,
            "total_winners_count": total_winners,
            "total_prize_payout": total_payout,
            "is_pending": (not main_numbers and not bonus_numbers) or str(draw.get("status") or "").strip().lower() not in {"completed", ""},
        }

    def _results_display_name(game_code: str, fallback_name: str | None = None) -> str:
        gc = str(game_code or "").strip().lower()
        if gc == "megamillions":
            return "Mega Millions"
        if gc == "lotto-fr":
            return "French Lotto"
        if gc == "lotto-ie":
            return "Irish Lotto"
        return str(fallback_name or game_code or "").strip()

    def _results_game_meta(game_code: str, games: list[dict[str, Any]], jackpots: list[dict[str, Any]]) -> dict[str, Any]:
        code = str(game_code or "").strip().lower()
        game = None
        for g_ in games:
            if str(g_.get("game_code") or "").strip().lower() == code:
                game = g_
                break
        game_name = _results_display_name(code, game.get("game_name") if isinstance(game, dict) else code)

        legacy_lottery_slug = ""
        for slug, name in (g.brand.legacy_lottery_slug_to_game_name or {}).items():
            if norm(str(name)) == norm(game_name):
                legacy_lottery_slug = slug
                break
        legacy_results_slug = ""
        for slug, name in (g.brand.legacy_results_slug_to_game_name or {}).items():
            if norm(str(name)) == norm(game_name):
                legacy_results_slug = slug
                break

        jackpot = None
        for j in jackpots:
            if str(j.get("game_code") or "").strip().lower() == code:
                jackpot = j
                break
        jackpot_total = 0.0
        try:
            jackpot_total = float(jackpot.get("jackpot_total") or 0.0) if isinstance(jackpot, dict) else 0.0
        except Exception:
            jackpot_total = 0.0
        jackpot_currency = str((jackpot or {}).get("currency") or "").strip().upper() if isinstance(jackpot, dict) else ""
        jackpot_symbol = _currency_symbol(jackpot_currency)

        logo_url = _find_local_logo(code, game_name)
        if not logo_url and isinstance(game, dict):
            logo_url = game.get("logo_url")
        if not logo_url and isinstance(jackpot, dict):
            logo_url = jackpot.get("logo_url")

        cutoff_at_utc = ""
        for k in ("cutoff_at_utc", "next_draw_utc", "next_cutoff_at_utc", "draw_datetime_utc"):
            v = (jackpot or {}).get(k) if isinstance(jackpot, dict) else None
            if v is not None and str(v).strip():
                cutoff_at_utc = str(v).strip()
                break
        if not cutoff_at_utc and isinstance(game, dict):
            for k in ("cutoff_at_utc", "next_draw_utc", "next_cutoff_at_utc", "draw_datetime_utc"):
                v = game.get(k)
                if v is not None and str(v).strip():
                    cutoff_at_utc = str(v).strip()
                    break

        return {
            "game_code": code,
            "game_name": game_name,
            "legacy_lottery_slug": legacy_lottery_slug,
            "legacy_results_slug": legacy_results_slug,
            # Canonical URLs, not the legacy slugs those pages redirect from.
            "results_url": url_for("results_game", game_code=code),
            "play_url": url_for("play", game_code=code),
            "logo_url": logo_url,
            "jackpot_total": jackpot_total,
            "jackpot_currency": jackpot_currency,
            "jackpot_currency_symbol": jackpot_symbol,
            "jackpot_display": f"{jackpot_symbol}{jackpot_total:,.0f}" if jackpot_total > 0 and jackpot_symbol else "",
            "cutoff_at_utc": cutoff_at_utc,
        }

    def _fetch_results_draws(game_code: str, *, limit: int = 60) -> list[dict[str, Any]]:
        """
        The most recent draws for a game, newest first.

        The live call only tops the cache up; the answer always comes back out
        of the cache. That is deliberate: the cache is what the homepage, nav
        and footer read, and it is ordered by draw date, whereas the CRM
        response is ordered by update time and windowed. Returning the live
        payload directly is what let this page and the rest of the site
        disagree about the latest result for the same game.
        """
        cache = get_cache()
        code = str(game_code or "").strip().lower()
        if not _crm_cache_only_mode():
            try:
                since = (datetime.now(timezone.utc) - timedelta(days=_RESULTS_LIVE_WINDOW_DAYS)).date().isoformat()
                dr = get_crm().draw_results(
                    game_code=code,
                    draw_date_from=since,
                    limit=max(int(limit), 200),
                    include_prize_tiers=1,
                )
                draws = dr.get("draws", []) if isinstance(dr, dict) else []
                if isinstance(draws, list):
                    cache.upsert_draw_results_page(
                        [d for d in draws if isinstance(d, dict)],
                        include_prize_tiers=True,
                    )
            except Exception:
                pass
        return [d for d in cache.get_draw_results_for_game(code, limit=limit) if isinstance(d, dict)]

    def _results_checker_rules(game: dict[str, Any] | None, draws: list[dict[str, Any]]) -> dict[str, Any]:
        def _normalize_groups(raw: Any) -> list[dict[str, Any]]:
            if isinstance(raw, list):
                return [g_ for g_ in raw if isinstance(g_, dict)]
            if isinstance(raw, dict) and isinstance(raw.get("groups"), list):
                return [g_ for g_ in raw.get("groups") if isinstance(g_, dict)]
            return []

        # IMPORTANT: checker input rules should follow ticket schema (what users pick),
        # not draw supplementary groups (which can include non-pick numbers).
        # Draw-derived counts are only a fallback when schema is unavailable.
        draw_main_count = 0
        draw_bonus_count = 0
        draw_main_max = 0
        draw_bonus_max = 0
        for d in draws:
            if not isinstance(d, dict):
                continue
            dm = d.get("main_numbers")
            db = d.get("bonus_numbers")
            if isinstance(dm, list) and dm and draw_main_count == 0:
                draw_main_count = len(dm)
            if isinstance(db, list) and db and draw_bonus_count == 0:
                draw_bonus_count = len(db)
            if isinstance(dm, list):
                for n in dm:
                    try:
                        draw_main_max = max(draw_main_max, int(n))
                    except Exception:
                        continue
            if isinstance(db, list):
                for n in db:
                    try:
                        draw_bonus_max = max(draw_bonus_max, int(n))
                    except Exception:
                        continue

        groups: list[dict[str, Any]] = []
        if isinstance(game, dict):
            products: list[dict[str, Any]] = []
            for k in (
                "products",
                "default_products",
                "skus",
                "single_products",
                "syndicate_products",
                "product",
                "default_product",
                "single_product",
                "syndicate_product",
            ):
                v = game.get(k)
                if isinstance(v, list):
                    products = [p for p in v if isinstance(p, dict)]
                    if products:
                        break
                elif isinstance(v, dict):
                    products = [v]
                    break
            for p in products:
                groups = _normalize_groups(p.get("line_schema"))
                if groups:
                    break
        main_rule: dict[str, Any] | None = None
        bonus_rule: dict[str, Any] | None = None

        if groups:
            for g_ in groups:
                name = str(g_.get("name") or "").strip() or "main"
                rule = {
                    "name": name,
                    "min": int(g_.get("min") or 1),
                    "max": int(g_.get("max") or 50),
                    "count": int(g_.get("count") or 1),
                    "label": str(name).replace("_", " ").title(),
                }
                if name.lower() == "main" and main_rule is None:
                    main_rule = rule
                elif bonus_rule is None:
                    bonus_rule = rule

        has_schema_groups = bool(groups)

        # Fallback to draw structure only when schema is unavailable.
        if not has_schema_groups and main_rule is None and draw_main_count > 0:
            main_rule = {
                "name": "main",
                "min": 1,
                "max": draw_main_max or 50,
                "count": draw_main_count,
                "label": "Numbers",
            }
        if not has_schema_groups and bonus_rule is None and draw_bonus_count > 0:
            bonus_rule = {
                "name": "bonus",
                "min": 1,
                "max": draw_bonus_max or 20,
                "count": draw_bonus_count,
                "label": "Bonus",
            }

        if main_rule is None:
            max_main = 50
            count_main = 5
            for d in draws:
                nums = d.get("main_numbers")
                if isinstance(nums, list) and nums:
                    count_main = len(nums)
                    try:
                        max_main = max(max_main, max(int(x) for x in nums))
                    except Exception:
                        pass
                    break
            main_rule = {"name": "main", "min": 1, "max": max_main, "count": count_main, "label": "Numbers"}

        if (not has_schema_groups) and bonus_rule is None:
            max_bonus = 0
            count_bonus = 0
            for d in draws:
                nums = d.get("bonus_numbers")
                if isinstance(nums, list) and nums:
                    count_bonus = len(nums)
                    try:
                        max_bonus = max(max_bonus, max(int(x) for x in nums))
                    except Exception:
                        pass
                    break
            if count_bonus > 0:
                bonus_rule = {
                    "name": "bonus",
                    "min": 1,
                    "max": max_bonus or 20,
                    "count": count_bonus,
                    "label": "Bonus",
                }

        return {"main": main_rule, "bonus": bonus_rule}

    def _results_page_model(game_code: str, *, selected_month: str | None = None) -> dict[str, Any]:
        code = str(game_code or "").strip().lower()
        games = store_games_cached()
        jackpots, _ = _get_jackpots_live_or_cache(timeout_seconds=_layout_timeout_seconds())
        meta = _results_game_meta(code, games, jackpots)
        draws_raw = _fetch_results_draws(code, limit=60)
        draws = [_normalize_results_draw(d) for d in draws_raw if isinstance(d, dict)]
        draws.sort(key=lambda d: str(d.get("draw_date") or ""), reverse=True)

        months: list[str] = []
        for d in draws:
            m = str(d.get("draw_month_label") or "").strip()
            if m and m not in months:
                months.append(m)
        active_month = str(selected_month or "").strip() or (months[0] if months else "")
        selected_draws = [d for d in draws if not active_month or str(d.get("draw_month_label") or "") == active_month]

        game_obj = None
        if not _crm_cache_only_mode():
            try:
                resp = get_crm().store_game(code)
                if isinstance(resp, dict):
                    game_obj = resp
            except Exception:
                game_obj = None
        if not isinstance(game_obj, dict):
            for g_ in games:
                if str(g_.get("game_code") or "").strip().lower() == code:
                    game_obj = g_
                    break
        rules = _results_checker_rules(game_obj if isinstance(game_obj, dict) else None, draws)
        # CRM draw payloads can include supplementary balls for Oz Lotto results,
        # but ticket entry is main-only. Keep checker aligned with ticket schema.
        if code == "oz-lotto-au":
            rules["main"] = {"name": "main", "min": 1, "max": 47, "count": 7, "label": "Numbers"}
            rules["bonus"] = None
        return {
            "game": meta,
            "all_draws": draws,
            "months": months,
            "selected_month": active_month,
            "selected_draws": selected_draws,
            "checker_rules": rules,
        }

    def _results_coerce_numbers(v: Any) -> list[int]:
        out: list[int] = []
        if isinstance(v, list):
            for x in v:
                try:
                    out.append(int(x))
                except Exception:
                    continue
        elif isinstance(v, str):
            for x in re.split(r"[\s,]+", v.strip()):
                if not x:
                    continue
                try:
                    out.append(int(x))
                except Exception:
                    continue
        elif v is not None:
            try:
                out.append(int(v))
            except Exception:
                pass
        return sorted(list(dict.fromkeys(out)))

    def _results_find_tier(prize_tiers: list[dict[str, Any]], main_count: int, bonus_count: int) -> dict[str, Any] | None:
        for t in prize_tiers:
            sig = t.get("main_bonus_signature")
            if not isinstance(sig, tuple) or len(sig) != 2:
                continue
            req_main, req_bonus = sig
            if req_main is None:
                continue
            if int(req_main) != int(main_count):
                continue
            if req_bonus is None:
                continue
            if int(req_bonus) != int(bonus_count):
                continue
            return t
        for t in prize_tiers:
            sig = t.get("main_bonus_signature")
            if not isinstance(sig, tuple) or len(sig) != 2:
                continue
            req_main, req_bonus = sig
            if req_main is None:
                continue
            if int(req_main) == int(main_count) and int(req_bonus or 0) == 0 and int(bonus_count) == 0:
                return t
        return None

    @app.get("/winning-lottery-numbers")
    def results_index():
        games = store_games_cached()
        jackpots, _ = _get_jackpots_live_or_cache(timeout_seconds=_layout_timeout_seconds())
        cache = get_cache()
        rows: list[dict[str, Any]] = []
        # LottosOnline: the lotteries the old results page listed, in the site's order, whether or not the
        # brand sells them (UK Lotto is results-only).
        for _lot in [l for l in lo_lotteries.LOTTERIES if l.results]:
            code = _lot.game_code
            meta = _results_game_meta(code, games, jackpots)
            latest = None
            try:
                draws = cache.get_draw_results_for_game(code, limit=5)
                for d in draws:
                    if isinstance(d, dict):
                        latest = d
                        break
            except Exception:
                latest = None
            latest_model = _normalize_results_draw(latest) if isinstance(latest, dict) else None
            rows.append(
                {
                    "game": meta,
                    "last_draw_label": latest_model.get("draw_date_label") if latest_model else "Pending",
                    "last_draw_pending": bool(latest_model.get("is_pending")) if latest_model else True,
                    "last_main_numbers": latest_model.get("main_numbers") if latest_model else [],
                    "last_bonus_numbers": latest_model.get("bonus_numbers") if latest_model else [],
                    "lottery": _lot,
                }
            )
        return render_template("lo/results_index.html", rows=rows, page=app.config["LO_LEGACY_PAGES"].get("/winning-lottery-numbers"))

    @app.get("/winning-lottery-numbers/<lo_results:game_code>")
    def results_game(game_code: str):
        # The model happily invents a page for any string, which turned every
        # typo and stale link into an indexable empty results page. The lo_results URL converter only
        # admits LottosOnline's results lotteries (including results-only UK Lotto), so check that list.
        if lo_lotteries.by_game_code(game_code) is None:
            abort(404)
        model = _results_page_model(game_code)
        return render_template(
            "results_game.html",
            game=model["game"],
            months=model["months"],
            selected_month=model["selected_month"],
            draws=model["selected_draws"],
            checker_rules=model["checker_rules"],
        )

    @app.get("/api/results/<game_code>/month")
    def results_game_month_api(game_code: str):
        month = (request.args.get("month") or "").strip()
        model = _results_page_model(game_code, selected_month=month)
        return {
            "ok": True,
            "game_code": str(game_code or "").strip().lower(),
            "selected_month": model["selected_month"],
            "draws": model["selected_draws"],
        }

    @app.post("/api/results/<game_code>/check-numbers")
    def results_game_check_numbers_api(game_code: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = request.form.to_dict(flat=True)
        month = str(payload.get("month") or "").strip()
        main_numbers = _results_coerce_numbers(payload.get("main_numbers"))
        bonus_numbers = _results_coerce_numbers(payload.get("bonus_numbers"))

        model = _results_page_model(game_code, selected_month=month)
        matches: list[dict[str, Any]] = []
        for d in model["selected_draws"]:
            d_main = [int(x) for x in (d.get("main_numbers") or [])]
            d_bonus = [int(x) for x in (d.get("bonus_numbers") or [])]
            matched_main = sorted(list(set(main_numbers) & set(d_main)))
            matched_bonus = sorted(list(set(bonus_numbers) & set(d_bonus)))
            if not matched_main and not matched_bonus:
                continue
            tier = _results_find_tier(d.get("prize_tiers") or [], len(matched_main), len(matched_bonus))
            matches.append(
                {
                    "draw_date": d.get("draw_date"),
                    "draw_date_label": d.get("draw_date_label"),
                    "matched_main": matched_main,
                    "matched_bonus": matched_bonus,
                    "tier": {
                        "label": tier.get("label"),
                        "tier_code": tier.get("tier_code"),
                        "prize_amount": tier.get("prize_amount"),
                        "currency": tier.get("currency"),
                    }
                    if isinstance(tier, dict)
                    else None,
                }
            )
        return {
            "ok": True,
            "game_code": str(game_code or "").strip().lower(),
            "selected_month": model["selected_month"],
            "matches": matches,
            "tier_resolution": "exact_or_fallback",
        }

    # --- Marketing Module offer landing pages ---
    #
    # Campaign links from the Marketing Module land here, so this page's failure
    # modes matter more than most: everyone who reaches it was sent deliberately
    # and paid for, and there is no navigation that leads here by accident.

    # Bundle items name their SKU under whichever of these the tenant uses.
    _OFFER_ITEM_CODE_KEYS = ("product_code", "lottery_product_code", "sku", "code")

    def _bundle_by_slug(bundle_slug: str) -> tuple[dict[str, Any] | None, bool]:
        """
        A bundle, tried in each case the slug might have been written in.

        The Module has stored both `PB_Welcome2` and `pb_welcome2` and live
        links exist in both forms, so a lookup that only tries what it was
        handed answers "no such offer" to our own campaigns.

        Also reports whether the CRM answered at all. An offer that does not
        exist and an endpoint we cannot call look the same to a visitor and
        must not look the same to us — the bundles endpoint is IP-gated, and a
        server whose egress is off the allowlist would otherwise present every
        campaign as withdrawn.
        """
        reachable = False
        for candidate in dict.fromkeys([bundle_slug, bundle_slug.lower(), bundle_slug.upper()]):
            try:
                resp = get_crm().bundle(candidate)
            except CRMError as e:
                if (getattr(e, "status_code", None) or 0) == 404:
                    reachable = True
                else:
                    app.logger.warning("bundle %r could not be read: %s", candidate, e)
                continue
            except Exception as e:  # noqa: BLE001 - a landing page must still render
                app.logger.warning("bundle %r could not be read: %s", candidate, e)
                continue
            reachable = True
            bundle = resp.get("bundle") if isinstance(resp, dict) else None
            if isinstance(bundle, dict) and bundle:
                return bundle, True
        return None, reachable

    # `shares remaining` has no settled name across the store payloads, and an
    # offer must render whether or not the count is there, so several are
    # accepted and a missing one is simply not shown.
    _SYNDICATE_SHARES_KEYS = ("syndicate_shares_remaining", "shares_remaining", "shares_available")

    # How many boards the group's wheel plays. `syndicate_boards_per_group` is
    # what the store catalogue calls it; the others are accepted because the
    # panel is the only place a customer learns what the wheel actually is.
    _SYNDICATE_BOARDS_KEYS = (
        "syndicate_boards_per_group",
        "syndicate_wheel_num_lines",
        "syndicate_num_lines",
        "syndicate_lines",
    )

    def _offer_int(value: Any) -> int | None:
        try:
            return int(float(str(value).replace(",", "").strip()))
        except Exception:
            return None

    def _offer_product_facts(product: Any) -> dict[str, Any]:
        """
        What the offer page needs about a SKU beyond which game it belongs to.

        A syndicate share is not a ticket. The group's boards are wheeled before
        anyone buys in, so there are no numbers to choose, no line schema to
        draw from, and nothing for the customer to complete — and a page that
        asks them to build a play cannot be bought at all, because the Continue
        button waits for numbers that will never be picked.

        `product_type` is the only safe way to tell the two apart. The syndicate
        codes share no prefix and their names are inconsistent, so matching on
        either would miss one the day the CRM adds the seventh.
        """
        facts: dict[str, Any] = {}
        if not isinstance(product, dict):
            return facts
        product_type = str(product.get("product_type") or "").strip().lower()
        if product_type:
            facts["product_type"] = product_type
        if product_type != "syndicate":
            return facts
        facts["is_syndicate"] = True
        # The catalogue has no field for the wheel's name, and the game's name
        # alone ("Lotto (FR)") does not tell a customer which wheel they are
        # buying a share of. The product's own name does.
        name = str(
            product.get("syndicate_prebuilt_wheel_name") or product.get("name") or ""
        ).strip()
        if name:
            facts["syndicate_prebuilt_wheel_name"] = name
        # The board count is what makes a wheel worth buying — it is the
        # difference between one chance for twenty numbers and thousands — and
        # the CRM's own name for it is `syndicate_boards_per_group`.
        for key in _SYNDICATE_BOARDS_KEYS:
            number = _offer_int(product.get(key))
            if number is not None and number > 0:
                facts["syndicate_wheel_num_lines"] = number
                break
        participants = _offer_int(product.get("syndicate_max_participants"))
        if participants is not None and participants > 0:
            facts["syndicate_max_participants"] = participants
        for key in _SYNDICATE_SHARES_KEYS:
            number = _offer_int(product.get(key))
            if number is not None and number >= 0:
                facts["syndicate_shares_remaining"] = number
                break
        return facts

    def _offer_game_index(codes: list[str]) -> dict[str, dict[str, Any]]:
        """
        What each SKU a bundle names is: its game, and whether it is a syndicate.

        The games cache is the first place to look and the flat catalogue the
        second, the same order the cart's schema lookup uses: a cold cache must
        not cost the offer page its game names.
        """
        found: dict[str, dict[str, Any]] = {}
        for code in codes:
            game = _game_for_product_code(code) or {}
            product = _catalog_product(code) or {}
            entry = _offer_product_facts(product)
            game_code = str(game.get("game_code") or product.get("game_code") or "").strip().lower()
            if game_code:
                entry["game_code"] = game_code
                entry["game_name"] = str(game.get("game_name") or product.get("name") or code).strip()
            if entry:
                found[code] = entry
        # Asked of the CRM when the cache still cannot name the game — not when
        # the code is merely absent from the index. A syndicate cached without a
        # game code now has an entry, and keying the fallback off "is it here
        # yet" would let that entry suppress the lookup that would have named it.
        if any(not (found.get(code) or {}).get("game_code") for code in codes):
            try:
                for product in (get_crm().store_products() or {}).get("products") or []:
                    if not isinstance(product, dict):
                        continue
                    pc = str(product.get("code") or product.get("product_code") or "").strip().upper()
                    if pc not in codes or (found.get(pc) or {}).get("game_code"):
                        continue
                    entry = dict(found.get(pc) or {})
                    entry.update(_offer_product_facts(product))
                    game_code = str(product.get("game_code") or "").strip().lower()
                    if game_code:
                        name = str(product.get("game_name") or product.get("name") or "").strip()
                        entry["game_code"] = game_code
                        entry["game_name"] = (
                            name or (_catalog_game(game_code) or {}).get("game_name") or game_code
                        )
                    if entry:
                        found[pc] = entry
            except Exception:
                pass
        return found

    def _bundle_locked_price(bundle: dict[str, Any] | None) -> tuple[int | None, str]:
        """
        The bundle's locked price and the currency that price is in.

        Not the brand's currency. Marketing locks a promo in whichever currency
        it chose, and the CRM prices it against that currency's catalog with no
        FX (API 65), so `base_currency` — the tenant's — is the wrong label and
        put a pound sign on a EUR 25.00 offer. `locked_price_eur_cents` keeps
        its name for historical reasons and is read only when the canonical
        field is absent; despite the name it is also in the locked currency.
        """
        if not isinstance(bundle, dict):
            return None, ""
        cents: int | None = None
        for key in ("locked_price_base_cents", "locked_price_eur_cents"):
            raw = bundle.get(key)
            if raw is None:
                continue
            try:
                cents = int(float(raw))
            except Exception:
                continue
            break
        # Older bundles have no locked currency, and for those the tenant's is
        # the only answer there is.
        currency = str(bundle.get("locked_price_currency") or bundle.get("base_currency") or "").strip().upper()
        return cents, currency

    # Marketing sets an offer's own closing date in the Module. Its banners
    # payload names that window `start_at` / `end_at`, so that is the first
    # thing looked for here.
    _BUNDLE_DEADLINE_KEYS = (
        "end_at",
        "ends_at",
        "expires_at",
        "expiry_at",
        "valid_until",
        "available_until",
        "offer_ends_at",
    )

    # The bundle payload is the CRM's own shape and need not use the banners'
    # spelling, and a list of guesses that misses leaves the page showing the
    # draw's clock as though the offer had no deadline at all — wrong, and
    # silently so. So any key that reads as a closing date and holds a
    # timestamp is taken, whatever it is called.
    _DEADLINE_WORDS = frozenset(
        {
            "end", "ends", "ended", "ending",
            "expire", "expires", "expired", "expiry", "expiration",
            "until", "close", "closes", "closed", "closing",
            "deadline", "cutoff", "finish", "finishes", "finishing",
        }
    )
    # A bundle carries `start_at` and `created_at` too, and `draw_cutoff_at`
    # is the lottery's date rather than the offer's — the very date this is
    # meant to stop showing.
    _DEADLINE_NOT_WORDS = frozenset(
        {"start", "starts", "started", "begin", "begins", "created", "updated", "draw", "draws"}
    )
    # `valid_to` and `available_to` are deadlines. A bare `to` is not.
    _DEADLINE_TO_WORDS = frozenset(
        {"valid", "available", "active", "live", "offer", "sale", "sell", "run", "running", "display"}
    )

    def _is_deadline_key(key: Any) -> bool:
        """Whether a payload key names the date an offer stops being sellable."""
        words = [w for w in re.split(r"[^a-z0-9]+", str(key).lower()) if w]
        if not words or _DEADLINE_NOT_WORDS.intersection(words):
            return False
        if _DEADLINE_WORDS.intersection(words):
            return True
        return "to" in words and bool(_DEADLINE_TO_WORDS.intersection(words))

    def _bundle_deadline_dates(bundle: dict[str, Any]) -> list[datetime]:
        """
        Every closing date the bundle states, wherever it keeps it.

        Nested objects are searched because some tenants hang the window off a
        `campaign` or `settings` block, but lists are not: a bundle's items
        carry their own draw dates, and those are not the offer's deadline.
        """
        found: list[datetime] = []

        def walk(node: Any, depth: int) -> None:
            if not isinstance(node, dict) or depth > 2:
                return
            for key, value in node.items():
                if isinstance(value, dict):
                    walk(value, depth + 1)
                elif _is_deadline_key(key):
                    ends = _as_utc_datetime(value)
                    if ends is not None:
                        found.append(ends)

        walk(bundle, 0)
        return found

    def _as_utc_datetime(raw: Any) -> datetime | None:
        """A CRM timestamp as an aware UTC datetime, or None if it isn't one."""
        if raw in (None, ""):
            return None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except Exception:
                return None
        text = str(raw).strip()
        if not text:
            return None
        # An all-digit string is an epoch, not a date: `fromisoformat` would
        # either refuse it or read it as a year.
        if re.fullmatch(r"\d{9,13}", text):
            try:
                value = float(text)
                return datetime.fromtimestamp(value / 1000 if len(text) > 10 else value, tz=timezone.utc)
            except Exception:
                return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
        except Exception:
            return None
        # The CRM sends some timestamps without an offset. They are UTC, and
        # reading them as local time would move the deadline by hours.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _bundle_deadline_seconds(bundle: dict[str, Any] | None) -> int | None:
        """
        Seconds until the offer itself closes, or None when it has no closing
        date.

        Marketing's deadline, not the lottery's. They are different dates, and
        a customer reading one as the other either hurries a purchase that had
        days left on it or lets a window close they believed was still open.
        """
        if not isinstance(bundle, dict):
            return None
        now = datetime.now(timezone.utc)
        for key in _BUNDLE_DEADLINE_KEYS:
            ends = _as_utc_datetime(bundle.get(key))
            if ends is not None:
                return max(0, int(ends.timestamp() - now.timestamp()))
        found = _bundle_deadline_dates(bundle)
        if not found:
            return None
        # A bundle can state more than one closing date. The offer stops being
        # sellable at the first of them, so that is the one to count to; once
        # they have all passed the clock reads zero whichever is chosen.
        future = [d for d in found if d > now]
        ends = min(future) if future else max(found)
        return max(0, int(ends.timestamp() - now.timestamp()))

    def _offer_tickets(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        """
        One entry per ticket the bundle buys, numbered across the whole bundle.

        Winnow takes the lottery from a single value on the bundle, so its
        three-lottery offer draws three Mega Millions boards and labels every
        one of them "Ticket 1 of 1". The items array is the only thing that
        knows what a bundle actually contains, so it is the only thing allowed
        to drive this page.
        """
        ordered: list[tuple[str, int, str]] = []
        for item in bundle.get("items") or []:
            if not isinstance(item, dict):
                continue
            code = ""
            for key in _OFFER_ITEM_CODE_KEYS:
                code = str(item.get(key) or "").strip().upper()
                if code:
                    break
            if not code:
                continue
            try:
                quantity = int(item.get("quantity") or 1)
            except Exception:
                quantity = 1
            # `quantity` is boards. `draws_count` inside config_json is how many
            # draws each of those boards enters, so it labels a board and never
            # multiplies them.
            ordered.append((code, max(1, min(quantity, 50)), _schedule_sentence(item.get("config_json"))))

        games = _offer_game_index([code for code, _, _ in ordered])
        tickets: list[dict[str, Any]] = []
        for code, quantity, schedule in ordered:
            game = games.get(code) or {}
            game_code = game.get("game_code") or None
            game_name = game.get("game_name") or code
            # Each board is headed by its own game, which is the only thing that
            # tells them apart in a bundle spanning several lotteries.
            logo_url = _find_local_logo(str(game_code or code), str(game_name)) if game_code else None
            is_syndicate = bool(game.get("is_syndicate"))
            for _ in range(quantity):
                ticket: dict[str, Any] = {
                    "product_code": code,
                    "game_code": game_code,
                    "game_name": game_name,
                    "logo_url": logo_url,
                    "schedule": schedule,
                    "is_syndicate": is_syndicate,
                }
                if is_syndicate:
                    for key in (
                        "syndicate_prebuilt_wheel_name",
                        "syndicate_wheel_num_lines",
                        "syndicate_max_participants",
                        "syndicate_shares_remaining",
                    ):
                        if key in game:
                            ticket[key] = game[key]
                tickets.append(ticket)
        # Counted across the boards that have numbers to pick, not across the
        # bundle. A share is not one of them, so including it labels two boards
        # "Ticket 1 of 3" and "Ticket 2 of 3" and sends the customer looking for
        # a third that is not there.
        playable = [t for t in tickets if not t.get("is_syndicate")]
        for position, ticket in enumerate(playable, start=1):
            ticket["position"] = position
            ticket["total"] = len(playable)
        return tickets

    def _offer_syndicate_panels(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        One summary panel per syndicate SKU, however many shares it buys.

        Shares are counted rather than listed. Two shares of one syndicate are
        two stakes in the same boards, so drawing the same wheel twice would
        read as two different entries.
        """
        panels: dict[str, dict[str, Any]] = {}
        for ticket in tickets:
            if not ticket.get("is_syndicate"):
                continue
            code = str(ticket.get("product_code") or "")
            panel = panels.get(code)
            if panel is None:
                panel = {k: v for k, v in ticket.items() if k not in ("position", "total")}
                panel["shares"] = 0
                panels[code] = panel
            panel["shares"] += 1
        return list(panels.values())

    def _offer_hero(tickets: list[dict[str, Any]]) -> dict[str, Any]:
        """
        The games an offer leads with, and the jackpot each is playing for.

        A bundle is a fixed set of tickets that can span several lotteries, so
        there is not always one figure to headline. A single-lottery bundle gets
        the play page's banner treatment — logo, live jackpot, cutoff countdown
        — and a bundle spanning several gets each of its games listed instead,
        because picking one of three jackpots to print in 73px would misstate
        what the customer is buying.
        """
        counts: dict[str, int] = {}
        shares: dict[str, int] = {}
        names: dict[str, str] = {}
        for ticket in tickets:
            code = str(ticket.get("game_code") or "").strip().lower()
            if not code:
                continue
            counts[code] = counts.get(code, 0) + 1
            if ticket.get("is_syndicate"):
                shares[code] = shares.get(code, 0) + 1
            names.setdefault(code, str(ticket.get("game_name") or code))
        if not counts:
            return {"games": [], "single": False}

        jackpots: dict[str, dict[str, Any]] = {}
        try:
            for entry in get_cache().get_cached_jackpots():
                if isinstance(entry, dict) and entry.get("game_code"):
                    jackpots.setdefault(str(entry["game_code"]).strip().lower(), entry)
        except Exception:
            jackpots = {}

        # A cached countdown was only true when it was fetched, so age it by how
        # long ago that was rather than counting down from an expired number.
        elapsed = 0
        try:
            last = get_cache().get_state("last_jackpots_fetch_at")
            if last:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                elapsed = max(0, int(datetime.now(timezone.utc).timestamp() - last_dt.timestamp()))
        except Exception:
            elapsed = 0

        games: list[dict[str, Any]] = []
        for code, count in counts.items():
            name = names.get(code) or code
            jackpot = jackpots.get(code) or {}
            nested = jackpot.get("jackpot") if isinstance(jackpot.get("jackpot"), dict) else {}
            amount = jackpot.get("jackpot_total")
            if amount is None:
                amount = nested.get("amount")
            currency = jackpot.get("currency") or nested.get("currency")
            display = None
            if currency and amount is not None:
                try:
                    display = f"{_currency_symbol(str(currency))}{float(amount):,.0f}"
                except Exception:
                    display = None
            try:
                raw_remaining = jackpot.get("remaining_seconds")
                remaining = max(0, int(raw_remaining) - elapsed) if raw_remaining is not None else None
            except Exception:
                remaining = None
            games.append(
                {
                    "game_code": code,
                    "game_name": name,
                    # A share buys into one set of group boards, so calling it a
                    # ticket overstates what is on offer.
                    "syndicate": shares.get(code, 0) == count,
                    "logo_url": _hero_logo_url(code, name),
                    "jackpot_display": display,
                    "remaining_seconds": remaining,
                    "tickets": count,
                }
            )
        games.sort(key=lambda entry: (-entry["tickets"], entry["game_name"]))
        return {"games": games, "single": len(games) == 1}

    def _render_offer(bundle_slug: str):
        bundle, reachable = _bundle_by_slug(bundle_slug)
        if not bundle:
            # Never redirect a campaign click. Someone who clicked an email link
            # has to be told at the address they clicked that the offer is not
            # available; bouncing them to a promotions list reading "No
            # promotions available yet" reads as the site being broken, and
            # loses the one thing the click was bought for. `noindex` keeps the
            # shell out of the index without costing the customer the message.
            return render_template(
                "offer.html",
                bundle=None,
                bundle_slug=bundle_slug,
                offer_reachable=reachable,
                tickets=[],
                offer_products=[],
                noindex="noindex, follow",
            )

        tickets = _offer_tickets(bundle)
        # A syndicate share has no board to draw, so it is judged on nothing and
        # only the playable tickets are held to having a schema. Without this
        # split every syndicate offer reads as a game we have stopped selling.
        playable = [t for t in tickets if not t.get("is_syndicate")]
        schemas = _cart_line_schemas(playable)
        unsellable = sorted({t["product_code"] for t in playable if not schemas.get(t["product_code"])})
        if unsellable:
            # A bundle built on a SKU the store does not sell has no boards to
            # draw. Winnow's live bundles all point at deactivated codes, so
            # this is a shape we will meet; name it here rather than serve a
            # picker with no numbers in it.
            app.logger.error(
                "offer %s references SKUs this store does not sell: %s",
                bundle_slug,
                ", ".join(unsellable),
            )
            tickets = []
            playable = []

        locked_cents, locked_currency = _bundle_locked_price(bundle)
        currency = locked_currency or _resolve_display_currency()
        # The offer's name as marketing wrote it, which is the same line the
        # customer read as the email subject before clicking (API 65). Never the
        # slug: a headline reading "welcome_to_lotto_express" is the one thing
        # on this page a customer is certain to read, and it tells them the
        # page is broken.
        offer_title = str(bundle.get("offer_name") or bundle.get("title") or "").strip()
        deadline_seconds = _bundle_deadline_seconds(bundle)
        if deadline_seconds is None:
            # The banner falls back to the draw cutoff, which is a different
            # date. Said here because otherwise "the countdown is showing the
            # wrong thing" and "marketing left the end date empty" look
            # identical from the page.
            # The field names are listed because the alternative is guessing
            # them again: if the CRM does carry the date under a name nothing
            # here recognises, this line is what says so.
            app.logger.info(
                "offer %s carries no closing date; banner uses the draw cutoff (bundle fields: %s)",
                bundle_slug,
                ", ".join(sorted(str(k) for k in bundle.keys())) if isinstance(bundle, dict) else "-",
            )
        return render_template(
            "offer.html",
            bundle=bundle,
            offer_deadline_seconds=deadline_seconds,
            offer_title=offer_title or "Special offer",
            offer_locked_cents=locked_cents,
            bundle_slug=str(bundle.get("bundle_slug") or bundle_slug),
            offer_reachable=True,
            tickets=tickets,
            offer_playable=playable,
            offer_syndicates=_offer_syndicate_panels(tickets),
            offer_products=[{"code": code, "line_schema": groups} for code, groups in schemas.items()],
            offer_currency_symbol=_currency_symbol(currency) or f"{currency} ",
            offer_unsellable=unsellable,
            offer_hero=_offer_hero(tickets),
        )

    @app.before_request
    def _normalise_offer_path():
        """
        Campaign links exist with the path itself in mixed case
        (`/OFFER/PB_WELCOME2`). Flask matches paths case-sensitively, so those
        answer 404 unless the segment is folded back to the one the routes are
        registered under.
        """
        parts = (request.path or "").strip("/").split("/")
        if not any(p != "offer" and p.lower() == "offer" for p in parts):
            return None
        target = "/" + "/".join("offer" if p.lower() == "offer" else p for p in parts)
        if request.query_string:
            target += "?" + request.query_string.decode("latin-1", "ignore")
        return redirect(target, code=301)

    @app.get("/offer/<bundle_slug>")
    def offer(bundle_slug: str):
        return _render_offer(bundle_slug)

    @app.get("/<locale>/offer/<bundle_slug>")
    def offer_localised(locale: str, bundle_slug: str):
        """
        The Module templates campaign links per locale (`/es-419/offer/...`).
        LottoExpress is English-only and has no locale scheme, but those links
        are printed in emails that have already gone out, so serve the offer
        rather than spend the click on a 404.
        """
        if not re.fullmatch(r"[a-z]{2}(-[a-z0-9]{2,8})?", (locale or "").lower()):
            abort(404)
        return _render_offer(bundle_slug)

    @app.post("/offer/<bundle_slug>/start")
    def offer_start(bundle_slug: str):
        bundle, _reachable = _bundle_by_slug(bundle_slug)
        if not bundle:
            flash("This offer is no longer available.", "error")
            return redirect(url_for("offer", bundle_slug=bundle_slug))
        # Checkout refuses an offer past its window as well, but only after the
        # customer has been through the cart and the payment step to get there.
        if _bundle_deadline_seconds(bundle) == 0:
            flash("This offer has ended.", "error")
            return redirect(url_for("offer", bundle_slug=bundle_slug))

        tickets = _offer_tickets(bundle)
        if not tickets:
            flash("This offer has no tickets to play.", "error")
            return redirect(url_for("offer", bundle_slug=bundle_slug))

        try:
            submitted = _parse_lines_json(request.form.get("lines_json") or "")
        except Exception as e:
            abort(400, f"Invalid lines_json: {e}")

        # Only the ordinary tickets have numbers to check. A syndicate's boards
        # are wheeled for the group before the offer goes out, so an offer made
        # entirely of shares posts no lines at all and must not be turned away
        # for it — that refusal is what made these offers impossible to buy.
        playable = [t for t in tickets if not t.get("is_syndicate")]
        if len(submitted) != len(playable) or not all(_line_has_any_selection(ln) for ln in submitted):
            flash("Please complete every ticket in this offer before continuing.", "warning")
            return redirect(url_for("offer", bundle_slug=bundle_slug))

        # The bundle is locked, so the cart is built from the bundle's own items
        # rather than from anything the form claimed. Consecutive tickets on one
        # SKU become a single cart item, which keeps the cart reading the way it
        # does from the play page.
        cart: list[dict[str, Any]] = []
        pending = list(submitted)
        for ticket in tickets:
            code = ticket["product_code"]
            last = cart[-1] if cart else None
            if ticket.get("is_syndicate"):
                # Shares of one syndicate are a quantity, not a list of lines:
                # they are several stakes in the same boards.
                if last and last["kind"] == "syndicate" and last["product_code"] == code:
                    last["quantity"] += 1
                    continue
                cart.append(
                    {
                        "kind": "syndicate",
                        "product_code": code,
                        "quantity": 1,
                        "options": {},
                        "game_code": ticket.get("game_code"),
                        "game_name": ticket.get("game_name"),
                    }
                )
                continue
            line = pending.pop(0)
            if last and last["kind"] == "single" and last["product_code"] == code:
                last["lines"].append(line)
                continue
            cart.append(
                {
                    "kind": "single",
                    "product_code": code,
                    "lines": [line],
                    "options": {},
                    "game_code": ticket.get("game_code"),
                    "game_name": ticket.get("game_name"),
                }
            )

        session["cart_items"] = cart
        session["cart_edit_order_url"] = url_for("offer", bundle_slug=bundle_slug)
        session["checkout_bundle_slug"] = str(bundle.get("bundle_slug") or bundle_slug)
        # Carried so the cart can never fall back to the catalog unit price for a
        # bundle. This is the figure the email promised and the offer page showed;
        # quoting it is still the CRM's job, and it re-prices again at submit.
        locked_cents, locked_currency = _bundle_locked_price(bundle)
        session["checkout_bundle_locked_cents"] = locked_cents
        session["checkout_bundle_currency"] = locked_currency
        session.pop("checkout_quote_id", None)
        _checkout_promo_set(None)
        session["checkout_selected_checkout_offers"] = []

        # A campaign link can carry a set-password token for a customer the
        # Module created without one. Offer them the shortcut on the way to
        # paying; if the token is dead, say nothing and leave the ordinary
        # login and register journey exactly as it was.
        if not session.get("crm_token") and _set_password_token():
            reason = ""
            try:
                check = get_crm().auth_set_password_check(_set_password_token())
                valid = bool(check.get("valid")) if isinstance(check, dict) else False
                if not valid:
                    reason = str(check.get("reason") or "unspecified") if isinstance(check, dict) else "unreadable"
            except Exception as e:  # noqa: BLE001 - a shortcut must never block the sale
                app.logger.info("set-password check failed, continuing as normal: %s", e)
                valid = False
            if valid:
                return redirect(url_for("set_password", next=url_for("cart")))
            # Declining is deliberately invisible to the customer, so without
            # this a campaign whose tokens are all being refused is
            # indistinguishable from a campaign nobody clicked. The reason is
            # safe to log; the token never is.
            if reason:
                app.logger.info("set-password shortcut declined: reason=%s", reason)
            session.pop("set_password_token", None)
        elif not session.get("crm_token"):
            # Mid-campaign, "the shortcut is broken" and "the link carried no
            # token" look identical from the outside: both land an anonymous
            # customer on the cart. Saying which decides whether to look at the
            # website or at the link template.
            app.logger.info("set-password shortcut skipped: no token on this journey")

        # A reactivation link belongs to someone with no account at all, so the
        # cart's "sign in to see your quote" is a dead end for them. Send them
        # to the sign-up form instead, and on to the cart once they have one.
        #
        # The token's presence is enough to decide this; whether it still
        # resolves to anything is the sign-up page's problem. A dead token
        # means an empty form, never a customer who cannot register.
        if not session.get("crm_token") and _reactivation_token():
            return redirect(url_for("register", next=url_for("cart")))

        return redirect(url_for("cart"))

    @app.get("/promotions")
    def promotions_index():
        # Simple CRM-driven offers discovery page powered by marketing banners.
        banners = marketing_banners_cached("catalog")
        return render_template("promotions_index.html", banners=banners)

    # --- Auth ---
    @app.get("/login")
    def login():
        return render_template("login.html", next=request.args.get("next"))

    @app.post("/login")
    def login_post():
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        next_url = _safe_next_url(request.form.get("next"), url_for("account"))
        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for("login", next=next_url))

        try:
            payload: dict[str, Any] = {"email": email, "password": password}
            ip = _client_ip()
            country = _geo_country_iso2()
            if ip:
                # Validate it's an IP string; if not, omit.
                try:
                    _ = ip_address(ip)
                    payload["ip"] = ip
                except Exception:
                    pass
            if country:
                payload["country"] = country
            data = get_crm().auth_login(payload)
        except CRMError as e:
            flash(_friendly_crm_error(e, context="login"), "error")
            return redirect(url_for("login", next=next_url))

        session["crm_token"] = data.get("token")
        session["customer"] = data.get("customer")
        session["time_on_site_started_at"] = int(time.time())
        session.pop("wallet", None)  # refresh on next page view
        # A real customer signing in on a browser that held a support session
        # is now themselves, with their own token and their own permissions.
        session.pop("customer_login_as", None)
        cust = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        if isinstance(cust, dict):
            verified = cust.get("email_verified")
            verified_at = cust.get("email_verified_at")
            if verified is True or bool(verified_at):
                session["email_verified_hint"] = True
        flash("Signed in.", "success")

        # If the user attempted to add tickets while logged out, complete that now.
        pending = session.pop("pending_cart_add", None)
        if isinstance(pending, dict):
            try:
                product_code = (pending.get("product_code") or "").strip()
                lines_json = (pending.get("lines_json") or "").strip()
                options_json = (pending.get("options_json") or "").strip()
                pending_game_code = _safe_game_code(pending.get("game_code"))
                pending_game_name = (pending.get("game_name") or "").strip()
                pending_edit_order_url = (pending.get("edit_order_url") or "").strip()
                if product_code:
                    lines = _parse_lines_json(lines_json)
                    options = json.loads(options_json) if options_json else {}
                    if isinstance(lines, list) and isinstance(options, dict):
                        cart = session.get("cart_items", [])
                        if not isinstance(cart, list):
                            cart = []
                        cart.append(
                            {
                                "kind": "single",
                                "product_code": product_code,
                                "lines": lines,
                                "options": options,
                                "game_code": pending_game_code or None,
                                "game_name": pending_game_name or None,
                            }
                        )
                        session["cart_items"] = cart
                        session["cart_edit_order_url"] = _resolve_edit_order_url(pending_edit_order_url)
                        if pending_game_code:
                            session["cart_last_game_code"] = pending_game_code
                        flash("Added your selected tickets to the cart.", "success")
                        return redirect(url_for("cart"))
            except Exception:
                # Ignore and continue with the normal redirect.
                pass

        return redirect(next_url)

    # --- keeping scripted sign-ups out ---
    #
    # Every control in this section is invisible to the person filling the form
    # in. That is a requirement, not a preference: the reactivation list runs to
    # 325,938 people with a median age of 71, and a challenge that a 71-year-old
    # fails costs more than the accounts it prevents. Bots signing up with
    # random letters are noise in the CRM and a distortion in the campaign
    # numbers - a reason to stop them, not a reason to start interrogating
    # customers.
    #
    # What they rely on instead is that a script is in a hurry and is not a
    # browser. It does not read a form before posting it, it does not fetch the
    # page it claims to be posting from, and it fills in fields a person cannot
    # see.

    _SIGNUP_FORM_SALT = "lottosonline:register-form"
    # And nobody is punished for being slow. Someone can open this form, take a
    # phone call, make a cup of tea and come back to it, so this is long enough
    # that it only ever catches a token being replayed days later - never a
    # customer who took their time. Being slow is not evidence of anything.
    _SIGNUP_MAX_SECONDS = 24 * 3600
    # Per-IP ceilings on account creation. Deliberately loose: a care home, a
    # library and anyone behind mobile CGNAT all share an address with hundreds
    # of legitimate people, so these are set where no plausible household or
    # institution reaches them and a script does so immediately.
    _SIGNUP_MAX_PER_HOUR = 6
    _SIGNUP_MAX_PER_DAY = 20
    # A field a browser hides and a person therefore leaves alone. Named so
    # that no password manager recognises it and helpfully fills it in - which
    # is what would happen to `website`, `url` or `company`.
    _SIGNUP_DECOY_FIELD = "signup_ref"

    def _signup_form_token() -> str:
        """A token proving a form came from us, and saying when we served it."""
        return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=_SIGNUP_FORM_SALT).dumps("register")

    def _signup_form_age_seconds(raw: str | None) -> float | None:
        """
        How long ago we served the form this was submitted from.

        None means we did not serve it: no token, a token we did not sign, or
        one so old it can only be a replay. A script posting straight at the
        endpoint has nothing to put here at all, which is the point - it has to
        fetch the page first, and then it has to wait.
        """
        if not raw:
            return None
        try:
            _payload, issued_at = URLSafeTimedSerializer(
                app.config["SECRET_KEY"], salt=_SIGNUP_FORM_SALT
            ).loads(str(raw), max_age=_SIGNUP_MAX_SECONDS, return_timestamp=True)
        except Exception:
            return None
        return (datetime.now(timezone.utc) - issued_at).total_seconds()

    def _signup_rate_limited(ip: str | None) -> str:
        """
        Which ceiling this address has already reached, or "" for none.

        Counted against account creations rather than form submissions, so
        somebody fumbling a password four times is not treated as a threat.
        """
        if not ip:
            return ""
        now = time.time()
        try:
            cache = get_cache()
            # Cheap here, and it keeps the table from growing without bound.
            cache.prune_signup_attempts(before=now - (2 * 24 * 3600))
            if cache.count_signup_attempts(ip, since=now - 3600) >= _SIGNUP_MAX_PER_HOUR:
                return "hour"
            if cache.count_signup_attempts(ip, since=now - (24 * 3600)) >= _SIGNUP_MAX_PER_DAY:
                return "day"
        except Exception as e:  # noqa: BLE001 - a broken counter must not close registration
            app.logger.warning("signup rate limit unavailable, allowing: %s", type(e).__name__)
        return ""

    _KEYBOARD_RUNS = ("qwert", "asdfg", "zxcvb", "yuiop", "hjkl", "12345")

    def _looks_typed_by_a_machine(text: str) -> str:
        """
        Why a name does not look like a name, or "" if it does.

        This only ever writes to the log. Real names defeat every rule anyone
        writes for this - they are short, they repeat letters, they come from
        languages and transliterations nobody thought about - and a customer
        turned away because an algorithm disliked their surname is a much worse
        outcome than a junk account in the CRM. So this gathers evidence and
        decides nothing.
        """
        raw = str(text or "").strip()
        if len(raw) < 4:
            return ""
        lowered = raw.lower()
        if not any(c in "aeiouy" for c in lowered) and lowered.isalpha():
            return "no vowels"
        if re.search(r"(.)\1{2,}", lowered):
            return "a letter three or more times over"
        for run in _KEYBOARD_RUNS:
            for length in range(4, len(run) + 1):
                if run[:length] in lowered:
                    return "a run of adjacent keys"
        return ""

    def _signup_looks_scripted(payload: dict[str, Any]) -> list[str]:
        notes: list[str] = []
        for field in ("first_name", "last_name"):
            why = _looks_typed_by_a_machine(payload.get(field) or "")
            if why:
                notes.append(f"{field}: {why}")
        local_part = str(payload.get("email") or "").split("@", 1)[0]
        why = _looks_typed_by_a_machine(local_part)
        if why:
            notes.append(f"email: {why}")
        return notes

    @app.get("/create-account")
    def register():
        # Emit signup_started once per session/journey.
        ctx = _mkt_ctx()
        stable_key = f"{ctx.get('tid') or _stable_key('mkt_signup_started_uuid')}:register"
        emit_marketing_event("signup_started", stable_key=stable_key)
        # Renders the legacy reCAPTCHA widget, and nothing more than that. The
        # answer is never sent to Google to be checked - there is no
        # `siteverify` call in this application - so it stops nobody who posts
        # at the endpoint directly, which is exactly what the sign-up bots do.
        # The controls above this route are what actually holds the door. Left
        # switchable for visual parity with the old site; if real verification
        # is ever wanted, Turnstile is the one that does not make a
        # 71-year-old identify motorbikes.
        recaptcha_enable = str(os.environ.get("RECAPTCHA_ENABLE") or "").strip() == "1"
        if recaptcha_enable:
            app.logger.warning(
                "RECAPTCHA_ENABLE is on, but this application never verifies the response - "
                "the widget is decorative and adds friction without adding protection"
            )
        # Countries list for the register page (CRM-driven, cached in SQLite).
        countries: list[dict[str, Any]] = []
        try:
            countries = get_cache().get_countries(active_only=True, include_blocked=False)
        except Exception:
            countries = []

        # If the cache is empty, attempt a quick best-effort refresh (brand-scoped via service key).
        if not countries and not _crm_cache_only_mode():
            try:
                resp = get_crm().countries(active_only=0, include_blocked=1)
                raw = resp.get("countries") if isinstance(resp, dict) else None
                if isinstance(raw, list):
                    get_cache().upsert_countries([c for c in raw if isinstance(c, dict)])
                    countries = get_cache().get_countries(active_only=True, include_blocked=False)
            except Exception:
                countries = countries or []

        # Optional preselect based on geo country, and the soft-block notice.
        # A soft-blocked country may browse and play, so the form is shown and
        # explained rather than hidden.
        default_country = None
        geo_restriction = "unknown"
        try:
            geo = getattr(g, "geo_country", None)
            if isinstance(geo, str) and re.fullmatch(r"[A-Z]{2}", geo):
                geo_restriction = _country_restriction(geo)
                if geo_restriction == "active":
                    default_country = geo
        except Exception:
            default_country = None
            geo_restriction = "unknown"

        # A former customer arriving from a reactivation link: their details
        # are filled in so that someone in their seventies is not asked to
        # retype twenty-year-old information, and every one of them stays
        # editable, because a name may have changed and this data is old.
        # Noted before the prefills run, because a dead invite is forgotten by
        # the time they return and this page was still reached by a URL with a
        # token in it. A token nobody will honour is still a token, and the
        # browser would hand this address to every asset host on the page.
        arrived_with_token = bool(_reactivation_token() or _legacy_signup_token())

        prefill = _reactivation_prefill()

        # A mail-order customer invited off the AS400. The CRM holds their
        # record and has already verified the address the invite was issued
        # against, so unlike a reactivation prefill this one brings an identity
        # with it and the email is not theirs to change here.
        legacy_prefill = _legacy_signup_prefill()
        if legacy_prefill:
            prefill = {**prefill, **legacy_prefill}
        legacy_invite = bool(legacy_prefill)

        # The country the CRM holds beats the country they happen to be
        # browsing from: it is what the record says, and they can still change
        # it. A soft-blocked geo still governs whether the form is offered.
        legacy_country = str(legacy_prefill.get("country") or "").strip().upper()
        if legacy_country and re.fullmatch(r"[A-Z]{2}", legacy_country):
            default_country = legacy_country
            # A customer the CRM has on file in Liverpool should not be offered
            # a euro account by default. Only three currencies exist here, so
            # this is the whole mapping; everywhere else keeps the existing
            # default, and the dropdown is theirs to change either way.
            if not legacy_prefill.get("currency"):
                prefill["currency"] = {"GB": "GBP", "US": "USD"}.get(legacy_country, "EUR")

        selected_currency = (session.pop("register_prefill_currency", None) or "").strip().upper()
        if not selected_currency:
            # The account's currency, not the offer's. A bundle is priced in
            # its own currency and that does not change.
            selected_currency = str(prefill.get("currency") or "").strip().upper() or "EUR"
        if selected_currency not in {"EUR", "USD", "GBP"}:
            selected_currency = "EUR"

        resp = make_response(
            render_template(
                "register.html",
                recaptcha_enable=recaptcha_enable,
                countries=countries,
                default_country=default_country,
                selected_currency=selected_currency,
                registration_blocked=(geo_restriction == "soft_block"),
                registration_blocked_message=REGISTRATION_SOFT_BLOCK_MESSAGE,
                signup_form_token=_signup_form_token(),
                signup_decoy_field=_SIGNUP_DECOY_FIELD,
                next=_safe_next_url(request.args.get("next"), ""),
                prefill_email=str(prefill.get("email") or "").strip(),
                prefill_first_name=str(prefill.get("first_name") or "").strip(),
                prefill_last_name=str(prefill.get("last_name") or "").strip(),
                prefill_birthdate=str(prefill.get("birthdate") or "").strip(),
                prefill_phone=str(prefill.get("phone") or "").strip(),
                # An invited customer's address is the identity the invite was
                # issued against and the one the CRM has verified. Shown, so
                # they know which account this is, and not editable, because
                # editing it would make it a different person's.
                legacy_invite=legacy_invite,
                # 34,521 of these records have no date of birth, and the CRM
                # only checks age when it is given one. On this path the form
                # is the only thing standing between an under-18 and an
                # account, until KYC.
                birthdate_required=legacy_invite,
                # A page carrying a token has to stay out of indexes and out of
                # the `Referer` of every asset it loads, whether or not the
                # token resolved to anything.
                noindex="noindex, nofollow" if arrived_with_token else None,
            )
        )
        return _protect_token_page(resp) if arrived_with_token else resp

    @app.get("/forgot-password")
    def forgot_password():
        return render_template("forgot_password.html")

    @app.post("/forgot-password")
    def forgot_password_post():
        email = (request.form.get("email") or "").strip()
        if not email:
            flash("Email is required.", "error")
            return redirect(url_for("forgot_password"))
        try:
            _ = get_crm().password_reset_request(email)
        except CRMError:
            # Anti-enumeration: always show success.
            pass
        flash("If the email exists, a reset link has been sent.", "success")
        return redirect(url_for("login"))

    @app.get("/verify-email")
    def verify_email():
        token = (request.args.get("token") or "").strip()
        if not token:
            return render_template(
                "verify_email.html",
                verify_success=False,
                verify_message="Missing verification token. Please request a new verification email.",
            )
        try:
            _ = get_crm().auth_email_verification_confirm(token)
        except CRMError as e:
            return render_template(
                "verify_email.html",
                verify_success=False,
                verify_message=_friendly_crm_error(e),
            )

        session["email_verified_hint"] = True
        session.pop("email_verify_banner_dismissed_at", None)
        return render_template(
            "verify_email.html",
            verify_success=True,
            verify_message="Your email has been verified successfully.",
        )

    @app.post("/verify-email/resend")
    def verify_email_resend():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("account")))
        customer = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        email = (customer.get("email") or "").strip() if isinstance(customer, dict) else ""
        if not email:
            try:
                me = get_crm().customer_me(token).get("customer")
                if isinstance(me, dict):
                    email = (me.get("email") or "").strip()
                    session["customer"] = me
            except CRMError:
                email = ""
        if not email:
            flash("We could not find your email. Please contact support.", "error")
            return redirect(url_for("account"))
        try:
            _ = get_crm().auth_email_verification_request(email)
        except CRMError:
            # Anti-enumeration style UX.
            pass
        flash("Verification email sent. Please check your inbox.", "success")
        return redirect(url_for("account"))

    @app.post("/verify-email/dismiss")
    def verify_email_dismiss():
        _ = require_login()
        session["email_verify_banner_dismissed_at"] = int(time.time())
        return redirect(url_for("account"))

    @app.get("/reset-password")
    def reset_password():
        token = (request.args.get("token") or "").strip()
        if token:
            session["password_reset_token"] = token
            # Strip token from URL per CRM guidance.
            return redirect(url_for("reset_password"))
        has_token = bool(session.get("password_reset_token"))
        return render_template("reset_password.html", has_token=has_token)

    @app.post("/reset-password")
    def reset_password_post():
        token = session.get("password_reset_token")
        if not token:
            flash("Missing reset token. Please request a new reset link.", "error")
            return redirect(url_for("forgot_password"))
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        if not new_password:
            flash("Password is required.", "error")
            return redirect(url_for("reset_password"))
        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_password"))
        try:
            _ = get_crm().password_reset_confirm(token=str(token), new_password=new_password)
        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
            return redirect(url_for("reset_password"))
        session.pop("password_reset_token", None)
        flash("Your password has been updated. Please sign in.", "success")
        return redirect(url_for("login"))

    # --- Setting a first password from a campaign link ---
    #
    # The Marketing Module creates customers who have never had a password and
    # sends them a campaign link carrying `spt`. This lets them pick a password
    # on the way to paying instead of registering from scratch. It is a
    # shortcut, never a gate: a missing or dead token leaves the ordinary login
    # and register journey exactly as it was.

    SET_PASSWORD_REASONS = {
        "mismatch": "Those passwords don't match. Please enter the same one twice.",
        "weak": (
            "Please choose a stronger password: at least 8 characters, with an uppercase "
            "letter, a lowercase letter, a digit and a special character."
        ),
        "used": "That link has already been used. Please sign in to finish your order.",
        "expired": "That link has expired. Please sign in to finish your order.",
        "has_password": "This account already has a password. Please sign in to finish your order.",
        "unknown": "We couldn't use that link. Please sign in to finish your order.",
    }
    # A bad password is worth another go at the form. Anything wrong with the
    # token itself cannot be fixed here, and leaving someone on a dead page with
    # a full cart is the one outcome this flow must not produce.
    SET_PASSWORD_RETRYABLE = {"mismatch", "weak"}

    def _set_password_token() -> str:
        raw = str(session.get("set_password_token") or "")
        return raw if re.fullmatch(r"[A-Za-z0-9._\-]{16,512}", raw) else ""

    def _reactivation_token() -> str:
        raw = str(session.get("reactivation_token") or "")
        return raw if re.fullmatch(r"[A-Za-z0-9._~=\-]{8,1024}", raw) else ""

    def _legacy_signup_token() -> str:
        raw = str(session.get("legacy_signup_token") or "")
        return raw if re.fullmatch(r"[A-Za-z0-9._~=\-]{8,1024}", raw) else ""

    def _legacy_signup_prefill() -> dict[str, Any]:
        """
        The CRM record behind a mail-order invite, or nothing.

        Unlike a reactivation prefill, a dead token here is worth saying out
        loud. That one quietly falls back to an empty form because the customer
        was only ever offered a convenience; this one promised them their
        details would be waiting, and a blank form with no explanation reads as
        the site having lost them.

        What it must not say is why. The CRM answers about a token and never
        about an address, so that someone holding a list of emails cannot use
        this to find out which of them are customers. A message here that
        distinguished "already claimed" from "no such invite" would hand back
        exactly what the endpoint refuses to give.
        """
        token = _legacy_signup_token()
        if not token:
            return {}
        try:
            body = get_crm().auth_legacy_signup_check(token)
        except Exception as e:  # noqa: BLE001 - never block a sign-up
            # The class only. A `requests` failure carries the URL it called,
            # and that URL has the token in it.
            reason = e.status_code if isinstance(e, CRMError) else type(e).__name__
            app.logger.info("legacy invite check declined: %s", reason)
            body = None

        prefill: dict[str, Any] = {}
        if isinstance(body, dict) and body.get("success") is not False:
            raw = body.get("prefill") if isinstance(body.get("prefill"), dict) else body
            if isinstance(raw, dict):
                prefill = {
                    k: raw.get(k)
                    for k in ("email", "first_name", "last_name", "birthdate",
                              "country", "phone", "currency")
                    if str(raw.get(k) or "").strip()
                }
        if not prefill.get("email"):
            # Without the verified address there is no identity to claim
            # against, so this is a dead invite however well-formed the answer
            # was. Drop the token: the form below still works, and the next
            # POST must not try to claim with it.
            session.pop("legacy_signup_token", None)
            flash("That invite link has expired. You can still sign up below.", "warning")
            return {}
        return prefill

    def _reactivation_prefill() -> dict[str, Any]:
        """
        The sign-up details behind this visitor's reactivation token, if any.

        Read from the Module each time rather than kept once in the session. The
        session is a signed cookie that travels on every request, and a name
        and a date of birth have no business riding in one when the Module will
        answer again for nothing. Repeat reads are explicitly allowed, which is
        also what makes a refresh or a back-button keep the prefill.

        Every way this can fail answers the same way - an empty dict, and an
        ordinary empty form. A token that expired, a Module that is down and a
        Module that is slow are all the same to a customer, and none of them is
        a reason to stop someone registering.
        """
        token = _reactivation_token()
        if not token:
            return {}
        client = get_mkt()
        if client is None:
            app.logger.info("reactivation prefill skipped: the Marketing Module is not configured")
            return {}
        try:
            body = client.prefill(g.brand.slug, token)
        except Exception as e:  # noqa: BLE001 - a prefill must never block a sign-up
            # The class only. A `requests` failure puts the URL it called in
            # its message, and that URL has the token in its query string.
            app.logger.warning("reactivation prefill unavailable, using an empty form: %s", type(e).__name__)
            return {}
        if not isinstance(body, dict) or not body.get("ok"):
            # Someone opening a forwarded email a month later is an expected
            # outcome, not a fault. The reason is safe to log; the token never
            # is.
            app.logger.info(
                "reactivation prefill declined: reason=%s",
                (body or {}).get("reason") if isinstance(body, dict) else "unreadable",
            )
            return {}
        # The Module names the campaign it sent this link for. Attribution
        # normally comes off the URL, and it is right there in the link - but a
        # link template that shipped without `cmp` would leave the campaign
        # unmeasurable while every other part of it worked, so take the
        # authoritative answer when the URL did not supply one.
        campaign = str(body.get("campaign") or "").strip()
        mkt = session.get("mkt") if isinstance(session.get("mkt"), dict) else {}
        if campaign and not mkt.get("cmp"):
            mkt["cmp"] = campaign
            session["mkt"] = mkt

        prefill = body.get("prefill")
        return prefill if isinstance(prefill, dict) else {}

    def _reactivation_registered() -> None:
        """
        Tells the Module a prefilled form was completed, then forgets the token.

        Measuring the drop-off between opening a prefilled form and finishing
        it is the only thing this does, so it is allowed to fail silently - but
        not to be skipped, because only the website knows when the second thing
        happened.
        """
        token = _reactivation_token()
        session.pop("reactivation_token", None)
        client = get_mkt()
        if not token or client is None:
            return
        try:
            client.prefill_registered(g.brand.slug, token)
        except Exception as e:  # noqa: BLE001 - nothing depends on this
            app.logger.info("reactivation completion not recorded: %s", type(e).__name__)

    def _protect_token_page(resp: Response) -> Response:
        # The token arrives in the URL, so without this the browser hands it to
        # every asset host in the `Referer` header, and a shared machine keeps
        # the page in its back button.
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/set-password")
    def set_password():
        # `spt` is captured on entry, so the token can leave the address bar,
        # the browser history and anything reading the URL.
        if request.args.get("spt"):
            return redirect(url_for("set_password", next=request.args.get("next") or None))

        next_url = _safe_next_url(request.args.get("next"), url_for("cart"))
        if not _set_password_token():
            flash("Please sign in to finish your order.", "warning")
            return redirect(url_for("login", next=next_url))

        return _protect_token_page(
            make_response(
                render_template("set_password.html", next=next_url, noindex="noindex, nofollow")
            )
        )

    @app.post("/set-password")
    def set_password_post():
        next_url = _safe_next_url(request.form.get("next"), url_for("cart"))
        token = _set_password_token()
        if not token:
            flash("Please sign in to finish your order.", "warning")
            return redirect(url_for("login", next=next_url))

        password = request.form.get("password") or ""
        confirm = request.form.get("password_confirm") or ""
        if not password or password != confirm:
            flash(SET_PASSWORD_REASONS["mismatch" if password else "weak"], "error")
            return redirect(url_for("set_password", next=next_url))

        def _give_up(reason: str):
            session.pop("set_password_token", None)
            flash(SET_PASSWORD_REASONS.get(reason) or SET_PASSWORD_REASONS["unknown"], "warning")
            return redirect(url_for("login", next=next_url))

        try:
            data = get_crm().auth_set_password(token=token, password=password, password_confirm=confirm)
        except CRMError as e:
            reason = ""
            if isinstance(getattr(e, "payload", None), dict):
                reason = str(e.payload.get("reason") or "").strip().lower()
            # The reason is safe to log. The token never is.
            app.logger.info("set-password refused: reason=%s", reason or "unspecified")
            if reason in SET_PASSWORD_RETRYABLE:
                flash(SET_PASSWORD_REASONS[reason], "error")
                return redirect(url_for("set_password", next=next_url))
            return _give_up(reason)

        bearer = str((data or {}).get("token") or "") if isinstance(data, dict) else ""
        if not bearer:
            app.logger.warning("set-password succeeded without a bearer; keys=%s", sorted(data) if isinstance(data, dict) else type(data).__name__)
            return _give_up("unknown")

        # This is an ordinary login bearer, so it is stored exactly as a login
        # stores one. No confirmation page: the point of the shortcut is that
        # they land on payment.
        session.pop("set_password_token", None)
        session["crm_token"] = bearer
        session["time_on_site_started_at"] = int(time.time())
        session.pop("wallet", None)
        # Their own bearer, their own account: no longer a support session.
        session.pop("customer_login_as", None)
        customer: dict[str, Any] = {}
        try:
            me = get_crm().auth_me(bearer)
            if isinstance(me, dict) and isinstance(me.get("customer"), dict):
                customer = me["customer"]
        except Exception:
            customer = {}
        if not customer:
            # A signed-in session with no profile still beats losing the order;
            # the account page fills the rest in on its next call.
            customer_id = (data or {}).get("customer_id")
            customer = {"id": customer_id} if customer_id is not None else {}
        session["customer"] = customer
        return redirect(next_url)

    @app.post("/create-account")
    def register_post():
        selected_currency = (request.form.get("currency") or "").strip().upper() or "EUR"
        allowed_currencies = {"EUR", "USD", "GBP"}
        selected_title = (request.form.get("title") or "").strip()
        allowed_titles = {"Mr", "Ms", "Mrs"}
        session["register_prefill_currency"] = selected_currency
        # Where registering was meant to lead. A customer who came here to buy
        # an offer is mid-purchase, and landing them on their account page
        # loses the cart they built - so every way out of this handler carries
        # it, including the ones that send them back to fix the form.
        next_url = _safe_next_url(request.form.get("next"), "")

        def _back_to_form():
            return redirect(url_for("register", next=next_url or None))

        def _refuse_signup():
            """
            Turns a submission away without telling a script what it got wrong.

            A real person should never see this, but if one ever does it has to
            be something they can act on, so it says to reload rather than
            implying they did something suspicious.
            """
            flash(
                "We could not confirm this form came from our website. "
                "Please reload the page and try again.",
                "error",
            )
            return _back_to_form()

        # A script does not fetch the page before posting to it, does not wait,
        # and does not leave a hidden field alone. None of these three can be
        # noticed by someone filling the form in honestly, which is the whole
        # requirement. They are checked before anything else so a scripted post
        # costs us no CRM call.
        if (request.form.get(_SIGNUP_DECOY_FIELD) or "").strip():
            app.logger.info("signup refused: a field only a script can see was filled in")
            return _refuse_signup()
        form_age = _signup_form_age_seconds(request.form.get("form_token"))
        if form_age is None:
            app.logger.info("signup refused: not submitted from a form we served")
            return _refuse_signup()
        if form_age < float(app.config["SIGNUP_MIN_SECONDS"]):
            app.logger.info("signup refused: form completed in %.2fs", form_age)
            return _refuse_signup()

        if selected_currency not in allowed_currencies:
            flash("Please select a valid currency (EUR, USD, or GBP).", "error")
            return _back_to_form()
        if selected_title and selected_title not in allowed_titles:
            flash("Please select a valid title.", "error")
            return _back_to_form()
        if not request.form.get("accept_terms"):
            flash("You must confirm you are over 18 and accept the terms to create an account.", "error")
            return _back_to_form()

        # Country enforcement. Geo says where they are, the form says where they
        # claim to be, and a restriction has to cover both or it only stops the
        # honest half.
        selected_country = (request.form.get("country") or "").strip().upper()
        restrictions = [_country_restriction(getattr(g, "geo_country", None))]
        if selected_country:
            restrictions.append(_country_restriction(selected_country))

        if "block_website" in restrictions:
            blocked_code = selected_country if _country_restriction(selected_country) == "block_website" else None
            flash("Sorry, we are not able to provide services in your country.", "error")
            return _blocked_country_response(blocked_code or getattr(g, "geo_country", None))

        if "soft_block" in restrictions:
            # A soft block stops new accounts only. Everything else on the site
            # stays open, so this returns to the form rather than the door.
            flash(REGISTRATION_SOFT_BLOCK_MESSAGE, "error")
            return _back_to_form()

        payload = {
            "title": selected_title or "Mr",
            "first_name": (request.form.get("first_name") or "").strip(),
            "last_name": (request.form.get("last_name") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "password": request.form.get("password") or "",
            "phone": (request.form.get("phone") or "").strip() or None,
            "birthdate": (request.form.get("birthdate") or "").strip() or None,
            "currency": selected_currency,
        }
        # Website Processor Rules route wallet payments on the persisted CRM
        # country, and the CRM parses the phone using it as the preferred
        # region, so save it at signup rather than waiting for first checkout.
        # What they chose, or failing that where they are: the CRM wants the
        # country on every registration it can get one for.
        known_country = selected_country or str(getattr(g, "geo_country", "") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", known_country or ""):
            payload["country"] = known_country
        # An invited customer has no password box to fill in: the claim does not
        # take one, and the CRM answers it with a set-password token instead.
        # The address is not asked for either - the CRM keeps the one it
        # verified - so demanding either here would refuse a claim that is
        # perfectly good.
        invited = bool(_legacy_signup_token())
        missing_identity = not payload["first_name"] or not payload["last_name"]
        if missing_identity or (not invited and (not payload["email"] or not payload["password"])):
            flash(
                "First name and last name are required."
                if invited
                else "First name, last name, email, and password are required.",
                "error",
            )
            return _back_to_form()

        # The AS400 id, which is the only thing tying this new account to
        # fifteen years of purchase history. Read from the Module again rather
        # than carried through the form: a hidden field would let anyone claim
        # somebody else's history by editing it.
        #
        # Read before attribution, not after, because this is also where the
        # Module names the campaign it sent the link for.
        customer_number = str(_reactivation_prefill().get("customer_number") or "").strip()
        if customer_number:
            payload["customer_number"] = customer_number

        # Marketing attribution fields supported by the register API.
        mkt = _mkt_ctx()
        if mkt.get("tid"):
            payload["acquisition_click_id"] = str(mkt["tid"])[:64]
        if mkt.get("src") and mkt.get("intent") != "lifecycle":
            payload["acquisition_source_code"] = mkt["src"]
        if mkt.get("cmp"):
            payload["acquisition_campaign_code"] = mkt["cmp"]

        # Counted here rather than at the top of the handler so that it measures
        # accounts being created, not forms being corrected.
        client_ip = _client_ip()
        reached = _signup_rate_limited(client_ip)
        if reached:
            # Loudly, and with the address, because this is the one control
            # here that can catch real people: a care home or a mobile network
            # puts hundreds of customers behind one address. If this line ever
            # appears for an address that is not a script, the ceiling is wrong.
            app.logger.warning(
                "signup refused: %s has reached the limit of %s accounts per %s",
                client_ip,
                _SIGNUP_MAX_PER_HOUR if reached == "hour" else _SIGNUP_MAX_PER_DAY,
                reached,
            )
            flash(
                "We have had several accounts created from your connection recently. "
                "Please try again later, or contact us and we will set it up for you.",
                "error",
            )
            return _back_to_form()

        # Evidence only. Nothing below this decides anything, so a surname an
        # algorithm dislikes cannot cost a customer their account - but when
        # somebody asks how many of last week's sign-ups were junk, and what
        # the junk looked like, the answer is in the log.
        scripted_notes = _signup_looks_scripted(payload)
        if scripted_notes:
            app.logger.info(
                "signup looks machine-typed but was allowed: %s (ip=%s, form filled in %.0fs)",
                "; ".join(scripted_notes),
                client_ip or "-",
                form_age,
            )

        def _claim_legacy_invite(token: str):
            """
            Turns an invite into an account, or gets out of the way.

            The email is not sent. The CRM holds one it has already verified
            for this record, and the whole point of an invite is that the token
            proves who this is - so nothing typed into the browser, including
            into a read-only field somebody reopened in devtools, can move the
            account to a different address.

            Returns a response when it has settled the matter, and None when
            the customer should carry on as an ordinary sign-up. Every failure
            takes the second road: an invite that will not claim is our problem
            and they should still be able to get an account.
            """
            claim = {
                "token": token,
                "first_name": payload["first_name"],
                "last_name": payload["last_name"],
                "birthdate": payload["birthdate"],
                "currency": payload["currency"],
            }
            if payload.get("phone"):
                claim["phone"] = payload["phone"]
            if payload.get("country"):
                claim["country"] = payload["country"]

            try:
                body = get_crm().auth_legacy_signup_claim(claim)
            except CRMError as e:
                session.pop("legacy_signup_token", None)
                crm_message = ""
                if isinstance(getattr(e, "payload", None), dict):
                    crm_message = str(e.payload.get("error") or "").strip()
                app.logger.warning("legacy invite claim refused (HTTP %s), falling back to registration", e.status_code)
                flash(crm_message or _friendly_crm_error(e), "error")
                return None
            except Exception as e:  # noqa: BLE001 - the token is in the URL a client error would quote
                session.pop("legacy_signup_token", None)
                app.logger.warning("legacy invite claim unavailable: %s", type(e).__name__)
                return None

            # The claim issues a short-lived set-password token instead of a
            # bearer, because the account exists but has no password yet. The
            # field name is not in any published contract, so read it the way
            # the payment redirects are read: take whichever one is there
            # rather than fail on a synonym.
            data = body if isinstance(body, dict) else {}
            spt = ""
            for key in ("spt", "set_password_token", "token", "password_token"):
                candidate = str(data.get(key) or "").strip()
                if candidate and re.fullmatch(r"[A-Za-z0-9._\-]{16,512}", candidate):
                    spt = candidate
                    break
            if not spt:
                session.pop("legacy_signup_token", None)
                app.logger.error(
                    "legacy invite claim succeeded but returned no usable set-password token "
                    "(keys: %s) - the customer cannot finish, so they are being registered instead",
                    ",".join(sorted(str(k) for k in data.keys())) or "none",
                )
                return None

            if client_ip:
                try:
                    get_cache().record_signup_attempt(client_ip, at=time.time())
                except Exception as e:  # noqa: BLE001 - an account exists; this is bookkeeping
                    app.logger.warning("could not record signup for rate limiting: %s", type(e).__name__)

            claimed = data.get("customer") if isinstance(data.get("customer"), dict) else {}
            cust_id = claimed.get("id")
            if cust_id is not None:
                emit_marketing_event("signup_completed", stable_key=str(cust_id), customer_id=int(cust_id))
            app.logger.info(
                "legacy invite claimed: customer=%s",
                cust_id if cust_id is not None else "?",
            )

            session.pop("legacy_signup_token", None)
            session.pop("register_prefill_currency", None)
            # Handed over exactly as an emailed set-password link would be, so
            # there is one implementation of choosing a first password.
            session["set_password_token"] = spt
            return redirect(url_for("set_password", next=next_url or None))

        legacy_token = _legacy_signup_token()
        if legacy_token:
            # The CRM refuses under-18s only when it is given a date to judge,
            # and a third of these records have none. Until KYC, this is the
            # only age check there is.
            if not payload.get("birthdate"):
                flash("Please enter your date of birth to continue.", "error")
                return _back_to_form()
            claimed_response = _claim_legacy_invite(legacy_token)
            if claimed_response is not None:
                return claimed_response
            # The invite did not open. The token is gone, so what follows is an
            # ordinary sign-up - but an invited form never showed a password
            # box or asked them to type their address, so there may be nothing
            # to register with. Showing them the full form is a poor end to a
            # broken invite and still a far better one than a refusal.
            if not payload["password"] or not payload["email"]:
                flash("Please fill in the form below to create your account.", "warning")
                return _back_to_form()

        def _register():
            """
            Registers, and does not let the AS400 id be what stops it.

            `customer_number` is not in the register contract (API 67) even
            though the column exists, so a CRM that rejects unknown fields
            would turn away every one of the 325,938 people this campaign is
            for. An account that needs its history linked by hand afterwards
            is a far smaller problem, and the retry is loud so it is never a
            silent loss.
            """
            try:
                return get_crm().auth_register(payload)
            except CRMError as e:
                if not customer_number or "customer_number" not in str(e).lower():
                    raise
                app.logger.error("CRM refused customer_number on registration, retrying without it: %s", e)
                payload.pop("customer_number", None)
                return get_crm().auth_register(payload)

        try:
            data = _register()
        except CRMError as e:
            # The CRM enforces the same country rules and says which one it
            # applied. Its wording is the customer-facing message; `restriction`
            # decides where they end up.
            restriction = ""
            crm_message = ""
            if isinstance(getattr(e, "payload", None), dict):
                restriction = str(e.payload.get("restriction") or "").strip().lower()
                crm_message = str(e.payload.get("error") or "").strip()
            if restriction == "block_website":
                return _blocked_country_response(selected_country or getattr(g, "geo_country", None))
            if restriction == "soft_block":
                flash(crm_message or REGISTRATION_SOFT_BLOCK_MESSAGE, "error")
                return _back_to_form()

            # Known CRM issue: registering with a phone number that already
            # belongs to another account crashes the CRM with a 500 instead of
            # a clean validation error. Give the customer an actionable hint.
            if e.status_code == 500 and payload.get("phone"):
                flash(
                    "We couldn't create your account. If this phone number was used for "
                    "another account, please use a different phone number or leave the "
                    "phone field empty.",
                    "error",
                )
            else:
                flash(_friendly_crm_error(e), "error")
            return _back_to_form()

        if client_ip:
            try:
                get_cache().record_signup_attempt(client_ip, at=time.time())
            except Exception as e:  # noqa: BLE001 - an account exists; this is bookkeeping
                app.logger.warning("could not record signup for rate limiting: %s", type(e).__name__)

        session.pop("register_prefill_currency", None)
        session["crm_token"] = data.get("token")
        session["customer"] = data.get("customer")
        # Their own bearer, their own account: no longer a support session.
        session.pop("customer_login_as", None)
        cust_id = None
        if isinstance(data.get("customer"), dict):
            cust_id = data["customer"].get("id")
        if cust_id is not None:
            emit_marketing_event("signup_completed", stable_key=str(cust_id), customer_id=int(cust_id))
        if customer_number:
            # The register response is the only chance to see whether the id
            # actually stuck. If the CRM accepted the field and dropped it, a
            # reactivated customer looks brand new for ever, and nobody would
            # notice without this line.
            saved = data.get("customer") if isinstance(data.get("customer"), dict) else {}
            if str(saved.get("customer_number") or "").strip() != customer_number:
                app.logger.error(
                    "registration did not keep customer_number: sent %s, customer %s came back with %r "
                    "- this account is not linked to its AS400 history",
                    customer_number,
                    cust_id if cust_id is not None else "?",
                    saved.get("customer_number"),
                )
        _reactivation_registered()
        # Email verification is non-blocking; best-effort send verification email after signup.
        try:
            _ = get_crm().auth_email_verification_request(str(payload["email"]))
        except CRMError:
            pass
        session["email_verified_hint"] = False
        flash("Account created.", "success")
        return redirect(next_url or url_for("account"))

    # --- Customer support sessions: staff viewing the site as a customer ---
    #
    # CRM staff with the right permission open this site as a customer without
    # their password. The CRM sends the staff browser here with a handoff that
    # is brand-bound, single-use and good for two minutes; this end trades it
    # for a customer bearer token that the CRM restricts to reads.

    _SUPPORT_HANDOFF_RE = re.compile(r"[A-Za-z0-9._~=\-]{16,1024}")
    # The CRM's own ceiling for one of these sessions. Used when the exchange
    # does not say, and as a cap on what it does say.
    _SUPPORT_SESSION_MAX_SECONDS = 3600
    SUPPORT_READ_ONLY_MESSAGE = "This customer support session is read-only."
    SUPPORT_BANNER_MESSAGE = (
        "Read-only customer support session. You are viewing the website as this customer. "
        "Purchases, wallet changes, saved-item changes, and account updates are blocked."
    )

    def _support_handoff_refused(audit_id: str, reason: str, *, status: int = 400):
        """
        One page for every way a handoff can fail, saying nothing about which.

        A staff member needs to know the link is no good and to fetch another;
        distinguishing expired from already-used from wrong-brand out loud
        would describe the state of a credential to whoever holds the URL.
        """
        app.logger.warning(
            "login-as handoff refused: audit=%s reason=%s",
            audit_id or "-",
            reason,
        )
        return _protect_token_page(
            make_response(
                render_template(
                    "support_login_as_invalid.html",
                    noindex="noindex, nofollow",
                    no_analytics=True,
                ),
                status,
            )
        )

    @app.get("/support/login-as/<audit_id>")
    def support_login_as(audit_id: str):
        # Exchanged here and now. The handoff lives for two minutes and once
        # only, so there is nothing to gain by holding it and a great deal to
        # lose: parked in a session it becomes a credential we are storing on
        # a staff member's behalf, for a customer who is not them.
        raw_token = str(request.args.get("token") or "").strip()
        audit_raw = str(audit_id or "").strip()
        if not raw_token or not _SUPPORT_HANDOFF_RE.fullmatch(raw_token):
            return _support_handoff_refused(audit_raw, "missing or malformed token")
        if not re.fullmatch(r"\d{1,19}", audit_raw):
            return _support_handoff_refused(audit_raw, "audit id is not an integer")

        try:
            data = get_crm().auth_login_as_customer(
                audit_id=int(audit_raw),
                token=raw_token,
                ip=_client_ip() or None,
            )
        except CRMError as e:
            # 400/401/403/404/409 are all the documented ways this ends, and
            # anything else is an outage. Neither is recoverable from here and
            # both are the same sentence to the person holding the link.
            return _support_handoff_refused(
                audit_raw,
                f"CRM refused the exchange (HTTP {e.status_code or 'unknown'})",
                status=403 if e.status_code in {401, 403, 409} else 400,
            )
        except Exception as e:  # noqa: BLE001 - never leak the URL in a traceback
            return _support_handoff_refused(audit_raw, f"exchange failed: {type(e).__name__}")

        customer_token = str((data or {}).get("token") or "").strip() if isinstance(data, dict) else ""
        if not customer_token:
            return _support_handoff_refused(audit_raw, "exchange returned no customer token")

        support = data.get("support_session") if isinstance(data.get("support_session"), dict) else {}
        try:
            ttl = int(support.get("expires_in_seconds") or _SUPPORT_SESSION_MAX_SECONDS)
        except Exception:
            ttl = _SUPPORT_SESSION_MAX_SECONDS
        ttl = max(60, min(ttl, _SUPPORT_SESSION_MAX_SECONDS))

        # Whatever this browser was signed in to, it is not this customer.
        # Their cart, wallet cache and staged billing address all go, or the
        # support session shows one customer's things under another's name.
        _clear_customer_session()
        for key in ("mkt", "mkt_click_uuid", "mkt_pageview_uuid", "mkt_signup_started_uuid"):
            session.pop(key, None)

        session["crm_token"] = customer_token
        session["customer"] = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        session["customer_login_as"] = {
            # Absent means read-only. The CRM only issues these read-only, and
            # a missing flag is not a reason to hand someone write access to
            # an account that is not theirs.
            "read_only": support.get("read_only") is not False,
            "audit_id": int(audit_raw),
            "expires_at": int(time.time()) + ttl,
        }
        app.logger.info(
            "login-as support session opened: audit=%s customer=%s read_only=%s ttl=%ss",
            audit_raw,
            (session["customer"] or {}).get("id") if isinstance(session.get("customer"), dict) else "-",
            session["customer_login_as"]["read_only"],
            ttl,
        )

        # Straight to a clean URL, so the handoff is gone from the address bar,
        # the back button and the Referer of every asset the next page loads.
        resp = redirect(url_for("account"))
        return _protect_token_page(make_response(resp))

    @app.before_request
    def _support_session_blocks_writes():
        """
        The server half of read-only, and the half that counts.

        Hidden buttons are a courtesy; this is the guarantee. The CRM refuses
        writes on a support token anyway, but plenty of this site changes the
        session without asking the CRM anything - adding to a cart, applying a
        promo code, staging a billing address - and none of that should happen
        to a customer because support looked at their account.
        """
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        # The admin console has its own gate and its own credential. A support
        # marker is about a customer, and must not lock staff out of it.
        if request.path.startswith("/admin"):
            return None
        # Signing in replaces this session rather than writing to it, and
        # blocking it would trap the browser: the marker outlives the tab, so
        # the next person at that desk could not log in as themselves.
        if request.path == "/login":
            return None
        if not _support_session_active():
            return None

        app.logger.info(
            "support session blocked a write: %s %s",
            request.method,
            _analytics_safe_path(request.path),
        )
        wants_json = request.path.startswith("/api/") or "application/json" in str(
            request.headers.get("Accept") or ""
        )
        if wants_json:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": SUPPORT_READ_ONLY_MESSAGE,
                        "error_code": "SUPPORT_SESSION_READ_ONLY",
                    }
                ),
                403,
            )
        flash(SUPPORT_READ_ONLY_MESSAGE, "warning")
        return redirect(_safe_next_url(request.referrer, url_for("account")))

    @app.get("/logout")
    def logout():
        session.pop("crm_token", None)
        session.pop("customer", None)
        session.pop("email_verified_hint", None)
        session.pop("email_verify_banner_dismissed_at", None)
        # A support session ends with the customer it was about. Left behind,
        # the banner and the write block would follow the next person to sign
        # in on this browser.
        session.pop("customer_login_as", None)
        flash("Signed out.", "success")
        return redirect(url_for("home"))

    @app.get("/account")
    def account():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("account")))
        txn_filters = session.get("acct_txn_filters") if isinstance(session.get("acct_txn_filters"), dict) else {}
        order_filters = session.get("acct_order_filters") if isinstance(session.get("acct_order_filters"), dict) else {}
        winnings_filters = session.get("acct_winnings_filters") if isinstance(session.get("acct_winnings_filters"), dict) else {}
        notif_prefs = session.get("acct_notification_prefs") if isinstance(session.get("acct_notification_prefs"), dict) else {}
        dismissed_at = session.get("email_verify_banner_dismissed_at")
        dismissed_recently = False
        try:
            dismissed_recently = bool(dismissed_at) and (int(time.time()) - int(dismissed_at)) < (7 * 24 * 3600)
        except Exception:
            dismissed_recently = False
        show_email_verify_banner = not bool(session.get("email_verified_hint")) and not dismissed_recently

        # Legacy UX: show first 5 matching rows and "Load more" reveals 5 more.
        txn_show = int(session.get("acct_txn_show") or 5)
        order_show = int(session.get("acct_order_show") or 5)
        winnings_show = int(session.get("acct_winnings_show") or 5)

        def _parse_date(s: str | None) -> datetime.date | None:
            raw = (s or "").strip()
            if not raw:
                return None
            # Most common: YYYY-MM-DD (daterangepicker locale format)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                try:
                    return datetime.strptime(raw, "%Y-%m-%d").date()
                except Exception:
                    return None
            # Legacy/JS callback sometimes uses "Jan 2, 2026"
            for fmt in ("%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except Exception:
                    pass
            return None

        def _parse_date_range(s: str | None) -> tuple[datetime.date | None, datetime.date | None]:
            raw = (s or "").strip()
            if not raw or " - " not in raw:
                return None, None
            a_raw, b_raw = [p.strip() for p in raw.split(" - ", 1)]
            return _parse_date(a_raw), _parse_date(b_raw)

        def _created_date(v: str | None) -> datetime.date | None:
            raw = (v or "").strip()
            if not raw:
                return None
            # ISO-like: 2026-01-02T... or 2026-01-02 ...
            head = raw[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head):
                try:
                    return datetime.strptime(head, "%Y-%m-%d").date()
                except Exception:
                    return None
            # Fallback: try ISO parser (handles "2026-01-02 12:34:56" on some builds)
            try:
                cleaned = raw.replace("Z", "+00:00")
                return datetime.fromisoformat(cleaned).date()
            except Exception:
                return None

        def _date_in_range(d: str | None, a: datetime.date | None, b: datetime.date | None) -> bool:
            if not a or not b:
                return True
            dd = _created_date(d)
            if dd is None:
                # If we can't parse the CRM date reliably, don't hide the row.
                return True
            return a <= dd <= b

        def _txn_matches(t: dict, *, a: datetime.date | None, b: datetime.date | None, typ_code: str | None, status_code: str | None) -> bool:
            created = (t.get("created_at") or t.get("createdAt") or "").strip()
            if not _date_in_range(created, a, b):
                return False

            typ = str(t.get("type") or t.get("kind") or t.get("transaction_type") or "").strip().lower()
            if typ_code:
                # Legacy codes from account.js: 0 deposit, 4 order(play), 6 win, 2 adjustment, 1 withdrawal
                want = str(typ_code).strip()
                if want == "0" and "deposit" not in typ:
                    return False
                if want == "4" and not any(k in typ for k in ("order", "play", "purchase")):
                    return False
                if want == "6" and "win" not in typ:
                    return False
                if want == "2" and "adjust" not in typ:
                    return False
                if want == "1" and "withdraw" not in typ:
                    return False

            st = str(t.get("status") or "").strip().lower()
            if status_code:
                want = str(status_code).strip()
                if want == "1" and not any(k in st for k in ("success", "succeeded", "completed", "paid")):
                    return False
                if want == "7" and not any(k in st for k in ("fail", "failed", "declined", "error")):
                    return False
                if want == "4" and not any(k in st for k in ("pending", "processing")):
                    return False
            return True

        def _order_matches(o: dict, *, a: datetime.date | None, b: datetime.date | None, order_id: str | None) -> bool:
            created = (o.get("created_at") or o.get("createdAt") or "").strip()
            if not _date_in_range(created, a, b):
                return False
            if order_id:
                oid = str(o.get("id") or "").strip()
                if oid and oid != str(order_id).strip():
                    return False
            return True

        try:
            me = get_crm().customer_me(token).get("customer")
            wallet = get_crm().wallet(token).get("wallet")
            if isinstance(wallet, dict):
                session["wallet"] = wallet

            def _money_str(cents: int) -> str:
                try:
                    return f"{(int(cents) / 100):.2f}"
                except Exception:
                    return "0.00"

            def _intish(v: Any) -> int | None:
                try:
                    if v is None:
                        return None
                    return int(v)
                except Exception:
                    return None

            def _get_amt_cents(t: dict) -> int:
                v = t.get("amount_cents")
                if v is None:
                    v = t.get("amountCents")
                if v is None:
                    v = t.get("amount")
                n = _intish(v)
                if n is None:
                    try:
                        return int(round(float(v or 0) * 100))
                    except Exception:
                        return 0
                return int(n)

            def _txn_code(t: dict) -> int | None:
                for k in ("transactionTypeCode", "transaction_type_code", "type_code", "typeCode"):
                    v = t.get(k)
                    n = _intish(v)
                    if n is not None:
                        return n
                return None

            def _txn_typ_str(t: dict) -> str:
                return str(t.get("type") or t.get("kind") or t.get("transaction_type") or "").strip().lower()

            def _txn_status_str(t: dict) -> str:
                return str(t.get("status") or "").strip().lower()

            # --- Transaction Summary (legacy parity) ---
            # Legacy site calls a summary endpoint and caches it hourly.
            # We compute a best-effort summary from wallet transactions and cache in session for 1 hour.
            currency_code = (wallet.get("currency") if isinstance(wallet, dict) else "") or ""
            currency_symbol = _currency_symbol(str(currency_code))
            txn_summary = session.get("acct_txn_summary") if isinstance(session.get("acct_txn_summary"), dict) else None
            now_ts = int(time.time())
            summary_is_fresh = False
            if isinstance(txn_summary, dict):
                try:
                    ts = int(txn_summary.get("ts") or 0)
                    summary_is_fresh = (now_ts - ts) < 3600 and str(txn_summary.get("currency") or "") == str(currency_code)
                except Exception:
                    summary_is_fresh = False

            if not summary_is_fresh:
                # Aggregate across wallet transactions (best-effort bounded scan).
                dep_cnt = dep_amt = 0
                wd_cnt = wd_amt = 0
                win_cnt = win_amt = 0
                loss_cnt = loss_amt = 0
                settled_cnt = settled_amt = 0
                unsettled_cnt = unsettled_amt = 0

                per_page = 200
                max_pages = 50  # safety bound; legacy updates hourly, we keep this fast
                for page in range(1, max_pages + 1):
                    resp = get_crm().wallet_transactions(token, page=page, per_page=per_page)
                    items = resp.get("transactions") if isinstance(resp, dict) else None
                    if not isinstance(items, list) or not items:
                        break
                    for t in items:
                        if not isinstance(t, dict):
                            continue
                        code = _txn_code(t)
                        typ = _txn_typ_str(t)
                        st = _txn_status_str(t)
                        amt = abs(_get_amt_cents(t))

                        # Prefer numeric codes if available (legacy mapping).
                        if code == 0 or ("deposit" in typ):
                            dep_cnt += 1
                            dep_amt += amt
                            continue
                        if code == 1 or ("withdraw" in typ):
                            wd_cnt += 1
                            wd_amt += amt
                            continue
                        if code == 6 or ("win" in typ):
                            win_cnt += 1
                            win_amt += amt
                            continue
                        if code == 10 or ("lose" in typ or "loss" in typ):
                            loss_cnt += 1
                            loss_amt += amt
                            continue
                        if code == 8:
                            settled_cnt += 1
                            settled_amt += amt
                            continue
                        if code == 9:
                            unsettled_cnt += 1
                            unsettled_amt += amt
                            continue

                        # Fallback: treat order/play as "bet", and infer settled state from status.
                        if code == 4 or any(k in typ for k in ("order", "play", "purchase", "bet")):
                            if any(k in st for k in ("pending", "processing", "unsettled", "open")):
                                unsettled_cnt += 1
                                unsettled_amt += amt
                            else:
                                settled_cnt += 1
                                settled_amt += amt

                txn_summary = {
                    "ts": now_ts,
                    "currency": currency_code,
                    "currency_symbol": currency_symbol,
                    "deposits_count": dep_cnt,
                    "deposits_amount": _money_str(dep_amt),
                    "withdrawals_count": wd_cnt,
                    "withdrawals_amount": _money_str(wd_amt),
                    "net_deposit": _money_str(dep_amt - wd_amt),
                    "wins_count": win_cnt,
                    "wins_amount": _money_str(win_amt),
                    "losses_count": loss_cnt,
                    "losses_amount": _money_str(loss_amt),
                    "plays_settled_count": settled_cnt,
                    "plays_unsettled_count": unsettled_cnt,
                    "plays_settled_amount": _money_str(settled_amt),
                    "plays_unsettled_amount": _money_str(unsettled_amt),
                }
                session["acct_txn_summary"] = txn_summary
            # Emulate legacy behavior: run a server-side search by paging through CRM until we
            # have enough matches to render (N) plus one extra to decide if "Load More" shows.
            ta, tb = _parse_date_range(txn_filters.get("date_range"))
            oa, ob = _parse_date_range(order_filters.get("date_range"))
            wa, wb = _parse_date_range(winnings_filters.get("date_range"))

            def _collect_txn_matches(*, want_n: int, a: str | None, b: str | None, typ_code: str | None, status_code: str | None) -> tuple[list[dict], bool]:
                per_page = 200
                max_pages = 200
                out: list[dict] = []
                page = 1
                is_sorted_desc = True
                while page <= max_pages:
                    resp = get_crm().wallet_transactions(token, page=page, per_page=per_page)
                    items = resp.get("transactions") if isinstance(resp, dict) else None
                    if not isinstance(items, list) or not items:
                        break
                    # Detect if page seems sorted newest->oldest (string compare on yyyy-mm-dd).
                    try:
                        first = str((items[0] or {}).get("created_at") or (items[0] or {}).get("createdAt") or "")[:10]
                        last = str((items[-1] or {}).get("created_at") or (items[-1] or {}).get("createdAt") or "")[:10]
                        if first and last and first < last:
                            is_sorted_desc = False
                    except Exception:
                        is_sorted_desc = False

                    for t in items:
                        if not isinstance(t, dict):
                            continue
                        if _txn_matches(t, a=a, b=b, typ_code=typ_code, status_code=status_code):
                            out.append(t)
                            if len(out) >= want_n:
                                return out[:want_n], True

                    # If we're filtering by date and the feed is sorted desc, we can stop once
                    # we are older than the start date (no further matches possible).
                    if is_sorted_desc and a and b:
                        try:
                            oldest = str((items[-1] or {}).get("created_at") or (items[-1] or {}).get("createdAt") or "")[:10]
                            if oldest and re.fullmatch(r"\d{4}-\d{2}-\d{2}", oldest) and oldest < a:
                                break
                        except Exception:
                            pass

                    if len(items) < per_page:
                        break
                    page += 1
                return out, False

            def _collect_order_matches(*, want_n: int, a: str | None, b: str | None, order_id: str | None) -> tuple[list[dict], bool]:
                per_page = 200
                max_pages = 200
                out: list[dict] = []
                page = 1
                is_sorted_desc = True
                while page <= max_pages:
                    resp = get_crm().orders(token, page=page, per_page=per_page)
                    items = resp.get("orders") if isinstance(resp, dict) else None
                    if not isinstance(items, list) or not items:
                        break

                    try:
                        first = str((items[0] or {}).get("created_at") or (items[0] or {}).get("createdAt") or "")[:10]
                        last = str((items[-1] or {}).get("created_at") or (items[-1] or {}).get("createdAt") or "")[:10]
                        if first and last and first < last:
                            is_sorted_desc = False
                    except Exception:
                        is_sorted_desc = False

                    for o in items:
                        if not isinstance(o, dict):
                            continue
                        if _order_matches(o, a=a, b=b, order_id=order_id):
                            out.append(o)
                            if len(out) >= want_n:
                                return out[:want_n], True

                    if is_sorted_desc and a and b:
                        try:
                            oldest = str((items[-1] or {}).get("created_at") or (items[-1] or {}).get("createdAt") or "")[:10]
                            if oldest and re.fullmatch(r"\d{4}-\d{2}-\d{2}", oldest) and oldest < a:
                                break
                        except Exception:
                            pass

                    if len(items) < per_page:
                        break
                    page += 1
                return out, False

            # Transactions table: apply filters if present, otherwise show most recent.
            txn_typ = (txn_filters.get("type") or "").strip() or None
            txn_status = (txn_filters.get("status") or "").strip() or None
            if (txn_filters.get("date_range") or "").strip() or txn_typ or txn_status:
                wallet_transactions, wallet_transactions_has_more = _collect_txn_matches(
                    want_n=txn_show + 1, a=ta, b=tb, typ_code=txn_typ, status_code=txn_status
                )
            else:
                tx_resp = get_crm().wallet_transactions(token, page=1, per_page=min(200, txn_show + 1))
                items = tx_resp.get("transactions") if isinstance(tx_resp, dict) else None
                wallet_transactions = [t for t in items if isinstance(items, list) and isinstance(t, dict)]
                wallet_transactions_has_more = len(wallet_transactions) > txn_show

            # Orders table: apply filters if present, otherwise show most recent.
            oid = (order_filters.get("order_id") or "").strip() or None
            if (order_filters.get("date_range") or "").strip() or oid:
                recent_orders, recent_orders_has_more = _collect_order_matches(want_n=order_show + 1, a=oa, b=ob, order_id=oid)
            else:
                o_resp = get_crm().orders(token, page=1, per_page=min(200, order_show + 1))
                items = o_resp.get("orders") if isinstance(o_resp, dict) else None
                recent_orders = [o for o in items if isinstance(items, list) and isinstance(o, dict)]
                recent_orders_has_more = len(recent_orders) > order_show

            # Winnings table: use dedicated CRM winnings endpoint for checked/no-win/win states.
            winnings_query: dict[str, Any] = {"page": 1, "per_page": min(200, winnings_show + 1)}
            if wa:
                winnings_query["draw_date_from"] = wa.isoformat()
            if wb:
                winnings_query["draw_date_to"] = wb.isoformat()
            try:
                w_resp = get_crm().winnings_tickets(token, **winnings_query)
                w_items = w_resp.get("tickets") if isinstance(w_resp, dict) else None
                if isinstance(w_items, list):
                    winnings_wallet_transactions = [w for w in w_items if isinstance(w, dict)]
                else:
                    winnings_wallet_transactions = []
                winnings_has_more = len(winnings_wallet_transactions) > winnings_show
            except CRMError:
                # Fallback for older CRM deployments: infer winnings from wallet transactions.
                if (winnings_filters.get("date_range") or "").strip():
                    wins, winnings_has_more = _collect_txn_matches(want_n=winnings_show + 1, a=wa, b=wb, typ_code="6", status_code=None)
                else:
                    wins, winnings_has_more = _collect_txn_matches(want_n=winnings_show + 1, a=None, b=None, typ_code="6", status_code=None)
                winnings_wallet_transactions = wins

            # Slice to requested show counts.
            wallet_transactions = wallet_transactions[:txn_show]
            recent_orders = recent_orders[:order_show]

            # Fetch order detail for the rows being displayed so the expanded
            # item table can show real ticket/product data instead of placeholders.
            for o in recent_orders:
                o["detail_tickets"] = []
                o["detail_items"] = []
                try:
                    det = get_crm().order(token, int(o.get("id")))
                    od = det.get("order") if isinstance(det, dict) else None
                    if isinstance(od, dict):
                        if isinstance(od.get("tickets"), list):
                            o["detail_tickets"] = [t for t in od["tickets"] if isinstance(t, dict)]
                        if isinstance(od.get("items"), list):
                            o["detail_items"] = [i for i in od["items"] if isinstance(i, dict)]
                except Exception:
                    # A failed detail fetch should not break the order history list.
                    pass
            winnings_wallet_transactions = winnings_wallet_transactions[:winnings_show]

        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
            me, wallet, wallet_transactions, recent_orders = None, None, [], []
            winnings_wallet_transactions = []
            wallet_transactions_has_more = False
            recent_orders_has_more = False
            winnings_has_more = False
            txn_summary = {
                "currency": (wallet.get("currency") if isinstance(wallet, dict) else "") if "wallet" in locals() else "",
                "currency_symbol": "",
                "deposits_count": 0,
                "deposits_amount": "0.00",
                "withdrawals_count": 0,
                "withdrawals_amount": "0.00",
                "net_deposit": "0.00",
                "wins_count": 0,
                "wins_amount": "0.00",
                "losses_count": 0,
                "losses_amount": "0.00",
                "plays_settled_count": 0,
                "plays_unsettled_count": 0,
                "plays_settled_amount": "0.00",
                "plays_unsettled_amount": "0.00",
            }
        account_currency_code = _resolve_display_currency(
            wallet=wallet if isinstance(wallet, dict) else None,
            customer=me if isinstance(me, dict) else None,
        )
        account_currency_symbol = _currency_symbol(account_currency_code) or account_currency_code

        # Legacy Orders section (read-only imported history). Isolated so a
        # legacy fetch failure can never break the rest of the account page.
        legacy_orders_list: list[dict] = []
        legacy_orders_total = 0
        try:
            l_resp = get_crm().legacy_orders(token, page=1, per_page=25)
            if isinstance(l_resp, dict):
                if isinstance(l_resp.get("orders"), list):
                    legacy_orders_list = [x for x in l_resp["orders"] if isinstance(x, dict)]
                try:
                    legacy_orders_total = int(l_resp.get("total") or 0)
                except (TypeError, ValueError):
                    legacy_orders_total = 0
            if legacy_orders_total > 0:
                session["legacy_orders_available"] = True
        except Exception:
            # A failed request hides the section but is not proof of no history.
            pass
        legacy_orders_visible = legacy_orders_total > 0 or _legacy_orders_show_when_empty()

        return render_template(
            "account.html",
            me=me,
            wallet=wallet,
            # From the wallet this page just read, rather than the one the
            # header happened to have in session, so the two figures on the
            # screen cannot disagree with each other.
            wallet_funding=_wallet_funding(wallet if isinstance(wallet, dict) else None),
            wallet_on_hold_cents=(
                _wallet_funding(wallet if isinstance(wallet, dict) else None)["reserved_added_cents"]
                + _wallet_funding(wallet if isinstance(wallet, dict) else None)["reserved_wins_cents"]
            ),
            wallet_transactions=wallet_transactions,
            winnings_wallet_transactions=winnings_wallet_transactions,
            recent_orders=recent_orders,
            txn_summary=txn_summary,
            txn_filters=txn_filters,
            order_filters=order_filters,
            winnings_filters=winnings_filters,
            notif_prefs=notif_prefs,
            wallet_transactions_has_more=wallet_transactions_has_more,
            recent_orders_has_more=recent_orders_has_more,
            winnings_has_more=winnings_has_more,
            show_email_verify_banner=show_email_verify_banner,
            account_currency_code=account_currency_code,
            account_currency_symbol=account_currency_symbol,
            legacy_orders_visible=legacy_orders_visible,
            legacy_orders_list=legacy_orders_list,
            legacy_orders_total=legacy_orders_total,
        )

    # --- Wallet ---
    @app.get("/wallet/add-funds")
    def wallet_add_funds():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        pending_ctx = _pending_checkout_get()
        next_url = (request.args.get("next") or pending_ctx.get("next_url") or "").strip()
        prefill_amount_cents = (request.args.get("amount_cents") or "").strip()
        required_cents_raw = (request.args.get("required_cents") or "").strip()
        balance_cents_raw = (request.args.get("balance_cents") or "").strip()
        edit_order_url = (request.args.get("edit_order_url") or pending_ctx.get("edit_order_url") or "").strip()
        # Best-effort: refresh wallet cache (used by header and currency symbol).
        try:
            w = get_crm().wallet(token).get("wallet")
            if isinstance(w, dict):
                session["wallet"] = w
        except Exception:
            w = session.get("wallet") if isinstance(session.get("wallet"), dict) else None

        customer_for_currency = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        cur = _resolve_display_currency(wallet=w if isinstance(w, dict) else None, customer=customer_for_currency)
        symbol = _currency_symbol(cur) or cur
        default_amount = "5.00"
        try:
            if prefill_amount_cents:
                default_amount = f"{(max(500, int(prefill_amount_cents)) / 100):.2f}"
            elif pending_ctx.get("amount_cents"):
                default_amount = f"{(max(500, int(pending_ctx.get('amount_cents') or 0)) / 100):.2f}"
        except Exception:
            pass
        next_url = _safe_next_url(next_url, url_for("account") + "#wallet")
        purchase_mode = next_url == url_for("checkout_after_topup")
        edit_order_url = _resolve_edit_order_url(edit_order_url)
        required_cents_val = None
        balance_cents_val = None
        try:
            required_cents_val = int(required_cents_raw) if required_cents_raw else (
                int(pending_ctx.get("required_cents")) if pending_ctx.get("required_cents") is not None else None
            )
        except Exception:
            required_cents_val = None
        try:
            balance_cents_val = int(balance_cents_raw) if balance_cents_raw else (
                int(pending_ctx.get("balance_cents")) if pending_ctx.get("balance_cents") is not None else None
            )
        except Exception:
            balance_cents_val = None
        if balance_cents_val is None and isinstance(w, dict):
            # "Available Funds" on this page means the same thing it means in
            # the header and in the cart, and there is one function that says
            # what that is.
            balance_cents_val = _wallet_spendable_cents(w)
        # Amount only. Which payment methods this customer gets is the CRM's
        # decision, made when the intent is created, so there is nothing to ask
        # for here yet and no reason to guess at it in advance.
        countries_for_form: list[dict[str, Any]] = []
        needs_country = not _routing_country()
        # A hosted-only processor never shows the card form, so this is the only
        # screen where a customer without an address can still give us one.
        needs_address = not _billing_address_on_file() and not isinstance(session.get("topup_address"), dict)
        if needs_country:
            # Processor Rules match on country and fall through to "No Match"
            # when it is blank, so a customer we have no country for is asked
            # once, here, rather than being routed on a guess.
            try:
                countries_for_form = [
                    c for c in get_cache().get_countries(active_only=True, include_blocked=False) if isinstance(c, dict)
                ]
            except Exception:
                countries_for_form = []
        if purchase_mode:
            _pending_checkout_set(
                source=str(pending_ctx.get("source") or "wallet_add_funds"),
                next_url=next_url,
                amount_cents=int(round(float(default_amount) * 100)),
                required_cents=required_cents_val,
                balance_cents=balance_cents_val,
                edit_order_url=edit_order_url,
            )
        return render_template(
            "wallet_add_funds.html",
            next=next_url,
            currency_symbol=symbol,
            currency_code=cur,
            default_amount=default_amount,
            purchase_mode=purchase_mode,
            required_cents=required_cents_val,
            balance_cents=balance_cents_val,
            edit_order_url=edit_order_url,
            needs_country=needs_country,
            needs_address=needs_address,
            country_options=countries_for_form,
        )

    @app.post("/wallet/add-funds")
    def wallet_add_funds_post():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        # Amount posted in major units (e.g. 5.00); convert to cents for CRM topup init.
        raw = (request.form.get("amount") or "").strip()
        next_url = (request.form.get("next") or "").strip()
        edit_order_url = _resolve_edit_order_url((request.form.get("edit_order_url") or "").strip())
        try:
            amt = float(raw)
        except Exception:
            amt = 0.0
        if amt < 5.0:
            flash("Minimum top up is 5.00.", "error")
            return redirect(url_for("wallet_add_funds"))
        amount_cents = int(round(amt * 100))

        # The customer's country decides which processor the CRM routes to, and
        # a blank one falls through to the "No Match" rule, so ask for it here
        # when we don't already have it rather than routing on a guess.
        routing_country = _routing_country()
        if not routing_country:
            country_input = (request.form.get("country") or "").strip()
            countries_for_form: list[dict[str, Any]] = []
            try:
                countries_for_form = [
                    c for c in get_cache().get_countries(active_only=True, include_blocked=False) if isinstance(c, dict)
                ]
            except Exception:
                countries_for_form = []
            routing_country = _country_iso2_from_input(country_input, countries_for_form)
            if not routing_country and not session.pop("topup_country_asked", False):
                # Ask once. Never twice: the country list this is matched against
                # comes from the cache, so if that is empty nothing the customer
                # types will parse, and a second bounce is a customer who cannot
                # pay at all. "No Match" exists for exactly this.
                session["topup_country_asked"] = True
                flash("Please tell us which country you're paying from.", "error")
                return redirect(url_for("wallet_add_funds", next=next_url or None, amount_cents=str(amount_cents)))
            if not routing_country:
                app.logger.warning("wallet topup routing country unresolved; letting the CRM No Match rule decide")
        session.pop("topup_country_asked", None)

        # An address, for the same reason and at the same moment. Unlike the
        # country there is no "No Match" rule to fall back on: a processor that
        # wants an address and is handed none simply refuses, so this one is
        # asked for until we have it. Kept in the session because the CRM only
        # commits it once init reaches it, and a customer who has already typed
        # it should not be asked again on a retry.
        address_payload: dict[str, Any] = {}
        if _billing_address_on_file():
            session.pop("topup_address", None)
        else:
            remembered = session.get("topup_address")
            address_payload = dict(remembered) if isinstance(remembered, dict) else {}
            if not address_payload:
                address_payload = _topup_address_payload(request.form, routing_country)
                if not address_payload:
                    flash("Please give us your address so we can take the payment.", "error")
                    return redirect(url_for("wallet_add_funds", next=next_url or None, amount_cents=str(amount_cents)))
                session["topup_address"] = address_payload

        # Default return: wallet tab.
        next_url = _safe_next_url(next_url, url_for("account") + "#wallet")
        balance_before_cents: int | None = None
        try:
            w_before = get_crm().wallet(token).get("wallet")
            if isinstance(w_before, dict):
                balance_before_cents = int(w_before.get("balance_cents") or 0)
        except Exception:
            try:
                w_before = session.get("wallet") if isinstance(session.get("wallet"), dict) else None
                if isinstance(w_before, dict):
                    balance_before_cents = int(w_before.get("balance_cents") or 0)
            except Exception:
                balance_before_cents = None

        _pending_checkout_set(
            source="wallet_add_funds_post",
            next_url=next_url,
            amount_cents=amount_cents,
            edit_order_url=edit_order_url,
            topup_balance_before_cents=balance_before_cents,
        )

        # Build absolute return URLs (CRM requires allowlisted hosts).
        base = request.url_root
        if g.brand.canonical_domain:
            base = f"https://{g.brand.canonical_domain}/"

        return_urls = {
            "success": urljoin(base, url_for("wallet_topup_return", status="success", next=next_url or None)),
            "fail": urljoin(base, url_for("wallet_topup_return", status="fail", next=next_url or None)),
            "cancel": urljoin(base, url_for("wallet_topup_return", status="cancel", next=next_url or None)),
        }

        # Use options mode to let the customer choose hosted page vs direct card.
        topup_processor_override = str(app.config.get("WALLET_TOPUP_PROCESSOR_OVERRIDE") or "").strip().lower()
        init_payload: dict[str, Any] = {
            "amount_cents": amount_cents,
            "return_urls": return_urls,
            "start_hpp": False,
        }
        if routing_country:
            init_payload["country"] = routing_country
        # Persisted by the CRM before it routes, so the processor it picks can
        # be handed an address even though it will never show our card form.
        if address_payload:
            init_payload.update(address_payload)
            # And prefilled if this journey does end up on the card form, which
            # asks for the same four fields and would otherwise ask twice.
            _pending_checkout_set(
                billing_street=str(address_payload.get("street") or ""),
                billing_city=str(address_payload.get("city") or ""),
                billing_state=str(address_payload.get("state") or ""),
                billing_postcode=str(address_payload.get("postal_code") or ""),
                billing_country=str(address_payload.get("country") or ""),
            )
        # Only send processor when explicitly overridden.
        # Otherwise let CRM use the processor configured for the brand.
        if topup_processor_override:
            init_payload["processor"] = topup_processor_override
            # Naming a processor overrides Processor Rules outright: the country
            # match, the cascade and every fallback are skipped for the one named
            # here. Left set on a live server it pins every customer to it, and
            # if that processor cannot complete a payment nobody can pay at all -
            # which is why this is a warning rather than a debug line.
            app.logger.warning(
                "WALLET_TOPUP_PROCESSOR=%s is overriding CRM payment routing for this top-up",
                topup_processor_override,
            )
        # Fresh top-up: reset the routing-advance guard for this journey.
        session.pop("topup_routing_advances", None)
        session.pop("topup_tried_processors", None)

        # API 58 Processor Rules: if processor initialization fails and the
        # matched rule permits advancing, the error payload carries
        # routing.resume_payload; retry init with the routing_session_id so the
        # CRM moves to the next eligible processor. Never retry the same
        # processor directly.
        init = None
        payload_to_send = dict(init_payload)
        for _attempt in range(4):
            try:
                init = get_crm().wallet_topup_init(token, payload_to_send)
                break
            except CRMError as e:
                err_routing = _topup_routing(e.payload)
                resume = (err_routing or {}).get("resume_payload")
                if isinstance(err_routing, dict):
                    _topup_mark_tried(err_routing.get("processor"))
                next_processor = str((err_routing or {}).get("next_processor") or "").strip().lower()
                if next_processor and next_processor in _topup_tried_processors():
                    app.logger.error(
                        "wallet_topup_init routing session %s offered %s again; not advancing (tried: %s)",
                        (resume or {}).get("routing_session_id") if isinstance(resume, dict) else "unknown",
                        next_processor,
                        ",".join(_topup_tried_processors()),
                    )
                elif (
                    isinstance(err_routing, dict)
                    and err_routing.get("can_advance") is True
                    and isinstance(resume, dict)
                    and resume.get("routing_session_id")
                ):
                    app.logger.info(
                        "wallet_topup_init advancing routing session %s to next processor %s",
                        resume.get("routing_session_id"),
                        err_routing.get("next_processor") or "unknown",
                    )
                    payload_to_send = {
                        "routing_session_id": str(resume["routing_session_id"]),
                        "start_hpp": False,
                        "return_urls": return_urls,
                    }
                    continue
                flash(_friendly_crm_error(e), "error")
                return redirect(url_for("wallet_add_funds"))
        if not isinstance(init, dict):
            flash("We couldn't start your payment. Please try again.", "error")
            return redirect(url_for("wallet_add_funds"))

        routing_info = _topup_routing(init)
        if routing_info and routing_info.get("session_id"):
            _pending_checkout_set(topup_routing_session_id=str(routing_info["session_id"]))
        _topup_mark_tried((routing_info or {}).get("processor") or init.get("processor"))

        mode = str(init.get("mode") or "").strip().lower()
        # Be tolerant to CRM shape variants: infer a usable mode when omitted.
        if not mode:
            if isinstance(init.get("options"), dict):
                mode = "options"
            elif init.get("redirect_url"):
                mode = "hpp_redirect"
            elif init.get("redirect"):
                mode = "hosted_redirect"

        app.logger.info(
            "wallet_topup_init response intent_id=%s mode=%s keys=%s",
            _extract_intent_id(init) or "unknown",
            mode or "unknown",
            sorted(list(init.keys())) if isinstance(init, dict) else [],
        )
        if (mode == "options" and isinstance(init.get("options"), dict)) or mode == "direct_card":
            intent_id = _extract_intent_id(init)
            if not intent_id:
                flash("CRM did not return intent id.", "error")
                return redirect(url_for("wallet_add_funds"))
            # With Processor Rules enabled the CRM selects the processor;
            # routing.processor is authoritative over any local override.
            used_processor = str(
                (routing_info or {}).get("processor")
                or (init.get("processor") if isinstance(init, dict) else "")
                or topup_processor_override
                or ""
            ).strip().lower()

            # CRM "direct_card" mode is ambiguous across deployments:
            # - Some processors return a CRM-hosted card form URL (we must redirect to it).
            # - Others return options.direct_card.charge_url, enabling direct charge via our own form fields.
            card_form_url = str(init.get("crm_card_form_url") or "").strip() if isinstance(init, dict) else ""
            if mode == "direct_card" and card_form_url:
                _pending_checkout_set(intent_id=intent_id, direct_card_available=False, topup_processor=used_processor or None)
                return redirect(card_form_url)

            direct_card_available = _topup_direct_card_ready(init)
            if _topup_direct_card_advertised(init) and not direct_card_available:
                app.logger.info(
                    "wallet_topup_init processor %s is not a direct-card processor; using hosted page",
                    used_processor or "unknown",
                )

            _pending_checkout_set(
                intent_id=intent_id,
                direct_card_available=direct_card_available,
                topup_processor=used_processor or None,
                topup_hosted_available=_topup_hosted_ready(init),
            )

            # The intent exists now, so the payment step charges it rather than
            # creating another one. Which step the customer gets is the CRM's
            # answer, read off this response.
            if direct_card_available:
                return redirect(url_for("wallet_topup_pay", intent_id=intent_id))
            if _topup_hosted_ready(init):
                return _start_hosted_page(token, intent_id, next_url)
            # Neither flow on offer: fall through to whatever processor-neutral
            # instruction the response carries rather than starting a hosted
            # page this processor does not have.

        # Fallback: processor-neutral instructions (redirect_url, next_action_url,
        # hosted form, or CRM card form) regardless of the reported mode.
        followed = _follow_topup_payment_instructions(init, token, next_url)
        if followed is not None:
            return followed
        return redirect(
            url_for(
                "wallet_payment_failed",
                reason=f"Unsupported payment mode returned by CRM ({mode or 'unknown'}).",
                next=next_url or None,
                intent_id=_extract_intent_id(init) or None,
            )
        )

    def _pay_step_intent(intent_id: str) -> dict | None:
        """
        The pending checkout this payment step belongs to.

        The intent id is in the URL, so it is checked against the one this
        session started: a customer must not be able to charge an intent that
        isn't theirs by editing the address bar.
        """
        ctx = _pending_checkout_get()
        if str(ctx.get("intent_id") or "").strip() != str(intent_id or "").strip():
            return None
        return ctx

    # --- Emailed payment links ---
    #
    # An agent raises a top-up in the CRM and emails the customer a link to pay
    # it. They arrive from their mail rather than from a session, so the signed
    # token in the link is the only credential there is, and every CRM call in
    # this flow is made from here: the service key that authenticates them must
    # never be anywhere a browser could read it.
    #
    # Opening the link must not contact the payment provider. Providers issue
    # sessions that expire in minutes, and mail is read hours after it arrives,
    # so the provider is contacted only when Pay Now is pressed.

    _PAYMENT_LINK_TOKEN_RE = re.compile(r"[A-Za-z0-9._\-]{16,4096}")

    def _payment_link_token() -> str:
        raw = str(session.get("payment_link_token") or "")
        return raw if _PAYMENT_LINK_TOKEN_RE.fullmatch(raw) else ""

    def _payment_link_scrub(value: Any, *secrets: str) -> str:
        """
        A log line with the secrets taken back out of it.

        A provider's refusal quotes what was sent to it, so the payer's tax and
        identity numbers can arrive inside an error message, and those may not
        reach a log. A payment nobody can diagnose is not much better, so the
        message is kept and only the values are removed.
        """
        out = str(value)
        for secret in secrets:
            # Short strings would match half the message by coincidence.
            if secret and len(secret) >= 6:
                out = re.sub(re.escape(secret), "[redacted]", out, flags=re.IGNORECASE)
        return out[:500]

    def _payment_link_identity_fields(context: Any) -> list[dict[str, Any]]:
        """
        The identity fields this provider requires of the payer.

        Taken from the CRM's `payment_requirements` rather than written against
        Bitolo: a processor that needs nothing then shows no form, and one that
        needs something else does not need a deploy here.
        """
        requirements = context.get("payment_requirements") if isinstance(context, dict) else None
        if not isinstance(requirements, dict):
            return []
        fields: list[dict[str, Any]] = []
        for name, spec in requirements.items():
            # `identity_handling` sits beside the fields as a note about them,
            # not as one of them.
            if not isinstance(spec, dict) or not spec.get("required"):
                continue

            def _length(key: str, spec: dict[str, Any] = spec) -> int:
                exact = spec.get("length")
                try:
                    return int(exact if exact is not None else spec.get(key) or 0)
                except Exception:
                    return 0

            fields.append(
                {
                    "name": str(name),
                    "label": str(spec.get("label") or str(name).upper()),
                    "min_length": _length("min_length"),
                    "max_length": _length("max_length"),
                }
            )
        return fields

    def _payment_link_identity_values(
        fields: list[dict[str, Any]], form: Any
    ) -> tuple[dict[str, str], str]:
        """
        The payer's identity numbers as typed, and the first thing wrong.

        Length and character set are checked so an obvious slip is caught
        before a provider is involved. What else makes an RFC or a CURP valid
        is the provider's business: a cleverer rule here would only invent
        refusals of numbers that are perfectly good, and this is the only route
        this customer has to pay.
        """
        values: dict[str, str] = {}
        error = ""
        for field in fields:
            name = str(field.get("name") or "")
            # These are written on paper in groups; typed here the same way.
            raw = re.sub(r"[\s\-]", "", str(form.get(name) or "")).upper()
            values[name] = raw
            if error:
                continue
            label = str(field.get("label") or name.upper())
            low = int(field.get("min_length") or 0)
            high = int(field.get("max_length") or 0) or low
            if not raw:
                error = f"Please enter your {label}."
            elif not re.fullmatch(r"[A-Z0-9\u00d1&]+", raw):
                # An RFC may legitimately contain N-tilde and an ampersand.
                error = f"Your {label} should contain letters and numbers only."
            elif low and not (low <= len(raw) <= high):
                expected = f"{low} characters" if low == high else f"between {low} and {high} characters"
                error = f"Your {label} should be {expected} - you entered {len(raw)}."
        return values, error

    def _payment_link_cents(value: Any) -> int:
        try:
            return max(0, int(float(value)))
        except Exception:
            return 0

    def _payment_link_page(
        *,
        context: Any = None,
        fields: list[dict[str, Any]] | None = None,
        values: dict[str, str] | None = None,
        error: str = "",
        unavailable: str = "",
        status_code: int = 200,
    ) -> Response:
        intent = context.get("intent") if isinstance(context, dict) and isinstance(context.get("intent"), dict) else {}
        charge = context.get("charge") if isinstance(context, dict) and isinstance(context.get("charge"), dict) else {}
        wallet_currency = str(intent.get("currency") or "").strip().upper()
        charge_currency = str(charge.get("currency") or "").strip().upper()
        wallet_cents = _payment_link_cents(intent.get("amount_cents"))
        charge_cents = _payment_link_cents(charge.get("amount_cents"))
        return _protect_token_page(
            make_response(
                render_template(
                    "wallet_payment_link.html",
                    noindex="noindex, nofollow",
                    unavailable=unavailable,
                    error=error,
                    fields=fields or [],
                    values=values or {},
                    intent_status=str(intent.get("status") or "").strip().lower(),
                    intent_reference=str(intent.get("id") or intent.get("intent_id") or "").strip(),
                    wallet_amount_cents=wallet_cents,
                    wallet_currency=wallet_currency,
                    wallet_currency_symbol=_currency_symbol(wallet_currency) or wallet_currency,
                    charge_amount_cents=charge_cents,
                    charge_currency=charge_currency,
                    # The transfer is only worth stating separately when it is
                    # in another currency - the customer's bank will show that
                    # figure, not the one their wallet is credited with.
                    show_charge=bool(charge_cents and charge_currency and charge_currency != wallet_currency),
                ),
                status_code,
            )
        )

    def _payment_link_context_or_page(token: str):
        """The link's context, or the page to show instead."""
        try:
            return get_crm().wallet_topup_email_link_context(token), None
        except CRMError as e:
            status = getattr(e, "status_code", None)
            app.logger.warning(
                "payment link context refused: status=%s body=%s",
                status,
                _payment_link_scrub(getattr(e, "payload", None) if getattr(e, "payload", None) is not None else e, token),
            )
            session.pop("payment_link_token", None)
            return None, _payment_link_page(
                unavailable=(
                    "This payment link is no longer valid. Please sign in to top up, "
                    "or contact us and we will send you a new one."
                ),
            )

    @app.get("/wallet/topup/pay")
    def wallet_payment_link():
        # The token is taken off the URL on entry so it leaves the address bar,
        # the browser history and the `Referer` of every asset this page loads.
        # `intent_id` and `mode` ride along on the emailed link and are ignored
        # on purpose: the token is the credential, and what the payment is for
        # is whatever the CRM says it is, not what the query string claims.
        if request.args.get("token"):
            session["payment_link_token"] = str(request.args.get("token") or "")
            return redirect(url_for("wallet_payment_link"))

        token = _payment_link_token()
        if not token:
            return _payment_link_page(
                unavailable="This payment link has expired. Please sign in to top up, or ask us for a new link."
            )

        context, page = _payment_link_context_or_page(token)
        if page is not None:
            return page
        fields = _payment_link_identity_fields(context)
        # Bitolo refuses a start without RFC and CURP, and the form only asks
        # for them when the CRM says to. Which processor the link is for and
        # what it was said to need is the first question when one fails.
        intent = context.get("intent") if isinstance(context, dict) and isinstance(context.get("intent"), dict) else {}
        app.logger.info(
            "payment link opened: intent=%s processor=%s requires=%s",
            intent.get("id") or intent.get("intent_id") or "-",
            intent.get("processor") or "-",
            ",".join(f["name"] for f in fields) or "-",
        )
        return _payment_link_page(context=context, fields=fields)

    @app.post("/wallet/topup/pay")
    def wallet_payment_link_post():
        """Pay Now: the first and only point at which the provider is contacted."""
        token = _payment_link_token()
        if not token:
            return _payment_link_page(
                unavailable="This payment link has expired. Please sign in to top up, or ask us for a new link."
            )

        # Asked again rather than trusted from the form. What the provider
        # requires is the CRM's to state, not the browser's, and this also
        # catches a link that died while the customer was typing - before a
        # provider session is raised against it.
        context, page = _payment_link_context_or_page(token)
        if page is not None:
            return page

        fields = _payment_link_identity_fields(context)
        values, error = _payment_link_identity_values(fields, request.form)
        if error:
            return _payment_link_page(context=context, fields=fields, values=values, error=error)

        base = request.url_root
        if g.brand.canonical_domain:
            base = f"https://{g.brand.canonical_domain}/"
        payload: dict[str, Any] = {
            "token": token,
            "return_urls": {
                "success": urljoin(base, url_for("wallet_topup_return", status="success")),
                "fail": urljoin(base, url_for("wallet_topup_return", status="fail")),
                "cancel": urljoin(base, url_for("wallet_topup_return", status="cancel")),
            },
        }
        payload.update(values)

        try:
            resp = get_crm().wallet_topup_email_link_hpp_start(payload)
        except CRMError as e:
            app.logger.warning(
                "payment link start refused: status=%s body=%s",
                getattr(e, "status_code", None),
                _payment_link_scrub(
                    getattr(e, "payload", None) if getattr(e, "payload", None) is not None else e,
                    token,
                    *values.values(),
                ),
            )
            return _payment_link_page(
                context=context, fields=fields, values=values, error=_friendly_crm_error(e)
            )

        # Neither the numbers just typed nor the token go any further than this
        # request. Nothing about them is stored, and the URL below is the
        # provider's own.
        #
        # Read by the same tolerant helper the signed-in hosted flow uses. This
        # endpoint has named a payment URL `redirect_url`, `hosted_url`,
        # `next_action_url` and `crm_card_form_url` depending on the processor,
        # and insisting on one of them is how a customer was last shown a
        # failure while we were holding a working URL.
        followed = _hosted_start_redirect(resp)
        if followed is not None:
            return followed

        instructions = resp.get("instructions") if isinstance(resp, dict) else None
        if isinstance(instructions, dict) and instructions:
            # A transfer the customer makes from their own bank. There is
            # nowhere to send them, so the details have to be readable here,
            # and the money arrives long after they close the page.
            intent = context.get("intent") if isinstance(context.get("intent"), dict) else {}
            return _protect_token_page(
                make_response(
                    render_template(
                        "wallet_payment_link_instructions.html",
                        noindex="noindex, nofollow",
                        instructions=instructions,
                        reference=str(instructions.get("reference") or (resp or {}).get("order_id") or "").strip(),
                        intent_reference=str(intent.get("id") or intent.get("intent_id") or "").strip(),
                        status_url=url_for("wallet_payment_link_status"),
                    )
                )
            )

        # Nothing to redirect to and no instructions to follow. Recorded field
        # by field rather than as a shape, because the question this has to
        # answer is whether the CRM withheld a payment URL or whether one came
        # back under a name we did not read - and `keys` is what shows the
        # difference. The URLs are logged for the same reason: they are a
        # single-use provider page, not a credential of the customer's. The
        # token and the identity numbers are not logged.
        started = resp if isinstance(resp, dict) else {}
        stated_error = str(started.get("error") or "").strip()
        app.logger.error(
            "payment link start gave nothing to pay with: http=200 success=%r mode=%r "
            "error=%s redirect_url=%s hosted_url=%s keys=%s",
            started.get("success"),
            started.get("mode"),
            _payment_link_scrub(stated_error or "-", token, *values.values()),
            _payment_link_scrub(started.get("redirect_url") or "-", token),
            _payment_link_scrub(started.get("hosted_url") or "-", token),
            sorted(started) if started else type(resp).__name__,
        )
        return _payment_link_page(
            context=context,
            fields=fields,
            values=values,
            # A 200 that reports a failure still carries the reason for it, and
            # API 67 is explicit that `error` is the processor's or the CRM's
            # own words and should be shown in place of a generic refusal. It
            # is usually the only thing a customer or an agent can act on.
            error=stated_error
            or (
                "We couldn't start this payment. Nothing has been taken - please try again "
                "in a few minutes, or contact us and we'll help."
            ),
        )

    @app.get("/wallet/topup/pay/status")
    def wallet_payment_link_status():
        """Whether the transfer has landed yet, for the instructions page to poll."""
        token = _payment_link_token()
        if not token:
            return jsonify({"status": "unknown"})
        try:
            resp = get_crm().wallet_topup_email_link_status(token)
        except CRMError as e:
            status = getattr(e, "status_code", None) or 0
            # 401 is the link expiring, not the payment failing, and says
            # nothing about a transfer that may well be on its way. So there is
            # nothing to report and no point asking again: the page stops
            # polling and keeps the details it already has.
            if status == 401:
                return jsonify({"status": "expired"})
            # A transfer nobody has made yet is not a failure either, so
            # anything else unreadable leaves the instructions up. 404 covers
            # both an intent the CRM cannot find and a CRM too old to have this
            # route, so it is not worth a line in the log.
            if status != 404:
                app.logger.warning(
                    "payment link status unavailable: status=%s body=%s",
                    status,
                    _payment_link_scrub(getattr(e, "payload", None) if getattr(e, "payload", None) is not None else e, token),
                )
            return jsonify({"status": "unknown"})

        answered = resp if isinstance(resp, dict) else {}
        bucket = _topup_status_bucket(None, answered)
        if bucket in {"success", "failed", "cancelled"}:
            # The website never tells the CRM how a payment went - there is no
            # endpoint for it, and every processor is finalised by a signed
            # webhook to the CRM precisely so a browser cannot be the source of
            # that truth. So this line is not a report, it is a record of what
            # we were told: when the CRM shows no failed payment and a customer
            # was shown one, this is the only evidence of which of us said it.
            intent = answered.get("intent") if isinstance(answered.get("intent"), dict) else {}
            app.logger.info(
                "payment link status settled: bucket=%s crm_status=%r intent=%s",
                bucket,
                intent.get("status") or answered.get("status"),
                intent.get("id") or intent.get("intent_id") or "-",
            )
        return jsonify({"status": bucket})

    @app.get("/wallet/topup/<intent_id>/pay")
    def wallet_topup_pay(intent_id: str):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        ctx = _pay_step_intent(intent_id)
        if ctx is None:
            flash("That payment has expired. Please start again.", "error")
            return redirect(url_for("wallet_add_funds"))

        next_url = _safe_next_url(str(ctx.get("next_url") or ""), url_for("account") + "#wallet")
        amount_cents = int(ctx.get("amount_cents") or 0)
        w = session.get("wallet") if isinstance(session.get("wallet"), dict) else None
        customer_obj = session.get("customer") if isinstance(session.get("customer"), dict) else {}
        cur = _resolve_display_currency(wallet=w, customer=customer_obj)

        topup_processor_override = str(app.config.get("WALLET_TOPUP_PROCESSOR_OVERRIDE") or "").strip().lower()
        testing_processor_mode = topup_processor_override == "testing"
        saved_cards: list[dict] = []
        if not testing_processor_mode:
            # Testing-processor outcomes are deterministic by PAN, so saved
            # cards would make the environment unpredictable.
            try:
                resp = get_crm().wallet_cards(token)
                cards = resp.get("cards") if isinstance(resp, dict) else None
                if isinstance(cards, list):
                    saved_cards = [c for c in cards if isinstance(c, dict)]
            except CRMError:
                saved_cards = []

        countries_for_form: list[dict[str, Any]] = []
        try:
            countries_for_form = [
                c for c in get_cache().get_countries(active_only=True, include_blocked=False) if isinstance(c, dict)
            ]
        except Exception:
            countries_for_form = []
        country_name_by_iso2 = {
            str(c.get("iso2") or "").strip().upper(): str(c.get("name") or "").strip() for c in countries_for_form
        }
        mailing = customer_obj.get("mailing_address") if isinstance(customer_obj.get("mailing_address"), dict) else {}
        address_obj = customer_obj.get("address") if isinstance(customer_obj.get("address"), dict) else {}
        country_iso = str(
            ctx.get("billing_country") or customer_obj.get("country") or mailing.get("country") or address_obj.get("country") or ""
        ).strip().upper()

        return render_template(
            "wallet_topup_pay.html",
            intent_id=intent_id,
            next=next_url,
            amount_cents=amount_cents,
            currency_symbol=_currency_symbol(cur) or cur,
            currency_code=cur,
            saved_cards=saved_cards,
            testing_processor_mode=testing_processor_mode,
            now_year=datetime.now(timezone.utc).year,
            purchase_mode=next_url == url_for("checkout_after_topup"),
            # Worldpay and Z1 have no hosted page, so offering one is offering a
            # button that can only fail.
            hosted_available=bool(ctx.get("topup_hosted_available")),
            edit_order_url=str(ctx.get("edit_order_url") or ""),
            billing_street=str(ctx.get("billing_street") or customer_obj.get("street") or address_obj.get("line1") or mailing.get("street") or "").strip(),
            billing_city=str(ctx.get("billing_city") or customer_obj.get("city") or mailing.get("city") or address_obj.get("city") or "").strip(),
            billing_state=str(ctx.get("billing_state") or customer_obj.get("state") or mailing.get("state") or address_obj.get("state") or "").strip(),
            billing_postcode=str(ctx.get("billing_postcode") or customer_obj.get("postal_code") or mailing.get("postal_code") or address_obj.get("postal_code") or "").strip(),
            billing_country=country_iso,
            billing_country_display=str(ctx.get("billing_country_display") or country_name_by_iso2.get(country_iso) or country_iso),
            country_options=countries_for_form,
        )

    @app.post("/wallet/topup/<intent_id>/hosted")
    def wallet_topup_use_hosted(intent_id: str):
        """Pay the intent on the processor's hosted page instead of by card."""
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        ctx = _pay_step_intent(intent_id)
        if ctx is None:
            flash("That payment has expired. Please start again.", "error")
            return redirect(url_for("wallet_add_funds"))
        next_url = _safe_next_url(str(ctx.get("next_url") or ""), url_for("account") + "#wallet")
        return _start_hosted_page(token, intent_id, next_url)

    @app.post("/wallet/topup/<intent_id>/pay")
    def wallet_topup_pay_post(intent_id: str):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        ctx = _pay_step_intent(intent_id)
        if ctx is None:
            flash("That payment has expired. Please start again.", "error")
            return redirect(url_for("wallet_add_funds"))

        next_url = _safe_next_url(str(ctx.get("next_url") or ""), url_for("account") + "#wallet")
        pay_url = url_for("wallet_topup_pay", intent_id=intent_id)

        billing_street = (request.form.get("billing_street") or "").strip()
        billing_city = (request.form.get("billing_city") or "").strip()
        billing_state = (request.form.get("billing_state") or "").strip()
        billing_postcode = (request.form.get("billing_postcode") or "").strip()
        billing_country_input = (request.form.get("billing_country") or "").strip()
        countries_for_form: list[dict[str, Any]] = []
        try:
            countries_for_form = [
                c for c in get_cache().get_countries(active_only=True, include_blocked=False) if isinstance(c, dict)
            ]
        except Exception:
            countries_for_form = []
        billing_country = _country_iso2_from_input(billing_country_input, countries_for_form)
        _pending_checkout_set(
            billing_street=billing_street,
            billing_city=billing_city,
            billing_state=billing_state,
            billing_postcode=billing_postcode,
            billing_country=billing_country,
            billing_country_display=billing_country_input,
        )
        if not billing_street or not billing_city or not billing_postcode or not billing_country:
            flash("Please provide your full address before continuing.", "error")
            if billing_country_input and not billing_country:
                flash("Please enter a valid country name (for example: United Kingdom) or ISO code.", "error")
            return redirect(pay_url)

        three_ds = {
            "browserAcceptHeader": request.headers.get("Accept") or "",
            "browserLanguage": request.form.get("browserLanguage") or request.headers.get("Accept-Language") or "",
            "browserColorDepth": request.form.get("browserColorDepth") or "",
            "browserScreenHeight": request.form.get("browserScreenHeight") or "",
            "browserScreenWidth": request.form.get("browserScreenWidth") or "",
            "browserTimezone": request.form.get("browserTimezone") or "",
            "browserUserAgent": request.headers.get("User-Agent") or "",
        }
        three_ds = {k: v for k, v in three_ds.items() if str(v or "").strip()}

        billing = {
            "streetAddress": billing_street,
            "line1": billing_street,
            "city": billing_city,
            "postcode": billing_postcode,
            "country": billing_country,
        }
        if billing_state:
            billing["state"] = billing_state
        billing = {k: v for k, v in billing.items() if v}

        # Keep the profile address in step with what was just used to pay.
        profile_payload: dict[str, Any] = {
            "street": billing_street,
            "city": billing_city,
            "postal_code": billing_postcode,
            "country": billing_country,
            "mailing_address": {
                "street": billing_street,
                "city": billing_city,
                "postal_code": billing_postcode,
                "country": billing_country,
                **({"state": billing_state} if billing_state else {}),
            },
        }
        if billing_state:
            profile_payload["state"] = billing_state
        try:
            get_crm().customer_update(token, profile_payload)
            me = get_crm().customer_me(token).get("customer")
            if isinstance(me, dict):
                session["customer"] = me
        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
            return redirect(pay_url)

        saved_card_id = (request.form.get("saved_card_id") or "").strip()
        if str(app.config.get("WALLET_TOPUP_PROCESSOR_OVERRIDE") or "").strip().lower() == "testing":
            saved_card_id = ""

        if saved_card_id:
            cvv = (request.form.get("saved_card_cvv") or "").strip()
            if not cvv:
                flash("CVV is required for saved cards.", "error")
                return redirect(pay_url)
            payload: dict[str, Any] = {"saved_card_id": int(saved_card_id), "cvv": cvv}
            if billing:
                payload["billing"] = billing
            if three_ds:
                payload["three_ds"] = three_ds
        else:
            card_number = (request.form.get("card_number") or "").strip().replace(" ", "")
            exp_month = (request.form.get("exp_month") or "").strip()
            exp_year = (request.form.get("exp_year") or "").strip()
            cardholder_name = (request.form.get("cardholder_name") or "").strip()
            cvv = (request.form.get("cvv") or "").strip()
            if not card_number or not exp_month or not exp_year or not cardholder_name or not cvv:
                flash("Please complete all card fields.", "error")
                return redirect(pay_url)
            save_card = str(request.form.get("save_card") or "").strip() in {"1", "true", "on", "yes"}
            label = (request.form.get("card_label") or "").strip() or None
            payload = {
                "card": {
                    "card_number": card_number,
                    "exp_month": exp_month,
                    "exp_year": exp_year,
                    "cardholder_name": cardholder_name,
                    "cvv": cvv,
                },
                "save_card": bool(save_card),
            }
            if label:
                payload["label"] = label
            if billing:
                payload["billing"] = billing
            if three_ds:
                payload["three_ds"] = three_ds

        # One charge per intent, ever. A slow processor and a customer pressing
        # Pay again were each posting a charge of their own, and the processor
        # saw them as retries on one card, back to back. Every later outcome
        # moves the journey to a new intent or a terminal page, so there is no
        # legitimate second charge to allow through. The lock is in the shared
        # cache because concurrent requests each read the session as it was
        # before either finished. A duplicate goes to the return page, which
        # asks the CRM how the first charge went; the browser shows whichever
        # response came last, and that one must report the real outcome.
        _topup_mark_tried(ctx.get("topup_processor"))
        if not get_cache().try_acquire_lock(f"topup_charge:{intent_id}", ttl_seconds=6 * 3600):
            app.logger.warning(
                "wallet_topup_charge not sent: intent %s on %s has already been charged",
                intent_id,
                ctx.get("topup_processor") or "unknown",
            )
            return redirect(url_for("wallet_topup_return", status="pending", next=next_url or None, intent_id=intent_id))
        try:
            charged = get_crm().wallet_topup_charge(token, intent_id, payload)
        except CRMError as e:
            reason = _friendly_crm_error(e)
            # Matched on the CRM's own words, not the ones shown to the
            # customer. The friendly text drops the CRM's wording entirely on a
            # 500 or a gateway status, so reading it here would make this
            # recovery depend on the status code the CRM picked for a refusal
            # that is about configuration either way.
            raw_reason = _crm_error_raw(e)
            # The question "has anyone ever paid on this processor" should be
            # answerable from the log without a CRM export. Charges were logged
            # only when they failed, without naming the processor.
            app.logger.info(
                "wallet_topup_charge refused: intent=%s processor=%s http=%s",
                intent_id,
                ctx.get("topup_processor") or "unknown",
                getattr(e, "status_code", None) or "?",
            )

            # A refusal to take a card at all is a configuration answer, not a
            # decline: nothing reached the bank. Advancing on it spends a
            # processor from the rule and asks the customer to type their card
            # a third time, when this processor's own hosted page will take the
            # payment as it stands. Routing is the answer only where there is
            # no hosted page here to use. Missing flag means an older session,
            # where trying the hosted page was what happened anyway.
            if "direct card charging is only available" in raw_reason and ctx.get(
                "topup_hosted_available", True
            ):
                app.logger.warning(
                    "wallet_topup_charge refused for intent %s (processor %s); using its hosted page",
                    intent_id,
                    ctx.get("topup_processor") or "unknown",
                )
                return _start_hosted_page(
                    token,
                    intent_id,
                    next_url,
                    on_failure="Direct card is unavailable for this payment. Please use the secure payment page.",
                )

            # API 60: a routed direct-card decline or technical failure carries
            # the routing state with it, so the next processor can be started
            # without waiting for the customer to come back through a return
            # URL. Only a rule the CRM owns decides whether that is allowed.
            charge_routing = _topup_routing(e.payload)
            if charge_routing is None:
                # Compatibility while CRM deployments are staggered: older
                # builds answer the charge without routing but still carry it on
                # the intent.
                try:
                    charge_routing = _topup_routing(get_crm().wallet_topup_status(token, intent_id))
                except CRMError:
                    charge_routing = None
            advanced = _advance_topup_routing(token, charge_routing, next_url, from_intent_id=intent_id)
            if advanced is not None:
                return advanced

            if saved_card_id and "card.card_number is required" in raw_reason:
                reason = (
                    "This saved card cannot be charged by the current payment flow. "
                    "Please use a new test card for now or remove and re-add the saved card."
                )
            app.logger.warning(
                "wallet_topup_charge failed for intent %s on %s: %s",
                intent_id,
                ctx.get("topup_processor") or "unknown",
                reason,
            )
            return redirect(url_for("wallet_payment_failed", reason=reason, next=next_url or None, intent_id=intent_id))

        if isinstance(charged, dict) and charged.get("mode") == "3ds_method" and isinstance(charged.get("threeds_method"), dict):
            tdm = charged.get("threeds_method") or {}
            action_url = str(tdm.get("action_url") or "").strip()
            unique_id = str(tdm.get("unique_id") or "").strip()
            signature = str(tdm.get("signature") or "").strip()
            if action_url and unique_id and signature:
                return render_template(
                    "wallet_topup_3ds_method.html",
                    intent_id=intent_id,
                    next=next_url,
                    threeds_method_action_url=action_url,
                    threeds_method_unique_id=unique_id,
                    threeds_method_signature=signature,
                )
            return redirect(
                url_for(
                    "wallet_payment_failed",
                    reason="3DS method step response was incomplete.",
                    next=next_url or None,
                    intent_id=intent_id,
                )
            )

        if isinstance(charged, dict) and charged.get("mode") == "3ds_redirect" and charged.get("next_action_url"):
            return redirect(str(charged["next_action_url"]))
        if isinstance(charged, dict) and (
            charged.get("status") == "completed" or (charged.get("success") is True and charged.get("wallet"))
        ):
            try:
                w = charged.get("wallet") if isinstance(charged.get("wallet"), dict) else get_crm().wallet(token).get("wallet")
                if isinstance(w, dict):
                    session["wallet"] = w
            except Exception:
                pass
            return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id))

        # Some processors settle by webhook, so pending is not a failure.
        charged_bucket = _topup_status_bucket(
            str(charged.get("status") or "") if isinstance(charged, dict) else "",
            charged if isinstance(charged, dict) else None,
        )
        if charged_bucket == "pending":
            return redirect(url_for("wallet_topup_return", status="pending", next=next_url or None, intent_id=intent_id))
        if charged_bucket == "cancelled":
            return redirect(url_for("wallet_payment_cancelled", next=next_url or None, intent_id=intent_id))

        # A decline can arrive as a 200 body rather than a 402, and API 60 puts
        # routing on every charge response for a routed intent, so the same
        # advance applies here.
        advanced = _advance_topup_routing(token, _topup_routing(charged), next_url, from_intent_id=intent_id)
        if advanced is not None:
            return advanced

        reason = ""
        if isinstance(charged, dict):
            reason = str(charged.get("error") or charged.get("decline_message") or charged.get("status") or "").strip()
        if saved_card_id and "card.card_number is required" in reason.lower():
            reason = (
                "This saved card cannot be charged by the current payment flow. "
                "Please use a new test card for now or remove and re-add the saved card."
            )
        app.logger.warning("wallet_topup_charge declined for intent %s: %s", intent_id, reason or "no reason given")
        return redirect(
            url_for(
                "wallet_payment_failed",
                reason=reason or "Payment could not be completed.",
                next=next_url or None,
                intent_id=intent_id,
            )
        )

    @app.post("/wallet/cards/<int:card_id>/delete")
    def wallet_cards_delete(card_id: int):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        try:
            _ = get_crm().wallet_cards_delete(token, card_id)
            flash("Saved card removed.", "success")
        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
        return redirect(url_for("wallet_add_funds"))

    @app.post("/wallet/topup/<intent_id>/emerchant/3ds/method/continue")
    def wallet_topup_emerchant_3ds_method_continue(intent_id: str):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_add_funds")))
        pending_ctx = _pending_checkout_get()
        next_url = _safe_next_url(
            (request.form.get("next") or pending_ctx.get("next_url") or "").strip(),
            "",
        )
        try:
            resp = get_crm().wallet_topup_emerchant_3ds_method_continue(token, intent_id)
        except CRMError as e:
            return redirect(
                url_for(
                    "wallet_payment_failed",
                    reason=_friendly_crm_error(e),
                    next=next_url or None,
                    intent_id=intent_id,
                )
            )

        if isinstance(resp, dict) and resp.get("mode") == "3ds_redirect" and resp.get("next_action_url"):
            return redirect(str(resp["next_action_url"]))
        if isinstance(resp, dict) and (
            resp.get("status") == "completed"
            or (resp.get("success") is True and isinstance(resp.get("wallet"), dict))
        ):
            try:
                w = resp.get("wallet") if isinstance(resp.get("wallet"), dict) else get_crm().wallet(token).get("wallet")
                if isinstance(w, dict):
                    session["wallet"] = w
            except Exception:
                pass
            return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id))
        if isinstance(resp, dict):
            s = _topup_status_bucket(str(resp.get("status") or ""), resp)
            if s == "failed":
                reason = str(resp.get("error") or resp.get("decline_message") or "Payment could not be completed.").strip()
                return redirect(
                    url_for(
                        "wallet_payment_failed",
                        reason=reason,
                        next=next_url or None,
                        intent_id=intent_id,
                    )
                )
            if s == "cancelled":
                return redirect(url_for("wallet_payment_cancelled", next=next_url or None, intent_id=intent_id))

        # Pending/unknown states should go to the existing polling return page.
        return redirect(url_for("wallet_topup_return", status="pending", next=next_url or None, intent_id=intent_id))

    @app.get("/checkout/after-topup")
    def checkout_after_topup():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("cart")))
        items = session.get("cart_items", [])
        if not items:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("cart"))
        # Auto-submit checkout after a successful top-up.
        return render_template("checkout_after_topup.html")

    @app.get("/wallet/topup")
    def wallet_topup():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_topup")))
        next_url = (request.args.get("next") or "").strip()
        amount_cents = (request.args.get("amount_cents") or "").strip()
        try:
            amount_cents_int = int(amount_cents) if amount_cents else None
            if amount_cents_int is not None and amount_cents_int <= 0:
                amount_cents_int = None
        except Exception:
            amount_cents_int = None
        return render_template("wallet_topup.html", next=next_url, amount_cents=amount_cents_int)

    @app.post("/wallet/topup")
    def wallet_topup_post():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("wallet_topup")))

        amount_cents = int((request.form.get("amount_cents") or "0").strip() or "0")
        next_url = (request.form.get("next") or "").strip()
        if amount_cents <= 0:
            flash("Enter a positive amount (in cents).", "error")
            return redirect(url_for("wallet_topup"))

        # Build absolute return URLs (CRM requires allowlisted hosts).
        # Canonical domain can be configured in brand config or via proxy headers.
        base = request.url_root
        if g.brand.canonical_domain:
            base = f"https://{g.brand.canonical_domain}/"

        return_urls = {
            "success": urljoin(base, url_for("wallet_topup_return", status="success", next=next_url or None)),
            "fail": urljoin(base, url_for("wallet_topup_return", status="fail", next=next_url or None)),
            "cancel": urljoin(base, url_for("wallet_topup_return", status="cancel", next=next_url or None)),
        }

        try:
            init = get_crm().wallet_topup_init(token, {"amount_cents": amount_cents, "return_urls": return_urls})
        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
            return redirect(url_for("wallet_topup"))

        mode = init.get("mode")
        if mode == "hpp_redirect" and init.get("redirect_url"):
            return redirect(init["redirect_url"])

        # Hosted redirect form mode: render a tiny auto-submitting form.
        if mode == "hosted_redirect" and init.get("redirect"):
            return render_template("wallet_topup_redirect_form.html", redirect_obj=init["redirect"])

        flash("Unsupported payment mode returned by CRM.", "error")
        return redirect(url_for("wallet_topup"))

    @app.get("/wallet/topup/return/<status>")
    def wallet_topup_return(status: str):
        # CRM appends intent_id=<id>
        pending_ctx = _pending_checkout_get()
        intent_id = (request.args.get("intent_id") or pending_ctx.get("intent_id") or "").strip()
        next_url = _safe_next_url((request.args.get("next") or pending_ctx.get("next_url") or "").strip(), "")
        try:
            poll_attempt = max(0, int(request.args.get("poll_attempt", "0") or "0"))
        except Exception:
            poll_attempt = 0
        effective_status = _topup_status_bucket(status)
        failed_reason = ""
        provider_payload: dict[str, Any] | None = None
        wallet_balance_cents: int | None = None
        if intent_id:
            _pending_checkout_set(intent_id=intent_id)
        # Payment-return diagnostics for campaign analysis (fail-open).
        try:
            emit_marketing_event(
                "campaign_touch",
                stable_key=f"payment_return:{intent_id or 'unknown'}:{status}",
                metadata={
                    "phase": "payment_return",
                    "outcome": status,
                    "intent_id": intent_id,
                    "next": next_url or None,
                },
            )
        except Exception:
            pass
        # Best-effort: refresh cached balance so the header updates after returning.
        token = require_login()
        if token:
            try:
                if intent_id:
                    try:
                        provider_status_resp = get_crm().wallet_topup_status(token, intent_id)
                        provider_payload = provider_status_resp if isinstance(provider_status_resp, dict) else None
                        effective_status = _topup_status_bucket(effective_status, provider_payload)
                    except CRMError as e:
                        if e.status_code == 401:
                            app.logger.warning(
                                "wallet_topup_status unauthorized (missing service key or bearer token) intent_id=%s",
                                intent_id,
                            )
                            effective_status = "failed"
                            failed_reason = "Payment status check unauthorized. Please try again."
                        else:
                            raise
                w = get_crm().wallet(token).get("wallet")
                if isinstance(w, dict):
                    session["wallet"] = w
                    try:
                        wallet_balance_cents = int(w.get("balance_cents") or 0)
                    except Exception:
                        wallet_balance_cents = None
            except Exception:
                pass

        # Testing processor can occasionally leave status as pending while wallet is already credited.
        # If balance moved by at least the requested top-up amount, treat as success.
        if effective_status == "pending":
            try:
                before_cents_raw = pending_ctx.get("topup_balance_before_cents")
                amount_cents_raw = pending_ctx.get("amount_cents")
                before_cents = int(before_cents_raw) if before_cents_raw is not None else None
                amount_cents = int(amount_cents_raw) if amount_cents_raw is not None else 0
                if (
                    before_cents is not None
                    and amount_cents > 0
                    and wallet_balance_cents is not None
                    and wallet_balance_cents >= (before_cents + amount_cents)
                ):
                    effective_status = "success"
                # Defensive fallback: some processors settle wallet with adjustments/rounding
                # while status lags in pending. Any positive balance movement indicates credit landed.
                elif (
                    before_cents is not None
                    and wallet_balance_cents is not None
                    and wallet_balance_cents > before_cents
                ):
                    effective_status = "success"
            except Exception:
                pass

        if effective_status == "success":
            session.pop("topup_routing_advances", None)
            session.pop("topup_tried_processors", None)
            # Hosted-page payments: capture any billing address echoed in the
            # status payload into the customer profile (best-effort).
            if token:
                _sync_profile_from_topup_payload(token, provider_payload)
            return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id or None))
        if effective_status == "failed":
            # When the failed intent's routing state says the session can
            # advance, start the next attempt rather than showing a failure the
            # CRM has not finished deciding on.
            status_routing = _topup_routing(provider_payload)
            advanced = _advance_topup_routing(token, status_routing, next_url, from_intent_id=intent_id or "")
            if advanced is not None:
                return advanced
            if isinstance(status_routing, dict) and status_routing.get("exhausted") is True:
                failed_reason = (
                    "We tried all available payment providers without success. "
                    "Please try again later or contact support."
                )
            return redirect(
                url_for(
                    "wallet_payment_failed",
                    next=next_url or None,
                    intent_id=intent_id or None,
                    reason=failed_reason or effective_status,
                )
            )
        if effective_status == "cancelled":
            return redirect(
                url_for(
                    "wallet_payment_cancelled",
                    next=next_url or None,
                    intent_id=intent_id or None,
                )
            )
        is_testing_processor = str(
            pending_ctx.get("topup_processor")
            or app.config.get("WALLET_TOPUP_PROCESSOR_OVERRIDE")
            or ""
        ).strip().lower() == "testing"
        # Avoid infinite pending loop when provider/webhook is delayed or stuck.
        # Testing mode can settle asynchronously and remain "pending" longer.
        max_pending_polls = 120 if is_testing_processor else 30  # ~6m (testing) or ~90s
        if effective_status == "pending" and poll_attempt >= max_pending_polls:
            if not is_testing_processor:
                return redirect(
                    url_for(
                        "wallet_payment_failed",
                        next=next_url or None,
                        intent_id=intent_id or None,
                        reason="Payment confirmation timed out. Please try again.",
                    )
                )
            # In testing mode, prefer continued polling over a false failure screen.
            poll_attempt = 0

        poll_url = url_for("wallet_topup_return", status="pending", next=next_url or None, intent_id=intent_id or None)
        return render_template(
            "wallet_topup_return.html",
            status=effective_status,
            raw_status=status,
            intent_id=intent_id,
            next=next_url,
            can_poll=bool(token and intent_id),
            poll_url=poll_url,
            poll_attempt=poll_attempt,
            provider_payload=provider_payload,
        )

    @app.get("/wallet/topup/success")
    def wallet_payment_success():
        pending_ctx = _pending_checkout_get()
        next_url = _safe_next_url((request.args.get("next") or pending_ctx.get("next_url") or "").strip(), url_for("account") + "#wallet")
        intent_id = (request.args.get("intent_id") or pending_ctx.get("intent_id") or "").strip()
        # The shortfall figures go too, not just the intent. They describe a
        # wallet that no longer exists, and left in the session they are what
        # sends a customer who has just paid back to the payment page for the
        # same money - see the cart, which will now not act on them.
        _pending_checkout_set(
            intent_id=None,
            direct_card_available=None,
            topup_balance_before_cents=None,
            topup_processor=None,
            required_cents=None,
            balance_cents=None,
            amount_cents=None,
        )

        # A top-up made to pay for a cart is a step, not a destination.
        #
        # Customer A1007986 paid intent 3589 at 17:27:37, the wallet was
        # credited, and no order was ever placed: this page said "Payment
        # successful" over a Continue button, and "payment successful" is a
        # sentence a customer reads as "done". They closed it and went back to
        # the cart. The order that the money was for finishes here now, rather
        # than being offered to whoever thinks to press one more button.
        #
        # Server-side, deliberately. The page it replaces needed a tap on a
        # phone browser returning from the processor, and a redirect asks
        # nothing of the browser, the customer or their JavaScript.
        if next_url == url_for("checkout_after_topup") and session.get("cart_items"):
            app.logger.info(
                "topup %s funded a pending cart; continuing to checkout without waiting for a click",
                intent_id or "-",
            )
            return redirect(next_url)

        return render_template("wallet_topup_success.html", next=next_url, intent_id=intent_id)

    @app.get("/wallet/topup/failed")
    def wallet_payment_failed():
        pending_ctx = _pending_checkout_get()
        next_url = _safe_next_url((request.args.get("next") or pending_ctx.get("next_url") or "").strip(), "")
        intent_id = (request.args.get("intent_id") or pending_ctx.get("intent_id") or "").strip()
        reason = (request.args.get("reason") or "").strip()
        # If timeout happened just before settlement, recover to success automatically.
        if intent_id and "timed out" in reason.lower():
            token = require_login()
            if token:
                try:
                    status_resp = get_crm().wallet_topup_status(token, intent_id)
                    bucket = _topup_status_bucket("", status_resp if isinstance(status_resp, dict) else None)
                    if bucket == "success":
                        return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id))
                    w = get_crm().wallet(token).get("wallet")
                    if isinstance(w, dict):
                        session["wallet"] = w
                        before_raw = pending_ctx.get("topup_balance_before_cents")
                        amount_raw = pending_ctx.get("amount_cents")
                        before_cents = int(before_raw) if before_raw is not None else None
                        amount_cents = int(amount_raw) if amount_raw is not None else 0
                        current_cents = int(w.get("balance_cents") or 0)
                        if (
                            before_cents is not None
                            and amount_cents > 0
                            and current_cents >= (before_cents + amount_cents)
                        ):
                            return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id))
                        if before_cents is not None and current_cents > before_cents:
                            return redirect(url_for("wallet_payment_success", next=next_url or None, intent_id=intent_id))
                except Exception:
                    pass
        _pending_checkout_set(intent_id=None, topup_processor=None)
        return render_template("wallet_topup_failed.html", next=next_url, intent_id=intent_id, reason=reason)

    @app.get("/wallet/topup/cancelled")
    @app.get("/wallet/topup/cancel")
    def wallet_payment_cancelled():
        pending_ctx = _pending_checkout_get()
        next_url = _safe_next_url((request.args.get("next") or pending_ctx.get("next_url") or "").strip(), "")
        intent_id = (request.args.get("intent_id") or pending_ctx.get("intent_id") or "").strip()
        _pending_checkout_set(intent_id=None, topup_processor=None)
        return render_template("wallet_topup_cancelled.html", next=next_url, intent_id=intent_id)

    # --- Orders ---
    @app.get("/orders")
    def orders():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("orders")))
        page = int(request.args.get("page", "1") or "1")
        data = get_crm().orders(token, page=page, per_page=25)
        display_currency_code = _resolve_display_currency(
            wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
            customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
        )
        return render_template(
            "orders.html",
            orders=data.get("orders", []),
            page=page,
            display_currency_code=display_currency_code,
            display_currency_symbol=_currency_symbol(display_currency_code) or display_currency_code,
            legacy_orders_available=_legacy_orders_available(token),
            active_orders_tab="current",
        )

    @app.get("/orders/<int:order_id>")
    def order_detail(order_id: int):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("order_detail", order_id=order_id)))
        data = get_crm().order(token, order_id)
        order = data.get("order") if isinstance(data, dict) else None
        has_missing_scan = False
        if isinstance(order, dict):
            tickets = order.get("tickets")
            if isinstance(tickets, list):
                for t in tickets:
                    if not isinstance(t, dict):
                        continue
                    scan = t.get("scan_url") or t.get("scanned_url")
                    if not scan:
                        has_missing_scan = True
                        break
        poll_attempt = 0
        try:
            poll_attempt = max(0, int(request.args.get("poll_attempt", "0") or "0"))
        except Exception:
            poll_attempt = 0
        return render_template(
            "order_detail.html",
            order=order,
            scan_poll_attempt=poll_attempt,
            has_missing_scan=has_missing_scan,
            display_currency_code=_resolve_display_currency(
                wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
                customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
            ),
        )

    # --- Legacy orders (read-only imported history; separate from current orders) ---
    def _legacy_orders_show_when_empty() -> bool:
        # Verification override: show the Legacy Orders tab (and an empty legacy
        # list page) even when the customer has no legacy orders. Set
        # LEGACY_ORDERS_SHOW_EMPTY=0 to restore the spec behavior of hiding the
        # tab when total == 0.
        return _env_bool("LEGACY_ORDERS_SHOW_EMPTY", True)

    def _legacy_orders_available(token: str) -> bool:
        """
        Whether the Legacy Orders tab should be shown for this customer.
        Only a successful list response with total > 0 shows the tab; a failed
        request hides the tab for this render but is not treated as proof that
        the customer has no history (nothing is cached, so we re-check later).
        """
        if _legacy_orders_show_when_empty():
            return True
        if session.get("legacy_orders_available") is True:
            return True
        try:
            data = get_crm().legacy_orders(token, page=1, per_page=1)
        except CRMError:
            return False
        total = data.get("total") if isinstance(data, dict) else 0
        try:
            available = int(total or 0) > 0
        except (TypeError, ValueError):
            available = False
        if available:
            # Imported history only ever grows, so a positive result is safe to cache.
            session["legacy_orders_available"] = True
        return available

    @app.get("/legacy-orders")
    def legacy_orders():
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("legacy_orders")))
        try:
            page = max(1, int(request.args.get("page", "1") or "1"))
        except ValueError:
            page = 1
        try:
            data = get_crm().legacy_orders(token, page=page, per_page=25)
        except CRMError as e:
            flash(_friendly_crm_error(e), "error")
            return redirect(url_for("orders"))
        if not isinstance(data, dict):
            data = {}
        legacy_list = data.get("orders") if isinstance(data.get("orders"), list) else []
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0 and not _legacy_orders_show_when_empty():
            # Successful response with no history: never render an empty Legacy Orders tab.
            return redirect(url_for("orders"))
        if total > 0:
            session["legacy_orders_available"] = True
        try:
            per_page = max(1, int(data.get("per_page") or 25))
        except (TypeError, ValueError):
            per_page = 25
        try:
            page = max(1, int(data.get("page") or page))
        except (TypeError, ValueError):
            pass
        total_pages = max(1, -(-total // per_page))
        return render_template(
            "legacy_orders.html",
            legacy_orders=legacy_list,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            legacy_orders_available=True,
            active_orders_tab="legacy",
            display_currency_code=_resolve_display_currency(
                wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
                customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
            ),
        )

    @app.get("/legacy-orders/<legacy_order_id>")
    def legacy_order_detail(legacy_order_id: str):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("legacy_order_detail", legacy_order_id=legacy_order_id)))
        try:
            data = get_crm().legacy_order(token, legacy_order_id)
        except CRMError as e:
            if e.status_code == 404:
                # Legacy order unavailable to this customer.
                return render_template("404.html"), 404
            flash(_friendly_crm_error(e), "error")
            return redirect(url_for("legacy_orders"))
        # Per API.md the legacy detail returns the order header fields at the top
        # level (plus items[] and tickets[]); tolerate an `order` wrapper too.
        order = None
        if isinstance(data, dict):
            if isinstance(data.get("order"), dict):
                order = data["order"]
            elif data.get("id"):
                order = data
        if not isinstance(order, dict):
            return render_template("404.html"), 404
        return render_template(
            "legacy_order_detail.html",
            order=order,
            display_currency_code=_resolve_display_currency(
                wallet=session.get("wallet") if isinstance(session.get("wallet"), dict) else None,
                customer=session.get("customer") if isinstance(session.get("customer"), dict) else None,
            ),
        )

    @app.post("/orders/<int:order_id>/refund-request")
    def order_refund_request(order_id: int):
        token = require_login()
        if not token:
            return redirect(url_for("login", next=url_for("order_detail", order_id=order_id)))
        reason = (request.form.get("reason") or "").strip() or "Customer requested refund support"
        return redirect(url_for("contact", topic="refund", order_id=str(order_id), message=reason))

    # --- Static pages (new canonical routes) ---
    @app.get("/contact-us")
    def contact():
        # LottosOnline's contact page: the old page's copy (phone, email, office) plus, when an account flow
        # sends the customer here about a withdrawal or refund, a pre-filled email. The inherited contact
        # form is gone: its handler acknowledged messages without sending them anywhere.
        topic = (request.args.get("topic") or "").strip().lower()
        order_id = (request.args.get("order_id") or "").strip()[:32]
        amount = (request.args.get("amount") or "").strip()[:32]
        subjects = {"withdrawal": "Withdrawal request", "refund": "Refund request", "email_verify": "Email verification"}
        subject = subjects.get(topic)
        if subject and order_id:
            subject += f" (order {order_id})"
        if subject and amount:
            subject += f" (amount {amount})"
        if topic in {"withdrawal", "refund"}:
            emit_marketing_event(
                "click",
                stable_key=f"{uuid.uuid4().hex}:{topic}:support",
                metadata={"topic": topic, "order_id": order_id or None},
            )
        return render_template("lo/contact.html", page=app.config["LO_LEGACY_PAGES"].get("/contact-us"), subject=subject)

    # Lotto Express blog and legacy-URL layers removed: LottosOnline public URLs live in lo_routes.py.

    @app.errorhandler(404)
    def not_found(_e):
        """
        Last chance to recognise a URL from an older generation of the site.

        This domain has carried three of them: an ISAPI site (`/pl.dll?PageID=`),
        a localised ASP.NET one (`/en/home/faq/`), and the PHP site most of the
        redirects above are written for. The archive shows all three still
        indexed, and a page that has a home here should go there rather than
        404. Handled once, here, instead of as dozens of routes.
        """
        brand: BrandConfig = app.config["BRAND_CONFIG"]
        table = {str(k).strip().lower().rstrip("/") or "/": v for k, v in (brand.legacy_path_to_path or {}).items()}
        target = table.get((request.path or "/").lower().rstrip("/") or "/")
        if target and target != request.path:
            return redirect(target, code=301)
        return render_template("404.html"), 404

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def server_error(e):
        # Known HTTP errors (403/404/405/...) keep their native response and
        # dedicated handlers; only true server errors get the friendly page.
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException) and (e.code or 500) < 500:
            return e

        # Log full detail server-side, but never leak internals to the user.
        # Rendered inline (no base template / context processors) so an upstream
        # CRM outage cannot cascade into a second failure while rendering the
        # error page itself.
        try:
            app.logger.exception("Unhandled error: %s", e)
        except Exception:
            pass
        body = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Something went wrong | LottosOnline</title>
  <link rel="stylesheet" href="/resources/css/style.css?v=2" />
</head>
<body>
  <div class="container">
    <div class="row lePages">
      <div class="col-xs-12 col-sm-12 col-md-12">
        <h1 class="pageHeading">Something went wrong</h1>
        <p class="sub-heading">Sorry, we hit a temporary problem. Please try again in a moment.</p>
        <a class="linkAsButton" href="/">Return home</a>
      </div>
    </div>
  </div>
</body>
</html>
"""
        return Response(body, status=500, mimetype="text/html")

    @app.route("/admin/login", methods=["GET", "POST"])
    @app.route("/admin/login/", methods=["GET", "POST"])
    def admin_login():
        next_url_raw = (request.args.get("next") or request.form.get("next") or "").strip()
        next_url = _sanitize_admin_next(next_url_raw) or url_for("admin_crm_cache")
        if request.method == "POST":
            sent = request.form.get("password") or ""
            want = (os.getenv("WEBSITE_ADMIN_PASSWORD") or "").strip()
            if not want:
                flash("Admin password is not configured.", "danger")
            else:
                try:
                    ok = secrets.compare_digest(sent, want)
                except Exception:
                    ok = sent == want
                if ok:
                    session["admin_authed"] = True
                    session.permanent = True
                    return redirect(next_url)
                flash("Incorrect password.", "danger")
        return render_template("admin_login.html", next_url=next_url)

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("admin_authed", None)
        return redirect(url_for("home"))

    def _lotto_default_github_user() -> str:
        return (
            _env_first(
                "LOTTO_GITHUB_PULL_DEFAULT_USER",
                "GITHUB_PULL_DEFAULT_USER",
                "GITHUB_USER",
                "GITHUB_USERNAME",
            )
            or "lottosonline-bot"
        )

    def _lotto_default_github_template() -> str:
        return (
            _env_first(
                "LOTTO_GITHUB_PULL_COMMAND_TEMPLATE",
                "GITHUB_PULL_COMMAND_TEMPLATE",
                "GITHUB_COMMAND_TEMPLATE",
            )
            or "https://{github_user}:{github_key}@github.com/REPLACE_ME/REPLACE_ME.git main"
        ).strip()

    def _lotto_allowed_github_repo() -> str:
        return _env_first("LOTTO_GITHUB_PULL_ALLOWED_REPO", "GITHUB_PULL_ALLOWED_REPO").lower()

    def _lotto_env_github_key() -> str:
        return _env_first(
            "LOTTO_GITHUB_PULL_KEY",
            "GITHUB_PULL_KEY",
            "GITHUB_PAT",
            "GITHUB_TOKEN",
        )

    def _validate_lotto_pull_remote(remote_url: str) -> None:
        rl = (remote_url or "").strip().lower()
        if not rl:
            raise RuntimeError("Git remote URL is empty.")
        blocked_markers = ("winnow", "winnowlotto", "website1.git")
        if any(m in rl for m in blocked_markers):
            raise RuntimeError("Refusing to pull non-Lotto repository target.")
        allowed = _lotto_allowed_github_repo()
        if not allowed:
            raise RuntimeError("LOTTO_GITHUB_PULL_ALLOWED_REPO is not configured.")
        if allowed not in rl:
            raise RuntimeError("Remote target is not in LOTTO_GITHUB_PULL_ALLOWED_REPO.")

    def _github_pull_template_is_valid(template: str) -> bool:
        try:
            tpl = str(template or "").strip()
            if not tpl:
                return False
            parts = tpl.split()
            if len(parts) < 2:
                return False
            _ = parts[0].format(github_user="u", github_key="k")
            branch = parts[1].strip()
            return bool(branch)
        except Exception:
            return False

    def _redacted_remote(remote_url: str, github_user: str | None, github_key: str | None) -> str:
        out = str(remote_url or "")
        if github_key:
            out = _redact_secret(out, github_key)
        if github_user:
            out = out.replace(f"{github_user}@", "***@")
            out = out.replace(f"{github_user}:", "***:")
        return out

    def _redact_url_credentials(text: str) -> str:
        s = str(text or "")
        # Hide any URL-embedded basic auth credential: https://user:secret@host/...
        try:
            s = re.sub(r"(https?://[^:/@\s]+:)[^@/\s]+(@)", r"\1***REDACTED***\2", s, flags=re.IGNORECASE)
        except Exception:
            pass
        return s

    @app.route("/admin/crm-cache", methods=["GET", "POST"])
    @app.route("/admin/crm-cache/", methods=["GET", "POST"])
    def admin_crm_cache():
        if not _require_admin():
            nxt = (request.full_path or request.path or "").strip()
            if nxt.endswith("?"):
                nxt = nxt[:-1]
            nxt = _sanitize_admin_next(nxt) or "/admin/crm-cache"
            return redirect(url_for("admin_login", next=nxt))

        cache = get_cache()
        # Ensure newly introduced admin tables exist for pre-existing DB files.
        cache.init_db()
        client = get_crm()
        action = (request.form.get("action") or request.args.get("action") or "").strip().lower()
        msg = None
        err = None
        github_pull_output = None
        github_pull_exit = None

        try:
            cur = cache.get_github_pull_settings() or {}
            if not cur.get("github_user") or not cur.get("command_template"):
                cache.upsert_github_pull_settings(
                    github_user=(cur.get("github_user") or _lotto_default_github_user()),
                    command_template=(cur.get("command_template") or _lotto_default_github_template()),
                )
        except Exception:
            pass

        if request.method == "POST" and action == "github_pull":
            acquired = False
            try:
                st = cache.get_github_pull_settings() or {}
                env_user = (_env_first("LOTTO_GITHUB_PULL_DEFAULT_USER", "GITHUB_PULL_DEFAULT_USER") or "").strip()
                env_tpl = (_env_first("LOTTO_GITHUB_PULL_COMMAND_TEMPLATE", "GITHUB_PULL_COMMAND_TEMPLATE") or "").strip()
                github_user = (env_user or st.get("github_user") or _lotto_default_github_user()).strip() or _lotto_default_github_user()
                tpl = (env_tpl or st.get("command_template") or _lotto_default_github_template()).strip()
                new_key = (request.form.get("github_key") or "").strip()
                enc = st.get("github_key_enc")
                key_source = "unknown"

                acquired = cache.try_acquire_lock("github_pull", ttl_seconds=180)
                if not acquired:
                    raise RuntimeError("Another Git pull is already running. Please wait and retry.")

                if new_key:
                    enc_new = _github_pat_encrypt(new_key)
                    if not enc_new:
                        raise RuntimeError("GitHub key encryption is not configured. Set GITHUB_PULL_FERNET_KEY.")
                    cache.upsert_github_pull_settings(github_user=github_user, github_key_enc=enc_new, command_template=tpl)
                    enc = enc_new
                    key_source = "form"

                if key_source != "form":
                    key_plain = _lotto_env_github_key()
                    if key_plain:
                        key_source = "env"
                    elif enc:
                        key_plain = _github_pat_decrypt(str(enc))
                        if key_plain:
                            key_source = "db"
                    if not key_plain:
                        raise RuntimeError(
                            "No GitHub key available. Enter a key in the form, or configure LOTTO_GITHUB_PULL_KEY/GITHUB_PULL_KEY."
                        )
                else:
                    key_plain = new_key
                expanded = tpl.format(github_user=github_user, github_key=key_plain)
                parts = expanded.split()
                if len(parts) < 2:
                    raise RuntimeError("Invalid command template. Expected: '<remote_url> <branch>'.")
                remote_url = parts[0].strip()
                branch = parts[1].strip()
                _validate_lotto_pull_remote(remote_url)

                repo_dir = os.path.dirname(__file__)
                res = subprocess.run(
                    ["git", "-C", repo_dir, "pull", remote_url, branch],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                github_pull_exit = int(res.returncode or 0)
                out = (res.stdout or "") + ("\n" if (res.stdout and res.stderr) else "") + (res.stderr or "")
                try:
                    head = subprocess.run(
                        ["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    branch_name = subprocess.run(
                        ["git", "-C", repo_dir, "branch", "--show-current"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    status = subprocess.run(
                        ["git", "-C", repo_dir, "status", "-sb"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    out += "\n\n---\n"
                    out += f"repo_dir: {repo_dir}\n"
                    out += f"requested_remote: {_redacted_remote(remote_url, github_user, key_plain)}\n"
                    out += f"requested_branch: {branch}\n"
                    out += f"key_source: {key_source}\n"
                    out += f"allowlist_configured: {'yes' if bool(_lotto_allowed_github_repo()) else 'no'}\n"
                    out += f"template_valid: {'yes' if _github_pull_template_is_valid(tpl) else 'no'}\n"
                    out += f"branch: {(branch_name.stdout or '').strip()}\n"
                    out += f"head: {(head.stdout or '').strip()}\n"
                    out += (status.stdout or "").strip()
                except Exception:
                    pass
                out = _redact_secret(out, key_plain)
                if not out.strip():
                    out = f"No stdout/stderr returned by git pull (exit {github_pull_exit})."
                github_pull_output = out.strip()
                try:
                    cache.set_state("github_pull_last_output", github_pull_output)
                    cache.set_state("github_pull_last_exit", str(github_pull_exit))
                    cache.set_state("github_pull_last_at", datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass
                if github_pull_exit == 0:
                    msg = "Git pull completed."
                else:
                    err = f"Git pull failed (exit {github_pull_exit})."
            except Exception as exc:
                err = f"Git pull failed: {exc}"
                github_pull_exit = github_pull_exit if github_pull_exit is not None else -1
                github_pull_output = (
                    f"Git pull failed before completion.\n"
                    f"reason: {exc}\n"
                    f"repo_dir: {os.path.dirname(__file__)}\n"
                    f"allowlist_configured: {'yes' if bool(_lotto_allowed_github_repo()) else 'no'}"
                )
                try:
                    cache.set_state("github_pull_last_output", github_pull_output)
                    cache.set_state("github_pull_last_exit", str(github_pull_exit))
                    cache.set_state("github_pull_last_at", datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass
            finally:
                if acquired:
                    cache.release_lock("github_pull")

        if request.method == "POST" and action == "save_intervals":
            try:
                jm = int(request.form.get("jackpots_interval_minutes") or 20)
                rh = int(request.form.get("results_interval_hours") or 12)
                wp = int(request.form.get("website_policies_refresh_interval_seconds") or 3600)
                pp = int(request.form.get("product_prices_refresh_interval_seconds") or 86400)
                cache.set_state("jackpots_interval_minutes", str(max(1, jm)))
                cache.set_state("results_interval_hours", str(max(1, rh)))
                cache.set_state("website_policies_refresh_interval_seconds", str(max(30, wp)))
                cache.set_state("product_prices_refresh_interval_seconds", str(max(300, pp)))
                msg = "Saved polling intervals."
            except Exception as exc:
                err = f"Failed to save intervals: {exc!r}"

        if request.method == "POST" and action == "sync_jackpots_now":
            acquired = False
            try:
                acquired = cache.try_acquire_lock("jackpots", ttl_seconds=600)
                if acquired:
                    jackpots = run_with_backoff(lambda: _get_jackpots_live_or_cache(), cache, "jackpots")
                    msg = f"Synced jackpots: {len(jackpots) if isinstance(jackpots, list) else 0} rows."
                else:
                    err = "Jackpots sync already running."
            except Exception as exc:
                err = f"Jackpots sync failed: {exc}"
            finally:
                if acquired:
                    cache.release_lock("jackpots")

        if request.method == "POST" and action == "sync_countries_now":
            acquired = False
            try:
                acquired = cache.try_acquire_lock("countries", ttl_seconds=300)
                if acquired:
                    out = run_with_backoff(lambda: sync_countries_once(client, cache), cache, "countries")
                    msg = f"Synced countries: {int((out or {}).get('countries') or 0)} rows."
                else:
                    err = "Countries sync already running."
            except Exception as exc:
                err = f"Countries sync failed: {exc}"
            finally:
                if acquired:
                    cache.release_lock("countries")

        if request.method == "POST" and action == "sync_website_policies_now":
            acquired = False
            try:
                acquired = cache.try_acquire_lock("website_policies", ttl_seconds=300)
                if acquired:
                    out = run_with_backoff(lambda: sync_website_policies_once(client, cache), cache, "website_policies")
                    msg = f"Synced website policies: {int((out or {}).get('policies') or 0)} rows."
                else:
                    err = "Website-policies sync already running."
            except Exception as exc:
                err = f"Website-policies sync failed: {exc}"
            finally:
                if acquired:
                    cache.release_lock("website_policies")

        if request.method == "POST" and action == "sync_product_prices_now":
            acquired = False
            try:
                acquired = cache.try_acquire_lock("product_prices", ttl_seconds=600)
                if acquired:
                    out = run_with_backoff(lambda: sync_product_prices_once(client, cache), cache, "product_prices")
                    msg = f"Synced product prices: {int((out or {}).get('products') or 0)} rows."
                else:
                    err = "Product-prices sync already running."
            except Exception as exc:
                err = f"Product-prices sync failed: {exc}"
                _record_pricing_warning(f"product_price_sync_failed:{exc}")
            finally:
                if acquired:
                    cache.release_lock("product_prices")

        if request.method == "POST" and action == "backfill_results_now":
            acquired = False
            try:
                acquired = cache.try_acquire_lock("draw_results", ttl_seconds=3600)
                if acquired:
                    out = run_with_backoff(
                        lambda: sync_draw_results_incremental(client, cache, include_prize_tiers=True, backfill_all_pages=True),
                        cache,
                        "draw_results",
                    )
                    msg = f"Backfilled results: {(out or {}).get('draws')} draws across {(out or {}).get('pages')} pages."
                else:
                    err = "Draw-results sync already running."
            except Exception as exc:
                err = f"Draw-results backfill failed: {exc}"
            finally:
                if acquired:
                    cache.release_lock("draw_results")

        if request.method == "POST" and action == "clear_cache":
            try:
                db_path = cache.cfg.db_path
                for p in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
                    if os.path.exists(p):
                        os.remove(p)
                get_cache().init_db()
                msg = "Cache cleared."
            except Exception as exc:
                err = f"Clear cache failed: {exc!r}"

        status = cache.get_sync_status()
        counts = cache.counts()
        jackpots_interval_minutes = int((cache.get_state("jackpots_interval_minutes") or "20") or 20)
        results_interval_hours = int((cache.get_state("results_interval_hours") or "12") or 12)
        try:
            website_policies_refresh_interval_seconds = int((cache.get_state("website_policies_refresh_interval_seconds") or "3600") or 3600)
        except Exception:
            website_policies_refresh_interval_seconds = 3600
        try:
            product_prices_refresh_interval_seconds = int(
                (cache.get_state("product_prices_refresh_interval_seconds") or os.environ.get("CRM_PRODUCT_PRICES_REFRESH_SECONDS") or "86400") or 86400
            )
        except Exception:
            product_prices_refresh_interval_seconds = 86400
        policies_by_category = cache.get_website_policies_grouped()
        github_st = cache.get_github_pull_settings() or {}
        env_user = (_env_first("LOTTO_GITHUB_PULL_DEFAULT_USER", "GITHUB_PULL_DEFAULT_USER") or "").strip()
        env_tpl = (_env_first("LOTTO_GITHUB_PULL_COMMAND_TEMPLATE", "GITHUB_PULL_COMMAND_TEMPLATE") or "").strip()
        effective_github_user = (env_user or github_st.get("github_user") or _lotto_default_github_user())
        effective_github_template = (env_tpl or github_st.get("command_template") or _lotto_default_github_template())
        key_available = bool(_lotto_env_github_key() or github_st.get("github_key_enc"))
        pull_status_flags = {
            "allowlist_configured": bool(_lotto_allowed_github_repo()),
            "template_valid": _github_pull_template_is_valid(effective_github_template),
            "key_available": key_available,
        }
        github_command_template_display = _redact_url_credentials(effective_github_template)
        if github_pull_output is None:
            try:
                github_pull_output = cache.get_state("github_pull_last_output") or ""
            except Exception:
                github_pull_output = ""
        if github_pull_exit is None:
            try:
                _last_exit = cache.get_state("github_pull_last_exit")
                github_pull_exit = int(_last_exit) if _last_exit is not None and str(_last_exit).strip() != "" else None
            except Exception:
                github_pull_exit = None

        return render_template(
            "admin_crm_cache.html",
            status=status,
            counts=counts,
            policies_by_category=policies_by_category,
            policies_count=sum([len(v) for v in (policies_by_category or {}).values()]) if isinstance(policies_by_category, dict) else 0,
            msg=msg,
            err=err,
            jackpots_interval_minutes=jackpots_interval_minutes,
            results_interval_hours=results_interval_hours,
            website_policies_refresh_interval_seconds=website_policies_refresh_interval_seconds,
            product_prices_refresh_interval_seconds=product_prices_refresh_interval_seconds,
            github_user=effective_github_user,
            github_command_template=github_command_template_display,
            github_pull_status_flags=pull_status_flags,
            github_pull_output=github_pull_output,
            github_pull_exit=github_pull_exit,
        )

    # --- Optional background sync placeholder ---
    def _sync_once() -> None:
        # Runs on a thread of its own, where there is no application context.
        # Nearly everything below reaches the CRM through `get_crm()`, which
        # keeps its client on `g`, so without this the first call raises and the
        # whole loop has been dead for as long as anyone has had it switched on.
        with app.app_context():
            _sync_once_in_context()

    def _sync_once_in_context() -> None:
        cache = get_cache()
        if not cache.try_acquire_lock("sync", ttl_seconds=120):
            return
        try:
            try:
                jackpots_interval_minutes = int((cache.get_state("jackpots_interval_minutes") or "20") or 20)
                results_interval_hours = int((cache.get_state("results_interval_hours") or "12") or 12)
                website_policies_interval_seconds = int((cache.get_state("website_policies_refresh_interval_seconds") or "3600") or 3600)
                product_prices_interval_seconds = int(
                    (cache.get_state("product_prices_refresh_interval_seconds") or os.environ.get("CRM_PRODUCT_PRICES_REFRESH_SECONDS") or "86400")
                    or 86400
                )
            except Exception:
                jackpots_interval_minutes = 20
                results_interval_hours = 12
                website_policies_interval_seconds = 3600
                product_prices_interval_seconds = 86400

            # `run_with_backoff` re-raises once its attempts are spent, and the
            # jobs below used to be called through it directly, so the first one
            # to fail took every job after it down with it for as long as it kept
            # failing. Product prices called a cache method that does not exist,
            # which is how draw results — last in the list — stopped updating for
            # a month while jackpots and policies carried on fine. Each job now
            # fails on its own. `run_with_backoff` has already recorded the error
            # in sync_state by the time it reaches us, so the admin sync view
            # still shows what broke.
            def _job(name: str, fn: Any) -> None:
                try:
                    run_with_backoff(name, fn, cache)
                except Exception as exc:
                    app.logger.warning("crm sync job %s failed: %r", name, exc)

            # Store games/products: refresh periodically so new CRM products appear without deploys.
            def _store_games() -> None:
                data = get_crm()._request("GET", "/api/v1/store/games", service_key=True, timeout_seconds=10)
                if isinstance(data, dict) and isinstance(data.get("games"), list):
                    cache.set_state("store_games_json", json.dumps(data, ensure_ascii=False))
                    cache.set_state("store_games_fetched_at", str(int(datetime.now(timezone.utc).timestamp())))

            _job("store_games", _store_games)

            # Warmed rather than fetched: `marketing_banners_cached` is what the
            # pages call and it holds its own TTL, so this just keeps a visitor
            # from being the one who waits for the CRM. Under `_job` with
            # everything else, since it used to sit outside the error handling
            # and could abort the pass before any of the jobs below it ran.
            def _banners() -> None:
                for placement in ("home", "catalog"):
                    marketing_banners_cached(placement)

            _job("marketing_banners", _banners)

            # Jackpots (live-first + persisted)
            def _jackpots() -> None:
                _get_jackpots_live_or_cache()

            if should_sync(cache.get_state("last_jackpots_fetch_at"), max(60, int(jackpots_interval_minutes) * 60)):
                _job("jackpots", _jackpots)

            # Countries (brand-scoped allow/block rules)
            def _countries() -> None:
                sync_countries_once(get_crm(), cache)

            if should_sync(cache.get_state("last_countries_fetch_at"), 300):
                _job("countries", _countries)

            # Website policies (brand-scoped)
            def _website_policies() -> None:
                sync_website_policies_once(get_crm(), cache)

            if should_sync(cache.get_state("last_website_policies_fetch_at"), max(30, int(website_policies_interval_seconds))):
                _job("website_policies", _website_policies)

            # Product pricing fallback snapshot (daily by default).
            def _product_prices() -> None:
                sync_product_prices_once(get_crm(), cache)

            if should_sync(cache.get_state("last_product_prices_fetch_at"), max(300, int(product_prices_interval_seconds))):
                _job("product_prices", _product_prices)

            # Draw results incremental backfill
            def _draws() -> None:
                # Drain the cursor instead of taking a single page per interval.
                # The bulk endpoint is ordered oldest-updated-first, so one page
                # every twelve hours can only ever crawl forwards through
                # history: a cursor sitting in July could not reach September
                # before the next July's worth of draws arrived. Draining is the
                # only shape of this job that can recover from falling behind.
                out = sync_draw_results_incremental(
                    get_crm(),
                    cache,
                    include_prize_tiers=True,
                    backfill_all_pages=True,
                    limit=500,
                    max_pages=_DRAW_RESULTS_PAGES_PER_RUN,
                )
                # Hitting the page budget is not the same as being up to date,
                # and `sync_draw_results_incremental` stamps the fetch time
                # either way, so record which one happened.
                cache.set_state("draw_results_caught_up", "0" if out.get("has_more") else "1")

            # A run that stopped on its budget is picked up by the next pass of
            # the loop rather than waiting out the interval, so a long backfill
            # finishes in minutes without anyone running anything by hand.
            behind = (cache.get_state("draw_results_caught_up") or "1") != "1"
            if behind or should_sync(cache.get_state("last_draw_results_fetch_at"), max(60, int(results_interval_hours) * 3600)):
                _job("draw_results", _draws)
        finally:
            cache.release_lock("sync")

    # Exposed so the loop's entry point can be exercised directly. It only ever
    # runs on a thread, which is where its context problems live.
    app.extensions["crm_sync_once"] = _sync_once

    start_background_sync(_sync_once, interval_seconds=300)

    # Engine internals the LottosOnline layer reuses rather than duplicates.
    app.config["LO_ENGINE"] = {
        "get_cache": get_cache,
        "currency_symbol": _currency_symbol,
        "is_sales_closed": _is_sales_closed,
        "layout_model": layout_model,
        "store_games_cached": store_games_cached,
        "jackpots_live_or_cache": _get_jackpots_live_or_cache,
        "get_crm": get_crm,
    }
    import lo_routes
    lo_routes.register(app)
    import lo_homescreen
    lo_homescreen.register(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["WEBSITE_PORT"], debug=_env_bool("FLASK_DEBUG", False))

