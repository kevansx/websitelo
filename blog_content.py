"""
The blog, served from files instead of WordPress.

The old `/blog/` was a WordPress install on the PHP host that no longer exists.
Its content was recovered from the Internet Archive by `tools/blog_harvest.py`
into `content/blog/<slug>.json`, one file per post, and this module turns those
files into the index, category and tag listings the old site had — at the same
URLs, so the pages Google already ranks keep working.

Posts are read once and cached. The cache is keyed on the newest file
modification time in the directory, so editing or adding a post shows up without
a restart, which is what makes the JSON files a workable way to publish.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content", "blog")

# WordPress's default, and what the archived `/blog/page/N/` URLs were cut on.
POSTS_PER_PAGE = 10

def slugify(value: str) -> str:
    """
    WordPress's term slugs: lowercase, punctuation to hyphens.

    Apostrophes are dropped rather than hyphenated, which is what makes
    "Winner's Story" the indexed `/blog/category/winners-story/` and not
    `winner-s-story`.
    """
    text = (value or "").strip().lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _parse_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    heading: str
    description: str
    body_html: str
    author: str
    categories: tuple[str, ...]
    tags: tuple[str, ...]
    hero_image: str
    word_count: int
    published: datetime | None
    modified: datetime | None

    @property
    def url(self) -> str:
        return f"/blog/{self.slug}/"

    @property
    def display_date(self) -> str:
        # Built by hand: the no-padding day directive differs between platforms.
        if not self.published:
            return ""
        return f"{self.published:%B} {self.published.day}, {self.published:%Y}"

    @property
    def iso_date(self) -> str:
        return self.published.strftime("%Y-%m-%d") if self.published else ""

    @property
    def card_image(self) -> str:
        """
        The picture that represents the post in a listing and when shared.

        Some posts lost their featured image: it was only ever served through
        the ShortPixel proxy and the archive never captured it. The first
        picture in the article is a truer stand-in than a generic brand image.
        """
        if self.hero_image:
            return self.hero_image
        found = re.search(r'<img[^>]+src="(/blog/wp-content/uploads/[^"]+)"', self.body_html)
        return found.group(1) if found else ""

    @property
    def show_hero(self) -> bool:
        """
        Whether the post page should print the hero image itself.

        WordPress showed the featured image above the article, but most of these
        posts also open with it inside the body, so printing both shows it twice.
        """
        return bool(self.hero_image) and self.hero_image not in self.body_html

    @property
    def reading_minutes(self) -> int:
        return max(1, round((self.word_count or 0) / 200))

    @property
    def excerpt(self) -> str:
        if self.description:
            return self.description
        text = re.sub(r"<[^>]+>", " ", self.body_html)
        text = re.sub(r"\s+", " ", text).strip()
        return (text[:157].rsplit(" ", 1)[0] + "…") if len(text) > 160 else text


@dataclass(frozen=True)
class Term:
    slug: str
    name: str
    kind: str  # "category" or "tag"
    posts: tuple[Post, ...]

    @property
    def url(self) -> str:
        return f"/blog/{self.kind}/{self.slug}/"


class Blog:
    """An immutable view of everything under content/blog."""

    def __init__(self, posts: Iterable[Post]):
        # Newest first, the order the index had. Undated posts sort last rather
        # than crashing the comparison.
        self.posts: tuple[Post, ...] = tuple(
            sorted(posts, key=lambda p: (p.published is not None, p.published or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        )
        self.by_slug: dict[str, Post] = {p.slug: p for p in self.posts}
        self.categories: dict[str, Term] = self._terms("category", lambda p: p.categories)
        self.tags: dict[str, Term] = self._terms("tag", lambda p: p.tags)

    def _terms(self, kind: str, pick) -> dict[str, Term]:
        names: dict[str, str] = {}
        members: dict[str, list[Post]] = {}
        for post in self.posts:
            for raw in pick(post):
                slug = slugify(raw)
                if not slug:
                    continue
                names.setdefault(slug, raw)
                members.setdefault(slug, []).append(post)
        return {
            slug: Term(slug=slug, name=names[slug], kind=kind, posts=tuple(items))
            for slug, items in sorted(members.items())
        }

    def term(self, kind: str, slug: str) -> Term | None:
        return (self.categories if kind == "category" else self.tags).get(slug)

    @property
    def latest_modified(self) -> datetime | None:
        dates = [p.modified or p.published for p in self.posts if (p.modified or p.published)]
        return max(dates) if dates else None


def paginate(posts: tuple[Post, ...], page: int, per_page: int = POSTS_PER_PAGE) -> tuple[tuple[Post, ...], int]:
    """Return the slice for `page` plus the page count (at least 1, even empty)."""
    total_pages = max(1, (len(posts) + per_page - 1) // per_page)
    start = (page - 1) * per_page
    return posts[start:start + per_page], total_pages


def _load_dir(directory: str) -> list[Post]:
    posts: list[Post] = []
    if not os.path.isdir(directory):
        return posts
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            continue
        slug = (raw.get("slug") or name[:-5]).strip()
        if not slug or not (raw.get("body_html") or "").strip():
            continue
        posts.append(
            Post(
                slug=slug,
                title=(raw.get("title") or raw.get("heading") or slug).strip(),
                heading=(raw.get("heading") or raw.get("title") or slug).strip(),
                description=(raw.get("description") or "").strip(),
                body_html=raw.get("body_html") or "",
                author=(raw.get("author") or "Lotto Express").strip(),
                categories=tuple(raw.get("categories") or ()),
                tags=tuple(raw.get("tags") or ()),
                hero_image=(raw.get("hero_image") or "").strip(),
                word_count=int(raw.get("word_count") or 0),
                published=_parse_date(raw.get("published") or ""),
                modified=_parse_date(raw.get("modified") or raw.get("published") or ""),
            )
        )
    return posts


def _fingerprint(directory: str) -> tuple[int, float]:
    """Cheap check for "has anything changed": file count and newest mtime."""
    try:
        entries = [e for e in os.scandir(directory) if e.name.endswith(".json")]
    except OSError:
        return (0, 0.0)
    return (len(entries), max((e.stat().st_mtime for e in entries), default=0.0))


_lock = threading.Lock()
_cache: tuple[tuple[int, float], Blog] | None = None


def blog(directory: str | None = None) -> Blog:
    global _cache
    path = directory or CONTENT_DIR
    if directory:
        return Blog(_load_dir(directory))
    stamp = _fingerprint(path)
    with _lock:
        if _cache is None or _cache[0] != stamp:
            _cache = (stamp, Blog(_load_dir(path)))
        return _cache[1]
