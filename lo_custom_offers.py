"""
Custom offer links: https://lottosonline.com/o/<code> (spec v2, Marketing Module
shared-docs/custom-offer-links-spec.md, copied to docs/custom-offer-links-spec.md).

A supervisor creates an offer in the CRM (a description and an amount), and the customer
gets a link carrying nothing but a random code. They open it, see the offer and press Pay.
There is no login, no account page and no cart. The money is a wallet top-up for that
customer, and the agent places the tickets.

The fewest possible points of failure:

* The pages are a thin view over three CRM calls (5.1 read, 5.2 pay, 5.4 events), all
  server to server with the service key, each carrying the page load's X-Request-Id and the
  customer's own IP and browser, never this server's.
* Paying hands over exactly as the emailed payment link does, through the engine's
  `_hosted_start_redirect`: the same processor page, CRM card page or 3-D Secure step. This
  module never shows a card field and never sees card data.
* The template stands alone. It does not extend the site's layout, so no analytics, push
  prompt, banner, chat or home-screen prompt loads, and no third-party request can carry
  the code. No cookies are set and no session is used.
* Nothing here may break the page: recording events is best effort, and a CRM that can't be
  reached gets an error page with a reference, while a `crm_unreachable` event waits in a
  small local store until the CRM answers again.

Off until Lottos Online's brand is on the CRM: CUSTOM_OFFERS_ENABLED=1 turns it on, and until
then every /o/ address answers 404.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from flask import Response, abort, g, jsonify, make_response, render_template, request
from flask.globals import request_ctx

# A code is 22 URL-safe characters. Shorter ones still go to the CRM, because a truncated
# link is a failure worth recording; anything outside the URL-safe alphabet does not.
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

RATE_PER_MINUTE = 30
POLLS_PER_PAGE = 25  # the done page polls every 3 seconds for 60 seconds: 20, with room for a slow network
POLL_SECONDS, POLL_FOR_SECONDS = 3, 60

# The browser events the page may send (spec 8.2), each with the only detail fields kept.
BROWSER_EVENTS: dict[str, tuple[str, ...]] = {
    "page_rendered": ("ms", "in_app", "os", "browser", "viewport", "language", "timezone", "connection", "cookies"),
    "script_failed": ("script",),
    "js_error": ("message", "source", "line"),
    "pay_clicked": ("ms",),
    "redirected": ("host",),
    "left_page": ("last_state",),
    "callback_requested": ("state",),
}
_MAX_EVENTS_PER_BEACON = 50
_MAX_BEACON_BYTES = 32 * 1024

CURRENCY_PREFIX = {"EUR": "€", "USD": "US$", "GBP": "£", "AUD": "A$", "CAD": "C$", "NZD": "NZ$"}

NOT_CHARGED = "You have not been charged."


def enabled(app) -> bool:
    return bool(app.config.get("CUSTOM_OFFERS_ENABLED"))


def switched_on_in_env() -> bool:
    """CUSTOM_OFFERS_ENABLED from the environment: on only when it says so, off when missing."""
    return (os.environ.get("CUSTOM_OFFERS_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def fmt_money(cents: Any, currency: Any) -> str:
    try:
        amount = int(cents) / 100
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    prefix = CURRENCY_PREFIX.get(code)
    text = f"{amount:,.2f}"
    return f"{prefix}{text}" if prefix else f"{text} {code}".strip()


def reference(rid: str) -> str:
    return (rid or "")[:6].upper()


def new_request_id() -> str:
    return str(uuid.uuid4())


def request_id_from(value: Any) -> str:
    """The page load's request id when the browser sends one back, else a new one."""
    v = str(value or "").strip().lower()
    return v if _RID_RE.match(v) else new_request_id()


# --------------------------------------------------------------------------- local store
class Store:
    """
    A small SQLite file beside the CRM cache: the per-IP rate counter, and events that
    could not reach the CRM yet. Its own file, so nothing else on the site depends on it.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with self._connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS hits (k TEXT NOT NULL, at REAL NOT NULL, w INTEGER NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS hits_k_at ON hits(k, at)")
            c.execute(
                "CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, "
                "request_id TEXT NOT NULL, client_ip TEXT, user_agent TEXT, events TEXT NOT NULL, at REAL NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def hit(self, key: str, weight: int = 1) -> int:
        """Count a request against `key` and answer the total for the last minute."""
        now = time.time()
        with self._lock, self._connect() as c:
            if weight:
                c.execute("INSERT INTO hits(k, at, w) VALUES(?,?,?)", (key, now, int(weight)))
            if int(now) % 10 == 0:
                c.execute("DELETE FROM hits WHERE at < ?", (now - 3600,))
            row = c.execute("SELECT COALESCE(SUM(w), 0) AS n FROM hits WHERE k = ? AND at >= ?", (key, now - 60)).fetchone()
            return int(row["n"])

    def count_since(self, key: str, seconds: float) -> int:
        with self._connect() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(w), 0) AS n FROM hits WHERE k = ? AND at >= ?", (key, time.time() - seconds)
            ).fetchone()
            return int(row["n"])

    def keep(self, code: str, request_id: str, client_ip: str | None, user_agent: str | None, events: list) -> None:
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT INTO pending(code, request_id, client_ip, user_agent, events, at) VALUES(?,?,?,?,?,?)",
                (code, request_id, client_ip, user_agent, json.dumps(events), time.time()),
            )
            # Bounded: a week, and the latest 5,000 batches.
            c.execute("DELETE FROM pending WHERE at < ?", (time.time() - 7 * 24 * 3600,))
            c.execute("DELETE FROM pending WHERE id NOT IN (SELECT id FROM pending ORDER BY id DESC LIMIT 5000)")

    def waiting(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as c:
            return c.execute("SELECT * FROM pending ORDER BY id LIMIT ?", (limit,)).fetchall()

    def done(self, row_id: int) -> None:
        with self._lock, self._connect() as c:
            c.execute("DELETE FROM pending WHERE id = ?", (row_id,))


# --------------------------------------------------------------------------- events
def clean_events(raw: Any) -> list[dict[str, Any]]:
    """Only the browser events of spec 8.2, each with only its listed fields."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:_MAX_EVENTS_PER_BEACON]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("event") or "")
        allowed = BROWSER_EVENTS.get(name)
        if allowed is None:
            continue
        detail_in = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        detail: dict[str, Any] = {}
        for k in allowed:
            v = detail_in.get(k)
            if isinstance(v, bool) or v is None:
                if v is not None:
                    detail[k] = v
            elif isinstance(v, (int, float)):
                detail[k] = int(v) if float(v).is_integer() else round(float(v), 1)
            else:
                detail[k] = str(v)[:200]
        at = str(item.get("at") or "")[:40]
        out.append({"event": name, "at": at or _now_iso(), "detail": detail})
    return out


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- the routes
def register(app) -> None:
    app.config.setdefault("CUSTOM_OFFERS_ENABLED", switched_on_in_env())
    # Tests relay events inline; on the server they go on a thread so no page waits for them.
    app.config.setdefault("CUSTOM_OFFERS_INLINE_EVENTS", False)
    app.config.setdefault(
        "CUSTOM_OFFERS_CONTACT",
        {
            "phone": (os.environ.get("LO_SUPPORT_PHONE") or "+357 22 000254").strip(),
            "email": (os.environ.get("LO_SUPPORT_EMAIL") or "support@lottosonline.com").strip(),
            "whatsapp": (os.environ.get("LO_SUPPORT_WHATSAPP") or "").strip(),
        },
    )

    engine = app.config["LO_ENGINE"]
    get_crm: Callable = engine["get_crm"]
    payment_link_client_ip: Callable = engine["payment_link_client_ip"]
    hosted_start_redirect: Callable = engine["hosted_start_redirect"]
    seen_ip: Callable = engine["client_ip"]

    store_box: dict[str, Store] = {}

    def store() -> Store:
        path = app.config.get("CUSTOM_OFFERS_DB_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(os.environ.get("CRM_CACHE_DB_PATH", "./data/crm_cache.sqlite"))),
            "custom_offers.sqlite",
        )
        s = store_box.get(path)
        if s is None:
            s = store_box[path] = Store(path)
        return s

    import requests
    from crm_api import CRMError

    def _customer() -> tuple[str | None, str | None, str | None]:
        """The customer's own public IPv4 (the payment link's rule), browser and language."""
        return (
            payment_link_client_ip(),
            (request.headers.get("User-Agent") or "")[:500] or None,
            (request.headers.get("Accept-Language") or "")[:200] or None,
        )

    # ---- relaying events, never in the customer's way
    def _send_now(code: str, rid: str, ip: str | None, ua: str | None, events: list[dict]) -> bool:
        try:
            get_crm().custom_offer_events(code, rid, ip, ua, events)
            return True
        except Exception as e:  # noqa: BLE001 - recording must never break anything
            app.logger.warning("custom offer events not delivered (%s): %s", type(e).__name__, str(e)[:200])
            return False

    def _flush_waiting() -> None:
        try:
            for row in store().waiting():
                events = json.loads(row["events"])
                if not _send_now(row["code"], row["request_id"], row["client_ip"], row["user_agent"], events):
                    return
                store().done(row["id"])
        except Exception as e:  # noqa: BLE001
            app.logger.warning("custom offer event store unavailable: %s", type(e).__name__)

    def _relay(code: str, rid: str, ip: str | None, ua: str | None, events: list[dict]) -> None:
        def work() -> None:
            if _send_now(code, rid, ip, ua, events):
                _flush_waiting()
            else:
                try:
                    store().keep(code, rid, ip, ua, events)
                except Exception as e:  # noqa: BLE001
                    app.logger.warning("custom offer event store unavailable: %s", type(e).__name__)

        if app.config.get("CUSTOM_OFFERS_INLINE_EVENTS"):
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _crm_answered() -> None:
        """The CRM answered: anything kept while it couldn't be reached can go now."""
        try:
            if not store().waiting(1):
                return
        except Exception:  # noqa: BLE001
            return
        if app.config.get("CUSTOM_OFFERS_INLINE_EVENTS"):
            _flush_waiting()
        else:
            threading.Thread(target=_flush_waiting, daemon=True).start()

    def _crm_unreachable(code: str, rid: str, call: str, why: str, started: float) -> None:
        """Kept locally, and sent through 5.4 once the CRM answers again (spec 5.0)."""
        ip, ua, _lang = _customer()
        event = {"event": "crm_unreachable", "at": _now_iso(),
                 "detail": {"call": call, "reason": why, "ms": int((time.monotonic() - started) * 1000)}}
        app.logger.warning("custom offer CRM unreachable: call=%s reason=%s ref=%s", call, why, reference(rid))
        try:
            store().keep(code, rid, ip, ua, [event])
        except Exception as e:  # noqa: BLE001
            app.logger.warning("custom offer event store unavailable: %s", type(e).__name__)

    # ---- the CRM's answer, read once
    class Unreachable(Exception):
        pass

    class Unknown(Exception):
        pass

    def _read(code: str, view: str, rid: str) -> dict:
        started = time.monotonic()
        ip, ua, lang = _customer()
        try:
            resp = get_crm().custom_offer_get(code, view, rid, ip, ua, lang)
        except CRMError as e:
            status = getattr(e, "status_code", None)
            if status == 404:
                _crm_answered()
                raise Unknown() from e
            _crm_unreachable(code, rid, "5.1", f"http {status or 'error'}", started)
            raise Unreachable() from e
        except requests.Timeout as e:
            _crm_unreachable(code, rid, "5.1", "timeout", started)
            raise Unreachable() from e
        except requests.RequestException as e:
            _crm_unreachable(code, rid, "5.1", type(e).__name__, started)
            raise Unreachable() from e
        _crm_answered()
        if not isinstance(resp, dict) or resp.get("ok") is False:
            raise Unknown()
        return resp

    # ---- rendering
    def _page(state: str, *, code: str, rid: str, offer: dict | None = None, status: int = 200, **extra) -> Response:
        offer = offer or {}
        amount = fmt_money(offer.get("amount_cents"), offer.get("currency"))
        charge_block = offer.get("charge") if isinstance(offer.get("charge"), dict) else {}
        charge = fmt_money(charge_block.get("amount_cents"), charge_block.get("currency")) if charge_block else ""
        html = render_template(
            "lo/custom_offer.html",
            state=state,
            code=code,
            rid=rid,
            ref=reference(rid),
            offer=offer,
            first_name=str(offer.get("first_name") or "").strip(),
            amount=amount,
            charge=charge if charge and charge != amount else "",
            contact=app.config["CUSTOM_OFFERS_CONTACT"],
            not_charged=NOT_CHARGED,
            poll_seconds=POLL_SECONDS,
            poll_for_seconds=POLL_FOR_SECONDS,
            **extra,
        )
        return make_response(html, status)

    def _offer_or_page(code: str, view: str, rid: str) -> tuple[dict | None, Response | None]:
        try:
            return _read(code, view, rid), None
        except Unknown:
            _count_unknown()
            return None, _page("unavailable", code=code, rid=rid, status=404)
        except Unreachable:
            return None, _page("error", code=code, rid=rid, status=503)

    # ---- rate limits: 30 a minute per IP on /o/*, unknown codes count double
    def _ip_key() -> str:
        return "ip:" + (str(seen_ip() or request.remote_addr or "-"))[:64]

    def _count_unknown() -> None:
        try:
            store().hit(_ip_key(), 1)
        except Exception:  # noqa: BLE001
            pass

    @app.before_request
    def _custom_offer_gate():
        path = request.path or ""
        if not (path == "/o" or path.startswith("/o/")):
            return None
        if not enabled(app):
            abort(404)
        # No tracking parameters read or written here (spec 7.1): the affiliate hook ran first.
        g.lo_set_aff_cookie = None
        if request.endpoint == "custom_offer_status":
            return None  # counted per page load instead, so a slow bank can't lock a customer out
        try:
            total = store().hit(_ip_key(), 1)
        except Exception as e:  # noqa: BLE001 - a broken counter must not take the page down
            app.logger.warning("custom offer rate counter unavailable: %s", type(e).__name__)
            return None
        if total > RATE_PER_MINUTE:
            if request.endpoint == "custom_offer_track":
                return Response(status=204)
            return make_response("Too many requests. Please wait a minute and try again.", 429,
                                 {"Content-Type": "text/plain; charset=utf-8", "Retry-After": "60"})
        return None

    @app.after_request
    def _custom_offer_headers(resp: Response) -> Response:
        path = request.path or ""
        if path.startswith("/o/") and enabled(app):
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["Cache-Control"] = "no-store"
            # No cookies and no session on these pages: the session is swapped for one that is never saved.
            request_ctx.session = app.session_interface.make_null_session(app)
            resp.headers.pop("Set-Cookie", None)
        return resp

    def _valid(code: str) -> bool:
        return bool(_CODE_RE.match(code or ""))

    # ---- GET /o/<code>
    @app.get("/o/<code>")
    def custom_offer(code: str):
        rid = new_request_id()
        if not _valid(code):
            _count_unknown()
            return _page("unavailable", code="", rid=rid, status=404)
        offer, page = _offer_or_page(code, "page", rid)
        if page is not None:
            return page
        return _offer_state_page(code, rid, offer)

    def _offer_state_page(code: str, rid: str, offer: dict, error: str = "") -> Response:
        status = str(offer.get("status") or "").lower()
        if status == "paid":
            return _page("paid", code=code, rid=rid, offer=offer)
        if status != "open":
            return _page("unavailable", code=code, rid=rid, offer=offer)
        return _page("offer", code=code, rid=rid, offer=offer, error=error)

    # ---- POST /o/<code>/pay
    @app.post("/o/<code>/pay")
    def custom_offer_pay(code: str):
        rid = request_id_from(request.form.get("rid"))
        if not _valid(code):
            return _page("unavailable", code="", rid=rid, status=404)
        return_url = urljoin(_site_root(), f"o/{code}/done")
        ip, ua, lang = _customer()
        started = time.monotonic()
        try:
            resp = get_crm().custom_offer_pay(code, return_url, rid, ip, ua, lang)
        except CRMError as e:
            status = getattr(e, "status_code", None)
            if status == 404:
                _crm_answered()
                return _page("unavailable", code=code, rid=rid, status=404)
            if status is None or status >= 500:
                _crm_unreachable(code, rid, "5.2", f"http {status or 'error'}", started)
                return _page("error", code=code, rid=rid, status=503)
            _crm_answered()
            payload = getattr(e, "payload", None)
            said = str(payload.get("error") or "").strip() if isinstance(payload, dict) else ""
            return _refused(code, rid, said)
        except requests.Timeout:
            _crm_unreachable(code, rid, "5.2", "timeout", started)
            return _page("error", code=code, rid=rid, status=503)
        except requests.RequestException as e:
            _crm_unreachable(code, rid, "5.2", type(e).__name__, started)
            return _page("error", code=code, rid=rid, status=503)
        _crm_answered()

        answered = resp if isinstance(resp, dict) else {}
        if not answered.get("ok"):
            return _refused(code, rid, str(answered.get("error") or "").strip())

        nxt = answered.get("next")
        # A processor that wants a form posted to it. The engine's own hand-over page for this
        # is built on the site layout, which would load the site's analytics on an address
        # carrying the code, so the same form is posted from this page's bare template.
        form = nxt.get("redirect") if isinstance(nxt, dict) else None
        if isinstance(form, dict) and form.get("action_url") and not any(
            nxt.get(k) for k in ("redirect_url", "hosted_url", "next_action_url", "crm_card_form_url")
        ):
            _redirected(code, rid, str(form["action_url"]))
            return _page("handover", code=code, rid=rid, form=form)

        followed = hosted_start_redirect(nxt)
        if followed is not None:
            _redirected(code, rid, str(followed.headers.get("Location") or ""))
            return followed

        app.logger.error(
            "custom offer pay gave nothing to pay with: ref=%s mode=%r keys=%s",
            reference(rid),
            (nxt or {}).get("mode") if isinstance(nxt, dict) else None,
            sorted(nxt) if isinstance(nxt, dict) else type(nxt).__name__,
        )
        return _page("error", code=code, rid=rid, status=502,
                     error="We couldn't start this payment. " + NOT_CHARGED + " Please try again in a few minutes.")

    def _site_root() -> str:
        """
        The site the customer opened the link on, so the processor sends them back to it:
        https://lottosonline.com/ in production, https://www1.lottosonline.com/ on staging.
        The brand's canonical host would send a staging payment back to production. Plain http
        only for a local preview.
        """
        host = (request.host or "").strip().lower()
        bare = host.split(":")[0]
        if bare.endswith("lottosonline.com"):
            return f"https://{bare}/"
        if bare in ("localhost", "127.0.0.1") or bare.startswith("10.") or bare.startswith("192.168."):
            return f"http://{host}/"
        canonical = getattr(getattr(g, "brand", None), "canonical_domain", None)
        return f"https://{canonical or 'lottosonline.com'}/"

    def _refused(code: str, rid: str, said: str) -> Response:
        """The CRM refused the payment: its words, the reference, and the offer as it stands."""
        error = said or "We couldn't start this payment. " + NOT_CHARGED
        try:
            offer = _read(code, "poll", rid)
        except (Unknown, Unreachable):
            return _page("error", code=code, rid=rid, status=409, error=error)
        return _offer_state_page(code, rid, offer, error=error)

    def _redirected(code: str, rid: str, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return
        ip, ua, _lang = _customer()
        _relay(code, rid, ip, ua, [{"event": "redirected", "at": _now_iso(), "detail": {"host": host[:200]}}])

    # ---- GET /o/<code>/done
    @app.get("/o/<code>/done")
    def custom_offer_done(code: str):
        # The processor's return parameters are never read: only the CRM says what happened.
        rid = new_request_id()
        if not _valid(code):
            _count_unknown()
            return _page("unavailable", code="", rid=rid, status=404)
        offer, page = _offer_or_page(code, "done", rid)
        if page is not None:
            return page
        return _done_page(code, rid, offer)

    def _payment(offer: dict) -> dict:
        p = offer.get("payment")
        return p if isinstance(p, dict) else {}

    def _done_page(code: str, rid: str, offer: dict) -> Response:
        pay = _payment(offer)
        state = str(pay.get("state") or "none").lower()
        status = str(offer.get("status") or "").lower()
        if status == "paid" or state == "succeeded":
            return _page("paid", code=code, rid=rid, offer=offer)
        if state == "in_progress":
            return _page("checking", code=code, rid=rid, offer=offer)
        if state in ("declined", "failed_technical"):
            return _page("failed", code=code, rid=rid, offer=offer, message=str(pay.get("customer_message") or ""),
                         can_retry=bool(pay.get("can_retry")) and status == "open")
        if status != "open":
            return _page("unavailable", code=code, rid=rid, offer=offer)
        return _page("not_completed", code=code, rid=rid, offer=offer)

    # ---- GET /o/<code>/status: the done page's poll, so the browser never calls the CRM
    @app.get("/o/<code>/status")
    def custom_offer_status(code: str):
        rid = request_id_from(request.args.get("rid"))
        if not _valid(code):
            return jsonify({"state": "unavailable"}), 404
        try:
            if store().hit(f"poll:{rid}", 1) > POLLS_PER_PAGE or store().count_since(_ip_key(), 60) > RATE_PER_MINUTE:
                return jsonify({"state": "wait"}), 429
        except Exception:  # noqa: BLE001
            pass
        try:
            offer = _read(code, "poll", rid)
        except Unknown:
            return jsonify({"state": "unavailable"}), 404
        except Unreachable:
            return jsonify({"state": "error"}), 503
        pay = _payment(offer)
        state = str(pay.get("state") or "none").lower()
        if str(offer.get("status") or "").lower() == "paid":
            state = "succeeded"
        return jsonify({
            "state": state,
            "message": str(pay.get("customer_message") or ""),
            "can_retry": bool(pay.get("can_retry")) and str(offer.get("status") or "").lower() == "open",
        })

    # ---- POST /o/<code>/t: the page's events, relayed with the IP and browser added
    @app.post("/o/<code>/t")
    def custom_offer_track(code: str):
        if not _valid(code) or (request.content_length or 0) > _MAX_BEACON_BYTES:
            return Response(status=204)
        try:
            body = json.loads(request.get_data(cache=False, as_text=True)[:_MAX_BEACON_BYTES] or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response(status=204)
        if not isinstance(body, dict):
            return Response(status=204)
        events = clean_events(body.get("events"))
        if events:
            ip, ua, _lang = _customer()
            _relay(code, request_id_from(body.get("request_id")), ip, ua, events)
        return Response(status=204)

    # ---- POST /o/<code>/call: "Ask us to call you" without JavaScript
    @app.post("/o/<code>/call")
    def custom_offer_call(code: str):
        rid = request_id_from(request.form.get("rid"))
        if _valid(code):
            ip, ua, _lang = _customer()
            state = str(request.form.get("state") or "")[:200]
            _relay(code, rid, ip, ua, [{"event": "callback_requested", "at": _now_iso(), "detail": {"state": state}}])
        return _page("called", code=code if _valid(code) else "", rid=rid)
