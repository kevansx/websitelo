"""
Recover the product pages for lotteries the store no longer sells.

Three products the old site sold are not in this CRM: Australian Powerball,
Spanish Lotto 6/49 La Primitiva and El Gordo. Their pages carried around two
thousand words each of purpose-written copy — draw schedule, odds, prize tiers
and a set of FAQs — and they are still indexed. Redirecting them to `/catalog`
threw all of that away, so this pulls the copy back out of the Internet Archive
and the app serves it at the original URLs.

Run it from the repo root:

    python tools/retired_harvest.py            # content/retired/<slug>.json
    python tools/retired_harvest.py --force    # refetch pages already written

Build-time only: it needs beautifulsoup4 and lxml, which the app does not. The
app reads the JSON this writes and nothing else.
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup, Tag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "content", "retired")

SITE = "https://www.lottoexpress.com"
UA = "Mozilla/5.0 (compatible; lottoexpress-retired-recovery)"

# The archived pages, and where each one should send someone who wanted to play.
# `alternatives` are CRM game codes we do sell that are the closest match: the
# Australian pair for Australian Powerball, the pan-European draws for the two
# Spanish games. They are the reason the page is worth keeping.
PAGES: list[dict] = [
    {
        "slug": "australian-powerball",
        "path": "/lotteries/Australian-Powerball",
        "name": "Australian Powerball",
        "results_slug": "australian-powerball-winning-numbers",
        "alternatives": ["oz-lotto-au", "sat-lotto-au", "powerball"],
    },
    {
        "slug": "spanish-lotto-649-la-primitiva",
        "path": "/lotteries/Spanish-Lotto-649-La-Primitiva",
        "name": "Spanish Lotto 6/49 La Primitiva",
        "results_slug": "spanish-lotto-649-la-primitiva-winning-numbers",
        # The old site also indexed a shorter results slug for the same game.
        "results_aliases": ["spanish-lotto-winning-numbers", "spanish-lotto"],
        "alternatives": ["euromillions", "eurojackpot", "superenalotto"],
    },
    {
        "slug": "el-gordo",
        "path": "/lotteries/Syndicate/El-Gordo",
        "name": "El Gordo",
        "results_slug": "el-gordo-winning-numbers",
        "alternatives": ["euromillions", "eurojackpot", "superenalotto"],
    },
]

# Links inside the recovered copy point at the old site's URL scheme.
LEGACY_LINKS = {
    "/terms-and-conditions": "/terms",
    "/privacy-policy": "/privacy",
    "/responsible-gaming": "/responsible-gaming",
    "/about-us": "/about",
    "/contact-us": "/contact",
    "/faq": "/faq",
    "/register": "/register",
    "/login": "/login",
    "/lotteries": "/catalog",
    "/lottery-results": "/results",
}


def _cp1252_fallback(err: UnicodeDecodeError):
    """The old site emitted stray Windows-1252 bytes inside otherwise valid UTF-8."""
    return err.object[err.start : err.end].decode("cp1252", "replace"), err.end


codecs.register_error("cp1252_fallback", _cp1252_fallback)


def http_get(url: str, timeout: int = 120, attempts: int = 4) -> bytes:
    """Fetch with backoff: the archive rate-limits and times out under load."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if getattr(exc, "code", None) in (404, 403):
                raise
            time.sleep(2 * (i + 1) ** 2)
    raise RuntimeError(f"giving up on {url}: {last}")


def newest_capture(path: str) -> str:
    """The last good capture is the last state the page was in before it went."""
    url = (
        "https://web.archive.org/cdx/search/cdx?output=json&filter=statuscode:200"
        f"&limit=-1&collapse=digest&url={urllib.parse.quote('lottoexpress.com' + path, safe='')}"
    )
    rows = json.loads(http_get(url).decode("utf-8", "replace"))
    if len(rows) < 2:
        raise RuntimeError(f"no archived 200 for {path}")
    return rows[-1][1]


def raw_capture(path: str, timestamp: str) -> str:
    """`id_` returns the original bytes: no archive toolbar, no rewritten URLs."""
    return http_get(f"https://web.archive.org/web/{timestamp}id_/{SITE}{path}").decode(
        "utf-8", "cp1252_fallback"
    )


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def _rewrite_links(node: Tag) -> None:
    for a in node.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(href)
            if "lottoexpress.com" not in parsed.netloc.lower():
                a["rel"] = "nofollow noopener"
                continue
            href = parsed.path or "/"
        target = LEGACY_LINKS.get(href.rstrip("/").lower() or "/")
        a["href"] = target or href


def _paragraph_html(container: Tag) -> str:
    """
    The body copy, as paragraphs.

    The old markup repeated each section's icon inside the first paragraph for
    the mobile layout; that duplicate is dropped rather than carried over.
    """
    out: list[str] = []
    for p in container.find_all("p"):
        for img in p.find_all("img"):
            img.decompose()
        _rewrite_links(p)
        for tag in p.find_all(True):
            attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "rel")}
            tag.attrs = attrs
        html = p.decode_contents().strip()
        if html:
            out.append(f"<p>{html}</p>")
    return "\n".join(out)


def extract_highlights(soup: BeautifulSoup) -> list[dict]:
    """
    The icon blocks beside the intro: draw day, odds, and a closer.

    Each one is a row pairing an icon column with the text, which is what marks
    it out from the other `h3`s on the page — El Gordo's contact-us footer is
    also an `h3.sub-heading` but has no icon and is not a highlight.
    """
    out: list[dict] = []
    details = soup.select_one(".lotteryDetails")
    if not details:
        return out
    for row in details.select(".row"):
        if not row.select_one(".about-us-side-image"):
            continue
        h3 = row.find(["h3", "h4"])
        body = h3.find_next_sibling("p") if h3 else None
        heading, text = _text(h3), _text(body)
        if heading and text:
            out.append({"heading": heading, "text": text})
    return out


def extract_quick_facts(soup: BeautifulSoup) -> list[dict]:
    """Label/value pairs from the "Quick Facts" accordion."""
    out: list[dict] = []
    for label in soup.select("p.lottoDetailHeader"):
        value = label.find_next_sibling("p")
        if value is None or value.get("class") and "lottoDetailHeader" in value.get("class"):
            continue
        name, text = _text(label), _text(value)
        if name and text:
            out.append({"label": name, "value": text})
    return out


def extract_prize_tiers(soup: BeautifulSoup) -> dict:
    """
    The prize table.

    It was laid out as Bootstrap rows rather than a `<table>`, with a duplicate
    label div in each cell for the mobile breakpoint. Each row reduces to the
    three real cells; the mobile labels are recognised by their class and
    dropped, which also identifies the header row.
    """
    odds = soup.select_one(".lotteryDetailOdds")
    if not odds:
        return {}
    intro = _text(odds.find("p"))
    headers: list[str] = []
    rows: list[list[str]] = []
    for row in odds.find_all("div", class_="row", recursive=False):
        head_cells = [_text(c) for c in row.select(".lottoDetailHeader")]
        if head_cells and not row.select(".lotteryDetailOddsMobile"):
            headers = head_cells
            continue
        cells: list[str] = []
        for col in row.find_all("div", recursive=False):
            for mobile in col.select(".lotteryDetailOddsMobile"):
                mobile.decompose()
            cells.append(_text(col))
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            rows.append(cells)
    if not rows:
        return {}
    return {"intro": intro, "headers": headers, "rows": rows}


def extract_sections(soup: BeautifulSoup) -> tuple[str, list[dict]]:
    """The "Know more about..." block: a heading and the FAQ-style sections."""
    copy = soup.select_one("#lotteryPageCopy, .lotteryPageCopy")
    if not copy:
        return "", []
    heading = _text(copy.find(["h2"]))
    sections: list[dict] = []
    for section in copy.find_all("section"):
        text_col = section.select_one(".lotteryPageCopyText") or section
        h3 = text_col.find(["h3", "h4"])
        body = _paragraph_html(text_col)
        if h3 is not None and body:
            sections.append({"heading": _text(h3), "body_html": body})
    return heading, sections


def extract_intro(soup: BeautifulSoup) -> str:
    details = soup.select_one(".lotteryDetails")
    if not details:
        return ""
    lead = details.select_one("p.pageHeading")
    body = lead.find_next_sibling("p") if lead else details.find("p")
    return _text(body)


def extract(html: str, page: dict, timestamp: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()

    meta = soup.find("meta", attrs={"name": "description"})
    description = (meta.get("content") or "").strip() if meta else ""
    title = _text(soup.title)
    h1 = _text(soup.find("h1"))
    copy_heading, sections = extract_sections(soup)

    # Two of the archived pages were already serving the site-wide title by the
    # time they were last captured; a generic one is worse than none.
    if title.lower().startswith("lotto express | play the world"):
        title = ""
    if description.strip().startswith("1) Register a free account"):
        description = ""

    return {
        "slug": page["slug"],
        "name": page["name"],
        "legacy_path": page["path"],
        "results_slug": page["results_slug"],
        "results_aliases": page.get("results_aliases") or [],
        "alternatives": page["alternatives"],
        "source": f"https://web.archive.org/web/{timestamp}/{SITE}{page['path']}",
        "captured": timestamp,
        "title": title,
        "description": description,
        "h1": h1,
        "intro": extract_intro(soup),
        "highlights": extract_highlights(soup),
        "quick_facts": extract_quick_facts(soup),
        "prize_tiers": extract_prize_tiers(soup),
        "copy_heading": copy_heading,
        "sections": sections,
    }


def word_count(rec: dict) -> int:
    parts = [rec.get("intro", ""), *(s["body_html"] for s in rec.get("sections", []))]
    parts += [h["text"] for h in rec.get("highlights", [])]
    return len(re.sub(r"<[^>]+>", " ", " ".join(parts)).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="refetch pages already written")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    failures = 0
    for page in PAGES:
        dest = os.path.join(OUT_DIR, f"{page['slug']}.json")
        if os.path.exists(dest) and not args.force:
            print(f"  skip   {page['slug']} (already recovered)")
            continue
        try:
            timestamp = newest_capture(page["path"])
            rec = extract(raw_capture(page["path"], timestamp), page, timestamp)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL   {page['slug']}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(
            f"  ok     {page['slug']}: {word_count(rec)} words, "
            f"{len(rec['sections'])} sections, {len(rec['quick_facts'])} facts, "
            f"{len(rec.get('prize_tiers', {}).get('rows', []))} prize tiers"
        )
        time.sleep(2)

    print(f"\nrecovered {len(PAGES) - failures} of {len(PAGES)} pages into content/retired")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
