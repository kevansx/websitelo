"""LottosOnline public URL layer, registered on top of the inherited engine (app.py).

What lives here, and why it is separate from app.py:

* Exact legacy redirects. Generated from the URL contract (tools/build_contract.py) into
  content/legacy_redirects.json: every old URL that redirects today keeps redirecting to the same
  place, with temporary redirects made permanent. Matching is exact (path + query) first, then path.
* Affiliate capture. Old affiliate links are /?a=<affiliate>&c=<campaign> (+ optional b, f, and a
  Voluum click id in clid or v). The old site kept them in a one-year `abc` cookie on .lottosonline.com
  until registration. We keep writing and reading that same cookie (so a visitor who clicked on the
  old site is still attributed after cut-over) and feed it into the engine's attribution
  (session["mkt"]: src = a, cmp = c, tid = clid) which the register call sends to the CRM.
* Pages the engine does not have: lottery information pages (/lotteries, /lotteries/<slug>) and every
  content page captured from the live site (content/legacy_pages), rendered with the copy word for word.
* sitemap.xml and robots.txt for the LottosOnline URL set.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import hashlib

from flask import Response, abort, g, redirect, render_template, request, send_from_directory, session, url_for

import lo_lotteries
from lo_lotteries import LOTTERIES

CONTENT = Path(__file__).resolve().parent / "content"
BRAND_STATIC = Path(__file__).resolve().parent / "static" / "brands" / "lottosonline"
SITE_URL = "https://www.lottosonline.com"

AFF_COOKIE = "abc"
AFF_COOKIE_DOMAIN = ".lottosonline.com"
AFF_MAX_AGE = 60 * 60 * 24 * 365
_AFF_VALUE = re.compile(r"^[A-Za-z0-9_.:{}%\"\\/, -]{0,200}$")

# Paths the engine serves itself; a captured legacy page with the same path must not shadow them.
ENGINE_PAGES = {
    "/", "/lottery-tickets", "/winning-lottery-numbers", "/login", "/create-account", "/contact-us",
}


def _load_json(name: str, default):
    p = CONTENT / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


class LegacyPages:
    """Content captured from the live site, keyed by path."""

    def __init__(self) -> None:
        self.dir = CONTENT / "legacy_pages"
        self.index: dict[str, str] = _load_json("legacy_pages/_index.json", {})
        self._cache: dict[str, dict] = {}

    def get(self, path: str) -> dict | None:
        key = self.index.get(path)
        if not key:
            return None
        if key not in self._cache:
            f = self.dir / f"{key}.json"
            if not f.exists():
                return None
            self._cache[key] = json.loads(f.read_text(encoding="utf-8"))
        return self._cache[key]

    def paths(self) -> list[str]:
        return sorted(self.index)


def register(app) -> None:
    redirects: dict[str, str] = _load_json("legacy_redirects.json", {})
    temporary: dict[str, str] = _load_json("legacy_redirects_temporary.json", {})
    pages = LegacyPages()
    app.config["LO_LEGACY_PAGES"] = pages

    # ------------------------------------------------------------------ template helpers
    # Azure Front Door caches by path and ignores query strings, so a ?v= cache-buster would serve stale
    # CSS after a deploy (Live Lottos, 29 Sep). The content hash goes in the path instead.
    _hashes: dict[tuple, str] = {}

    def lo_asset(rel: str) -> str:
        f = BRAND_STATIC / rel
        key = (rel, f.stat().st_mtime_ns)
        h = _hashes.get(key)
        if h is None:
            h = _hashes[key] = hashlib.sha1(f.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:10]
        return f"/assets/lo/{h}/{rel}"

    @app.get("/assets/lo/<h>/<path:rel>")
    def lo_versioned_asset(h: str, rel: str):
        resp = send_from_directory(BRAND_STATIC, rel, max_age=31536000)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "LottosOnline",
        "legalName": "Marvicap Limited",
        "url": SITE_URL + "/",
        "logo": SITE_URL + "/images/logo_square_large.png",
        "sameAs": [
            "https://www.facebook.com/LottosOnline",
            "https://twitter.com/LottosOnline",
            "https://www.pinterest.com/lottosonlinecom/",
            "https://www.youtube.com/channel/UCclrNVGkE3JFv44ZNRC5RkA",
        ],
    }
    org_json = json.dumps(org, separators=(",", ":"))

    def lo_breadcrumb_jsonld(crumbs) -> str:
        items = [{"@type": "ListItem", "position": i + 1, "name": name, "item": SITE_URL + href}
                 for i, (name, href) in enumerate(crumbs)]
        return json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items},
                          separators=(",", ":"))

    import os as _os

    # Tags fire only in production, so local and staging testing never pollute analytics or ad data.
    _prod = (_os.environ.get("WEBSITE_ENV") or "").strip().lower() == "production"

    def _tag(name: str, default: str) -> str:
        v = _os.environ.get(name)
        return (v if v is not None else default).strip() if _prod else ""

    lo_tags = {
        "gtm_id": _tag("LO_GTM_ID", "GTM-TZZNV5S"),
        "gtm_loader": _os.environ.get("LO_GTM_LOADER", "https://gtm.lottosonline.com/jrfugtxg.js"),
        "gtm_noscript": _os.environ.get("LO_GTM_NOSCRIPT", "https://gtm.lottosonline.com/ns.html"),
        "mixpanel_token": _tag("LO_MIXPANEL_TOKEN", "9495e8a5218fe9330aecb78fac09e5cc"),
        "fb_pixel_id": _tag("LO_FB_PIXEL_ID", "1670423983232657"),
        "zendesk_key": _tag("LO_ZENDESK_KEY", "c313db13-7d37-4ec8-9a85-06f112b0507d"),
    }

    @app.context_processor
    def _lo_context():
        return {
            "lo_tags": lo_tags,
            "lo_asset": lo_asset,
            "lo_year": datetime.now(timezone.utc).year,
            "lo_org_jsonld": org_json,
            "lo_breadcrumb_jsonld": lo_breadcrumb_jsonld,
            "lo_lotteries": LOTTERIES,
            "lo_page": pages.get,
        }

    # ------------------------------------------------------------------ jackpots + artwork
    LEGACY_IMAGES = Path(__file__).resolve().parent / "static" / "legacy_images"
    SYMBOLS = {"USD": "US$", "EUR": "€", "GBP": "£", "AUD": "AU$", "CAD": "CA$", "NZD": "NZ$", "ZAR": "R"}

    def fmt_jackpot(amount, currency: str) -> str:
        """The old site's style: "US$440 Million", "AU$20 Million", "£500,000" (with € for EUR)."""
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            return ""
        if amt <= 0:
            return ""
        sym = SYMBOLS.get((currency or "").upper(), (currency or "") + " ")
        if amt >= 1_000_000:
            m = amt / 1_000_000
            txt = f"{m:,.0f}" if m >= 100 or m == int(m) else f"{m:,.2f}".rstrip("0").rstrip(".")
            return f"{sym}{txt} Million"
        return f"{sym}{amt:,.0f}"

    _jp_memo: dict = {"at": 0.0, "by_code": {}}

    def jackpots_by_code() -> dict:
        import time as _t
        if _t.time() - _jp_memo["at"] < 30 and _jp_memo["by_code"]:
            return _jp_memo["by_code"]
        eng = app.config.get("LO_ENGINE") or {}
        rows = []
        try:
            rows, _ = eng["jackpots_live_or_cache"](timeout_seconds=4)
        except Exception:
            try:
                rows = eng["get_cache"]().get_cached_jackpots()
            except Exception:
                rows = []
        out = {}
        for j in rows or []:
            code = j.get("game_code")
            if code:
                out[code] = j
        _jp_memo.update(at=_t.time(), by_code=out)
        return out

    def lo_jackpot(game_code: str) -> dict | None:
        j = jackpots_by_code().get(game_code)
        if not j:
            return None
        amount = j.get("jackpot_total")
        cur = j.get("currency")
        if amount is None and isinstance(j.get("jackpot"), dict):
            amount, cur = j["jackpot"].get("amount"), j["jackpot"].get("currency")
        cutoff = j.get("cutoff_at_utc") or j.get("next_draw_utc")
        if cutoff and not str(cutoff).endswith("Z") and "+" not in str(cutoff):
            cutoff = str(cutoff) + "Z"
        return {
            "display": fmt_jackpot(amount, cur),
            "amount": amount,
            "currency": cur,
            "cutoff_iso": cutoff,
            "draw_date": j.get("draw_date"),
            "rise_pct": lo_lotteries.rise_pct(game_code, amount),
            "raw": j,
        }

    def lo_ball(lot) -> str:
        return f"/images/lottery-assets/logo_large_round_{lot.legacy_code}.png"

    @app.get("/favicon.ico")
    def favicon_ico():
        return send_from_directory(BRAND_STATIC / "img", "favicon.ico", max_age=2592000)

    @app.get("/images/<path:rel>")
    def legacy_image(rel: str):
        # The old site's /images/ paths, kept for the artwork the new pages reuse and for the image-search
        # URLs Search Console reports. Only files we copied across are served.
        return send_from_directory(LEGACY_IMAGES, rel, max_age=2592000)

    app.jinja_env.globals.update(lo_jackpot=lo_jackpot, lo_ball=lo_ball, lo_fmt_jackpot=fmt_jackpot)

    def home_rows() -> list[dict]:
        rows = [{"lottery": l, "jp": lo_jackpot(l.game_code) or {}, "price": None} for l in LOTTERIES if l.sells]
        rows.sort(key=lambda r: (-(r["jp"].get("rise_pct") or -1), -(float(r["jp"].get("amount") or 0))))
        return rows

    def featured_rows(rows: list[dict]) -> list[dict]:
        # The old home page's four cards were the four biggest jackpots (in euros), not the top of the table.
        def eur(r):
            raw = (r["jp"] or {}).get("raw") or {}
            try:
                return float(raw.get("jackpot_eur") or 0)
            except (TypeError, ValueError):
                return 0.0
        return sorted(rows, key=eur, reverse=True)[:4]

    app.config["LO_HOME_ROWS"] = home_rows
    app.jinja_env.globals["lo_featured_rows"] = featured_rows

    # ------------------------------------------------------------------ redirects + affiliates
    @app.before_request
    def _lo_legacy_redirect():
        full = request.full_path.rstrip("?") if request.query_string else request.path
        target = redirects.get(full) or redirects.get(request.path)
        if target and target != request.path:
            # Keep tracking parameters on a redirected landing (an affiliate link to an old URL).
            qs = request.query_string.decode("latin-1")
            if qs and "?" not in target and full not in redirects:
                target = f"{target}?{qs}"
            return redirect(target, code=301)
        # Old PHP entry points with ?lottery=<slug> that are not in the table: same rule as the contract.
        section = {"/lottery-info.php": ("/lotteries", "info"), "/play.php": ("/lottery-tickets", "sells"),
                   "/lottery-results.php": ("/winning-lottery-numbers", "results")}.get(request.path)
        if section and request.args.get("lottery"):
            lot = lo_lotteries.by_slug(request.args["lottery"])
            base_path, wants = section
            return redirect(f"{base_path}/{lot.slug}" if lot and getattr(lot, wants) else base_path, code=301)
        tmp = temporary.get(full) or temporary.get(request.path)
        if tmp is None and request.path.startswith("/my-account/"):
            tmp = "/login"  # any other old account page: same behaviour as the old site for a logged-out visitor
        if tmp:
            if tmp == "/login" and session.get("crm_token"):
                return redirect(url_for("account"), code=302)
            if tmp == "/login":
                return redirect(url_for("login", next=url_for("account")), code=302)
            return redirect(tmp, code=302)
        return None

    @app.before_request
    def _lo_affiliate_capture():
        a = (request.args.get("a") or "").strip()
        b = (request.args.get("b") or "").strip()
        c = (request.args.get("c") or "").strip()
        f = (request.args.get("f") or "").strip()
        clid = (request.args.get("clid") or request.args.get("v") or "").strip()
        if ((a and c) or f) and all(_AFF_VALUE.match(x) for x in (a, b, c, f)):
            g.lo_set_aff_cookie = f"{a}-{b}-{c}-{f}"
        else:
            cookie = request.cookies.get(AFF_COOKIE) or ""
            parts = (cookie.split("-") + ["", "", "", ""])[:4]
            a, b, c, f = parts
        mkt = session.get("mkt", {}) if isinstance(session.get("mkt", {}), dict) else {}
        changed = False
        if a and mkt.get("intent") != "lifecycle" and not mkt.get("src"):
            mkt["src"], changed = a[:64], True
        if c and not mkt.get("cmp"):
            mkt["cmp"], changed = c[:64], True
        if clid and _AFF_VALUE.match(clid):
            mkt["tid"], changed = clid[:64], True
            session["voluum_click_id"] = clid[:128]
        if changed:
            session["mkt"] = mkt

    @app.after_request
    def _lo_affiliate_cookie(resp):
        val = getattr(g, "lo_set_aff_cookie", None)
        if val:
            host = (request.host or "").split(":")[0]
            domain = AFF_COOKIE_DOMAIN if host.endswith("lottosonline.com") else None
            resp.set_cookie(AFF_COOKIE, val, max_age=AFF_MAX_AGE, path="/", domain=domain, samesite="Lax")
        return resp

    # ------------------------------------------------------------------ lottery information pages
    @app.get("/lotteries")
    def lotteries_index():
        page = pages.get("/lotteries")
        return render_template("lo/lotteries_index.html", page=page, lotteries=[l for l in LOTTERIES if l.info])

    @app.get("/lotteries/<lo_info:game_code>")
    def lottery_info(game_code: str):
        lot = lo_lotteries.by_game_code(game_code)
        page = pages.get(lo_lotteries.info_path(lot))
        if page is None:
            abort(404)
        return render_template("lo/lottery_info.html", page=page, lottery=lot)

    # ------------------------------------------------------------------ captured content pages
    def _legacy_page_view():
        page = pages.get(request.path)
        if page is None:
            abort(404)
        return render_template("lo/legacy_page.html", page=page)

    for path in pages.paths():
        if path in ENGINE_PAGES or path.startswith(("/lottery-tickets/", "/winning-lottery-numbers/", "/lotteries")):
            continue
        endpoint = "legacy_page_" + re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
        app.add_url_rule(path, endpoint=endpoint, view_func=_legacy_page_view, methods=["GET"])

    # ------------------------------------------------------------------ sitemap + robots
    def sitemap_paths() -> list[str]:
        out = ["/", "/lottery-tickets", "/lotteries", "/winning-lottery-numbers"]
        for l in LOTTERIES:
            if l.sells:
                out.append(lo_lotteries.play_path(l))
        for l in LOTTERIES:
            if l.info:
                out.append(lo_lotteries.info_path(l))
        for l in LOTTERIES:
            if l.results:
                out.append(lo_lotteries.results_path(l))
        for p in ("/how-to-play-lottery-online", "/faqs", "/about-us", "/contact-us", "/payment-methods",
                  "/VIP-rewards", "/spin-to-win", "/raffle-tickets", "/terms-and-conditions", "/privacy-policy",
                  "/AML-Policy.php", "/create-account", "/login"):
            out.append(p)
        return out

    app.config["LO_SITEMAP_PATHS"] = sitemap_paths

    @app.get("/sitemap.xml")
    def sitemap_xml():
        today = datetime.now(timezone.utc).date().isoformat()
        rows = [f"  <url><loc>{escape(SITE_URL + p)}</loc><lastmod>{today}</lastmod></url>" for p in sitemap_paths()]
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"
        return Response(body, mimetype="application/xml")

    @app.get("/robots.txt")
    def robots_txt():
        # Same private areas the old robots.txt fenced off, plus the engine's transactional paths.
        lines = [
            "User-agent: *",
            "Disallow: /checkout",
            "Disallow: /cart",
            "Disallow: /my-account/",
            "Disallow: /account",
            "Disallow: /wallet/",
            "Disallow: /orders",
            "Disallow: /admin/",
            "Disallow: /support/",
            "",
            f"Sitemap: {SITE_URL}/sitemap.xml",
            "",
        ]
        return Response("\n".join(lines), mimetype="text/plain")
