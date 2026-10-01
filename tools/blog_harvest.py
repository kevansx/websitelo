"""
Rebuild the WordPress blog from the Internet Archive.

The blog was a WordPress install served at `/blog/` on the old PHP host. That
host is gone: nothing answers there any more, and 594 archived `/blog/` URLs are
still in Google's index. This recovers the content so the app can serve it at
exactly the same URLs.

Run it from the repo root:

    python tools/blog_harvest.py --posts          # content/blog/<slug>.json
    python tools/blog_harvest.py --images         # static/blog/uploads/**
    python tools/blog_harvest.py --posts --images

It is a build-time tool, not part of the running site: it needs beautifulsoup4,
lxml and Pillow, which the app itself does not. The app only reads the JSON and
the image files this writes. Re-running is safe — existing files are skipped
unless --force is given, so an interrupted run just resumes.
"""

from __future__ import annotations

import argparse
import codecs
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from bs4 import BeautifulSoup, NavigableString

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "blog")
UPLOADS_DIR = os.path.join(ROOT, "static", "blog", "uploads")

SITE = "https://www.lottoexpress.com"
UA = "Mozilla/5.0 (compatible; lottoexpress-blog-recovery)"
CDX = (
    "https://web.archive.org/cdx/search/cdx?url=lottoexpress.com/blog/"
    "&matchType=prefix&output=json&fl=original,timestamp,statuscode,mimetype&limit=40000"
)

# The old marketing stack. None of it should come back with the content.
JUNK_HOSTS = ("hubspot.com", "hscta.net", "googletagmanager.com", "monsterinsights.com")
KEEP_IFRAME_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com")

# Legacy product URLs the posts link to, mapped to where those pages live now,
# so the blog's internal links land directly instead of through a redirect.
LEGACY_LINKS = {
    "/lotteries/american-powerball": "/play/powerball",
    "/lotteries/american-mega-millions": "/play/megamillions",
    "/lotteries/euromillions": "/play/euromillions",
    "/lotteries/euromillions-superdraw": "/play/euromillions",
    "/lotteries/eurojackpot": "/play/eurojackpot",
    "/lotteries/french-lotto": "/play/lotto-fr",
    "/lotteries/german-lotto": "/play/lotto-6aus49",
    "/lotteries/irish-lotto": "/play/lotto-ie",
    "/lotteries/oz-lotto": "/play/oz-lotto-au",
    "/lotteries/australian-lotto-645": "/play/sat-lotto-au",
    "/lotteries/australian-superdraw": "/play/sat-lotto-au",
    "/lotteries/superenalotto": "/play/superenalotto",
    "/lotteries/promotions": "/promotions",
    # Products the store no longer sells: the catalogue is the honest landing.
    "/lotteries/australian-powerball": "/catalog",
    "/lotteries/syndicate/el-gordo": "/catalog",
    "/lottery-results/american-mega-millions-winning-numbers": "/results/megamillions",
    "/lottery-results/euromillions-winning-numbers": "/results/euromillions",
    "/lottery-results": "/results",
    "/about-us": "/about-us",
    "/contact-us": "/contact-us",
    "/faq": "/faq",
    "/responsible-gaming": "/responsible-gaming",
    "/terms-and-conditions": "/terms-and-conditions",
    "/privacy-policy": "/privacy-policy",
    "/register": "/register",
    "/login": "/login",
}


# --------------------------------------------------------------------------
# archive plumbing
# --------------------------------------------------------------------------


def _cp1252_fallback(err: UnicodeDecodeError):
    """
    The old site emitted the odd Windows-1252 byte (0x92 for a curly apostrophe)
    inside otherwise valid UTF-8. Decoding the whole page as cp1252 would mangle
    the genuine multi-byte characters, so only the bad bytes are reinterpreted.
    """
    return err.object[err.start:err.end].decode("cp1252", "replace"), err.end


codecs.register_error("cp1252_fallback", _cp1252_fallback)


def decode_html(data: bytes) -> str:
    return data.decode("utf-8", "cp1252_fallback")


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
            code = getattr(exc, "code", None)
            if code in (404, 403):
                raise
            time.sleep(2 * (i + 1) ** 2)
    raise RuntimeError(f"giving up on {url}: {last}")


def raw_capture(path: str, timestamp: str) -> str:
    """`id_` returns the original bytes: no archive toolbar, no rewritten URLs."""
    url = f"https://web.archive.org/web/{timestamp}id_/{SITE}{path}"
    return decode_html(http_get(url))


def latest_captures() -> dict[str, str]:
    """Newest successful capture per `/blog/` path — the last state of the page."""
    rows = json.loads(http_get(CDX).decode("utf-8", "replace"))
    best: dict[str, str] = {}
    for original, timestamp, status, _mime in rows[1:]:
        if status != "200":
            continue
        path = urllib.parse.urlparse(original).path
        if not path.startswith("/blog"):
            continue
        if timestamp > best.get(path, ""):
            best[path] = timestamp
    return best


def is_post_path(path: str) -> bool:
    if not re.match(r"^/blog/[^/]+/?$", path):
        return False
    head = path[len("/blog/"):].strip("/").lower()
    return head not in {"category", "tag", "author", "page", "feed", "comments", "wp-json", "wp-content"} and not head.endswith(".php")


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for blob in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(blob.string or "")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            out.extend(n for n in data.get("@graph", [data]) if isinstance(n, dict))
        elif isinstance(data, list):
            out.extend(n for n in data if isinstance(n, dict))
    return out


def node_of_type(nodes: Iterable[dict[str, Any]], *wanted: str) -> dict[str, Any]:
    for node in nodes:
        raw = node.get("@type")
        types = raw if isinstance(raw, list) else [raw]
        if any(t in wanted for t in types if t):
            return node
    return {}


def meta(soup: BeautifulSoup, **attrs: str) -> str:
    tag = soup.find("meta", attrs=attrs)
    return (tag.get("content") or "").strip() if tag else ""


def as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v]


def clean_title(raw: str, h1: str) -> str:
    """Yoast left a few titles truncated to a dangling separator on the live site."""
    title = re.sub(r"\s+", " ", raw or "").strip()
    title = re.sub(r"[\s\-–—|·]+$", "", title).strip()
    if len(title) < 8 and h1:
        title = h1
    return title


def local_upload_path(url: str) -> str:
    """
    Reduce any form of an upload URL to the site path it should be served at.

    ShortPixel proxied every image, so the src reads
    `https://sp-ao.shortpixel.ai/client/<transforms>/https://www.lottoexpress.com/blog/...`
    — the real URL is the tail.
    """
    if not url:
        return ""
    tail = url
    if "shortpixel.ai" in url:
        idx = url.rfind("http")
        if idx > 0:
            tail = url[idx:]
    parsed = urllib.parse.urlparse(tail)
    if parsed.scheme and "lottoexpress.com" not in (parsed.netloc or ""):
        return ""
    path = parsed.path or ""
    return path if "/blog/wp-content/uploads/" in path else ""


def best_img_src(img) -> str:
    """Pick the real image out of the lazy-load placeholders ShortPixel left."""
    for attr in ("data-src", "src", "data-lazy-src"):
        candidate = (img.get(attr) or "").strip()
        if candidate and not candidate.startswith("data:"):
            resolved = local_upload_path(candidate)
            if resolved:
                return resolved
    for attr in ("srcset", "data-srcset"):
        raw = (img.get(attr) or "").strip()
        for part in raw.split(","):
            candidate = part.strip().split(" ")[0]
            resolved = local_upload_path(candidate)
            if resolved:
                return resolved
    return ""


def rewrite_link(href: str) -> str:
    """
    Point in-body links at canonical paths rather than through a 301.

    Sub-pages of a game ("/lotteries/Irish-Lotto/Lucky-5") belong to the game,
    and the campaign tags the old posts carried on internal links only create
    duplicate URLs now, so they are dropped.
    """
    if not href or href.startswith(("#", "mailto:", "tel:")):
        return href
    # One post links to "lottoexpress.com" with no scheme, which the page's
    # <base href="/"> would resolve to a path that does not exist.
    if not href.startswith(("/", "http")) and href.split("/", 1)[0].endswith("lottoexpress.com"):
        rest = href.split("/", 1)[1] if "/" in href else ""
        href = "/" + rest
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc and "lottoexpress.com" not in parsed.netloc:
        return href

    path = (parsed.path or "/").rstrip("/").lower() or "/"
    mapped = LEGACY_LINKS.get(path)
    while mapped is None and path.count("/") > 1:
        path = path.rsplit("/", 1)[0]
        mapped = LEGACY_LINKS.get(path)
    if mapped:
        return mapped + (f"#{parsed.fragment}" if parsed.fragment else "")

    rebuilt = parsed.path or "/"
    if parsed.query and not parsed.netloc:
        rebuilt += "?" + parsed.query
    if parsed.fragment:
        rebuilt += "#" + parsed.fragment
    return rebuilt


def clean_body(node) -> tuple[str, set[str]]:
    """Strip the old marketing stack and localise every asset reference."""
    images: set[str] = set()

    for tag in node.select("script, noscript, style, link, form"):
        tag.decompose()

    # Snapshot the tree first: decomposing during a live traversal leaves the
    # iterator holding gutted tags.
    for tag in list(node.find_all(True)):
        if tag.decomposed or tag.parent is None:
            continue
        if tag.name == "iframe":
            src = tag.get("src") or ""
            if not any(host in src for host in KEEP_IFRAME_HOSTS):
                tag.decompose()
            continue
        classes = " ".join(tag.get("class") or [])
        ident = tag.get("id") or ""
        if "hs-cta" in classes or "hs-cta" in ident or "hs_cos" in classes:
            tag.decompose()

    for img in list(node.select("img")):
        if img.decomposed or img.parent is None:
            continue
        src = best_img_src(img)
        if not src:
            wrapper = img.find_parent("figure") or img.find_parent("a")
            (wrapper or img).decompose()
            continue
        images.add(src)
        img["src"] = src
        img["loading"] = "lazy"
        img["decoding"] = "async"
        for attr in ("srcset", "data-srcset", "data-src", "data-lazy-src", "sizes", "width", "height"):
            img.attrs.pop(attr, None)
        if not (img.get("alt") or "").strip():
            img["alt"] = ""

    for anchor in list(node.select("a[href]")):
        if anchor.decomposed or anchor.parent is None:
            continue
        anchor["href"] = rewrite_link(anchor.get("href", ""))
        target = anchor.get("href", "")
        if target.startswith("http") and "lottoexpress.com" not in target:
            anchor["rel"] = "nofollow noopener"
            anchor["target"] = "_blank"

    # Empty paragraphs and wrappers left behind by the removals.
    for tag in list(node.find_all(["p", "div", "figure", "span"])):
        if tag.decomposed or tag.parent is None:
            continue
        if not tag.find(["img", "iframe", "br", "hr"]) and not tag.get_text(strip=True):
            tag.decompose()

    html = "".join(str(child) for child in node.children).strip()
    html = re.sub(r"(\s*\n\s*){3,}", "\n\n", html)
    return html, images


def extract_post(html: str, path: str, timestamp: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    nodes = ld_nodes(soup)
    article = node_of_type(nodes, "Article", "BlogPosting", "NewsArticle")

    author = ""
    ref = (article.get("author") or {}) if isinstance(article.get("author"), dict) else {}
    author = (ref.get("name") or "").strip()
    if not author and ref.get("@id"):
        for node in nodes:
            if node.get("@id") == ref["@id"] and node.get("name"):
                author = str(node["name"]).strip()
                break

    h1_tag = soup.find("h1")
    h1 = re.sub(r"\s+", " ", h1_tag.get_text(" ", strip=True)) if h1_tag else ""

    body_node = soup.select_one("div.entry-content") or soup.select_one("div.post-content")
    if body_node is None:
        raise ValueError("no article body found")
    body_html, images = clean_body(body_node)
    if len(body_html) < 200:
        raise ValueError(f"body suspiciously short ({len(body_html)} chars)")

    hero = local_upload_path(meta(soup, property="og:image"))
    if hero:
        images.add(hero)

    categories = [c for c in as_list(article.get("articleSection"))]
    if not categories:
        categories = [a.get_text(strip=True) for a in soup.select('a[rel~="category"]')]
    tags = [t for t in as_list(article.get("keywords"))]
    if not tags:
        tags = [a.get_text(strip=True) for a in soup.select('a[rel~="tag"]')]

    title_raw = soup.title.get_text(strip=True) if soup.title else ""
    slug = path.strip("/").split("/")[-1]

    return {
        "slug": slug,
        "url": f"/blog/{slug}/",
        "title": clean_title(title_raw, h1),
        "heading": h1 or clean_title(title_raw, h1),
        "description": re.sub(r"\s+", " ", meta(soup, name="description") or "").strip(),
        "published": (article.get("datePublished") or "").strip(),
        "modified": (article.get("dateModified") or article.get("datePublished") or "").strip(),
        "author": author or "Lotto Express",
        "categories": sorted({c.strip() for c in categories if c and c.strip()}),
        "tags": sorted({t.strip() for t in tags if t and t.strip()}),
        "hero_image": hero,
        "word_count": int(article.get("wordCount") or 0) or len(re.findall(r"\w+", BeautifulSoup(body_html, "lxml").get_text(" "))),
        "body_html": body_html,
        "images": sorted(images),
        "source_capture": timestamp,
    }


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------


def harvest_posts(captures: dict[str, str], force: bool) -> list[dict[str, Any]]:
    os.makedirs(POSTS_DIR, exist_ok=True)
    paths = sorted(p for p in captures if is_post_path(p))
    print(f"posts to recover: {len(paths)}")

    recovered: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    for i, path in enumerate(paths, 1):
        slug = path.strip("/").split("/")[-1]
        target = os.path.join(POSTS_DIR, f"{slug}.json")
        if os.path.exists(target) and not force:
            recovered.append(json.load(open(target, encoding="utf-8")))
            print(f"  [{i:3}/{len(paths)}] skip {slug}")
            continue
        try:
            html = raw_capture(path, captures[path])
            post = extract_post(html, path, captures[path])
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(post, fh, indent=1, ensure_ascii=False)
            recovered.append(post)
            print(f"  [{i:3}/{len(paths)}] ok   {slug}  ({post['word_count']} words, {len(post['images'])} images)")
        except Exception as exc:  # noqa: BLE001
            failures.append((path, str(exc)[:120]))
            print(f"  [{i:3}/{len(paths)}] FAIL {slug}: {str(exc)[:90]}")
        time.sleep(0.3)

    print(f"\nrecovered {len(recovered)} posts, {len(failures)} failed")
    for path, err in failures:
        print(f"   {path}: {err}")
    return recovered


def relink_posts() -> None:
    """
    Re-apply link rewriting to already-recovered posts.

    Refetching 115 pages to fix a mapping is wasteful; the body is already on
    disk, so the rewrite runs against that.
    """
    changed = 0
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        target = os.path.join(POSTS_DIR, name)
        with open(target, encoding="utf-8") as fh:
            post = json.load(fh)
        soup = BeautifulSoup(post.get("body_html") or "", "lxml")
        for anchor in soup.select("a[href]"):
            anchor["href"] = rewrite_link(anchor.get("href", ""))
        body = soup.body
        rebuilt = "".join(str(child) for child in body.children).strip() if body else str(soup)
        if rebuilt != post.get("body_html"):
            post["body_html"] = rebuilt
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(post, fh, indent=1, ensure_ascii=False)
            changed += 1
    print(f"relinked {changed} posts")


def local_target(path: str) -> str:
    rel = path.split("/blog/wp-content/uploads/", 1)[1]
    return os.path.join(UPLOADS_DIR, *rel.split("/"))


def save_image(path: str, data: bytes) -> None:
    target = local_target(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(optimise(data, path))


def recover_missing_images(prune: bool) -> None:
    """
    Second pass for images the first pass could not find.

    Every image on the old site was served through the ShortPixel proxy, so for
    many of them the archive only ever crawled the proxy URL — the direct
    `/blog/wp-content/uploads/...` address was never fetched and so is not in
    the CDX index. The original proxy URL is still in the archived page, so the
    post capture is re-read to recover it.

    With --prune, any image that is still unavailable is removed from the post
    body: a missing picture is better than a broken one.
    """
    wanted: dict[str, list[str]] = {}
    posts: dict[str, dict[str, Any]] = {}
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        post = json.load(open(os.path.join(POSTS_DIR, name), encoding="utf-8"))
        posts[post["slug"]] = post
        srcs = set(re.findall(r'<img[^>]+src="(/blog/wp-content/uploads/[^"]+)"', post["body_html"]))
        if post.get("hero_image"):
            srcs.add(post["hero_image"])
        for src in srcs:
            if not os.path.exists(local_target(src)):
                wanted.setdefault(src, []).append(post["slug"])

    print(f"images referenced by posts but not on disk: {len(wanted)}")
    recovered: set[str] = set()

    # 1. The archive may hold the direct URL even though the prefix listing did
    #    not show it; ask for the nearest capture rather than a known timestamp.
    for path in sorted(wanted):
        try:
            data = http_get(f"https://web.archive.org/web/2024id_/{SITE}{path}", attempts=2)
        except Exception:  # noqa: BLE001
            continue
        if data[:1] not in (b"<", b""):
            save_image(path, data)
            recovered.add(path)
    print(f"  recovered by direct lookup: {len(recovered)}")

    # 2. Otherwise pull the proxy URL out of the page it appeared on.
    still = [p for p in sorted(wanted) if p not in recovered]
    originals: dict[str, str] = {}
    checked: set[str] = set()
    for path in still:
        for slug in wanted[path]:
            post = posts[slug]
            timestamp = post.get("source_capture")
            if not timestamp or slug in checked:
                continue
            checked.add(slug)
            try:
                html = raw_capture(f"/blog/{slug}/", timestamp)
            except Exception:  # noqa: BLE001
                continue
            for raw_src in re.findall(r'(?:src|data-src|data-lazy-src)="([^"]+)"', html):
                resolved = local_upload_path(raw_src)
                if resolved and resolved not in originals and raw_src.startswith("http"):
                    originals[resolved] = raw_src
            time.sleep(0.2)

    for path in still:
        source = originals.get(path)
        if not source:
            continue
        timestamp = ""
        for slug in wanted[path]:
            timestamp = posts[slug].get("source_capture") or ""
            if timestamp:
                break
        try:
            data = http_get(f"https://web.archive.org/web/{timestamp}id_/{source}", attempts=2)
        except Exception:  # noqa: BLE001
            continue
        if data[:1] not in (b"<", b""):
            save_image(path, data)
            recovered.add(path)
    print(f"  recovered in total: {len(recovered)} of {len(wanted)}")

    lost = [p for p in sorted(wanted) if p not in recovered]
    if lost:
        print(f"\nnot in the archive at all ({len(lost)}):")
        for path in lost[:20]:
            print("   ", path)

    if prune and lost:
        gone = set(lost)
        changed = 0
        for slug, post in posts.items():
            soup = BeautifulSoup(post["body_html"], "lxml")
            removed = 0
            for img in list(soup.select("img")):
                if img.get("src") in gone:
                    (img.find_parent("figure") or img).decompose()
                    removed += 1
            if post.get("hero_image") in gone:
                post["hero_image"] = ""
                removed += 1
            if not removed:
                continue
            body = soup.body
            post["body_html"] = "".join(str(c) for c in body.children).strip() if body else post["body_html"]
            post["images"] = [i for i in (post.get("images") or []) if i not in gone]
            with open(os.path.join(POSTS_DIR, f"{slug}.json"), "w", encoding="utf-8") as fh:
                json.dump(post, fh, indent=1, ensure_ascii=False)
            changed += 1
        print(f"pruned unrecoverable images from {changed} posts")


def optimise(data: bytes, path: str) -> bytes:
    """Recompress without changing dimensions, format or filename."""
    try:
        from PIL import Image
    except ImportError:
        return data
    ext = path.rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png"):
        return data
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        buf = io.BytesIO()
        if ext in ("jpg", "jpeg"):
            img.convert("RGB").save(buf, "JPEG", quality=82, optimize=True, progressive=True)
        else:
            img.save(buf, "PNG", optimize=True)
        out = buf.getvalue()
        return out if 0 < len(out) < len(data) else data
    except Exception:  # noqa: BLE001
        return data


def harvest_images(captures: dict[str, str], posts: list[dict[str, Any]], force: bool) -> None:
    wanted: set[str] = set()
    for post in posts:
        wanted.update(post.get("images") or [])
        if post.get("hero_image"):
            wanted.add(post["hero_image"])
    # Anything else the archive holds under uploads, so old image URLs still resolve.
    for path in captures:
        if "/blog/wp-content/uploads/" in path and path.rsplit(".", 1)[-1].lower() in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            wanted.add(path)

    print(f"\nimages to recover: {len(wanted)}")
    saved = before = after = 0
    missing: list[str] = []
    for i, path in enumerate(sorted(wanted), 1):
        rel = path.split("/blog/wp-content/uploads/", 1)[1]
        target = os.path.join(UPLOADS_DIR, *rel.split("/"))
        if os.path.exists(target) and not force:
            continue
        timestamp = captures.get(path)
        if not timestamp:
            # Referenced by a post but never captured at that exact URL.
            for known, known_ts in captures.items():
                if known.endswith(rel):
                    timestamp = known_ts
                    break
        if not timestamp:
            missing.append(path)
            continue
        try:
            data = http_get(f"https://web.archive.org/web/{timestamp}id_/{SITE}{path}")
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{path} ({str(exc)[:50]})")
            continue
        small = optimise(data, path)
        before += len(data)
        after += len(small)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(small)
        saved += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(wanted)}] {saved} saved")
        time.sleep(0.2)

    print(f"\nsaved {saved} images: {before/1024/1024:.1f} MB fetched -> {after/1024/1024:.1f} MB on disk")
    if missing:
        print(f"not recoverable ({len(missing)}):")
        for path in missing[:25]:
            print("   ", path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts", action="store_true", help="recover post content")
    parser.add_argument("--images", action="store_true", help="recover uploads")
    parser.add_argument("--relink", action="store_true", help="re-apply link rewriting to recovered posts")
    parser.add_argument("--missing", action="store_true", help="retry images the first pass could not find")
    parser.add_argument("--prune", action="store_true", help="with --missing, drop images the archive does not have")
    parser.add_argument("--force", action="store_true", help="re-fetch files that already exist")
    args = parser.parse_args()
    if not (args.posts or args.images or args.relink or args.missing):
        parser.error("choose --posts, --images, --relink and/or --missing")

    if args.relink and not (args.posts or args.images or args.missing):
        relink_posts()
        return 0

    if args.missing and not (args.posts or args.images):
        recover_missing_images(args.prune)
        return 0

    print("reading the archive index...")
    captures = latest_captures()
    print(f"captured /blog/ URLs with a 200: {len(captures)}")

    posts: list[dict[str, Any]] = []
    if args.posts:
        posts = harvest_posts(captures, args.force)
    elif args.images and os.path.isdir(POSTS_DIR):
        for name in sorted(os.listdir(POSTS_DIR)):
            if name.endswith(".json") and not name.startswith("_"):
                posts.append(json.load(open(os.path.join(POSTS_DIR, name), encoding="utf-8")))

    if args.images:
        harvest_images(captures, posts, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
