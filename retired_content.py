"""
The product pages for lotteries this store no longer sells.

Three products the old site sold are not in this CRM. Their pages were indexed
and carried real copy, so rather than redirect them into `/catalog` the app
serves them at their original URLs as reference pages that say plainly the game
is not available and point at the games that are.

The content is recovered from the Internet Archive by `tools/retired_harvest.py`
and stored as one JSON file per product in `content/retired/`. Nothing here
talks to the CRM: these are static pages by definition, because the CRM has no
data for a product it does not carry.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content", "retired")


@dataclass(frozen=True)
class PrizeTable:
    intro: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True)
class RetiredGame:
    slug: str
    name: str
    legacy_path: str
    results_slug: str
    results_aliases: list[str]
    alternatives: list[str]
    source: str
    captured: str
    title: str
    description: str
    h1: str
    intro: str
    highlights: list[dict[str, str]]
    quick_facts: list[dict[str, str]]
    prize_tiers: PrizeTable
    copy_heading: str
    sections: list[dict[str, str]]

    @property
    def path(self) -> str:
        """The canonical URL. Lowercase, like every other page on this site."""
        return f"/lotteries/{self.slug}"

    @property
    def seo_title(self) -> str:
        return self.title or f"{self.name} | Lotto Express"

    @property
    def seo_description(self) -> str:
        if self.description:
            return self.description
        return (
            f"{self.name} is no longer available through Lotto Express. "
            f"See how the game works and which lotteries you can play instead."
        )

    @property
    def captured_year(self) -> str:
        """
        Prize figures and draw dates in this copy are from when we sold the game.

        The page says so, and this is the year it says. Prize tables age badly
        and El Gordo's still names a 2023 draw date.
        """
        return self.captured[:4] if len(self.captured) >= 4 else ""


def _load_one(path: str) -> RetiredGame:
    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)
    tiers = raw.get("prize_tiers") or {}
    return RetiredGame(
        slug=str(raw["slug"]),
        name=str(raw.get("name") or raw["slug"]),
        legacy_path=str(raw.get("legacy_path") or ""),
        results_slug=str(raw.get("results_slug") or ""),
        results_aliases=[str(s) for s in (raw.get("results_aliases") or [])],
        alternatives=[str(c) for c in (raw.get("alternatives") or [])],
        source=str(raw.get("source") or ""),
        captured=str(raw.get("captured") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        h1=str(raw.get("h1") or ""),
        intro=str(raw.get("intro") or ""),
        highlights=list(raw.get("highlights") or []),
        quick_facts=list(raw.get("quick_facts") or []),
        prize_tiers=PrizeTable(
            intro=str(tiers.get("intro") or ""),
            headers=[str(h) for h in (tiers.get("headers") or [])],
            rows=[[str(c) for c in row] for row in (tiers.get("rows") or [])],
        ),
        copy_heading=str(raw.get("copy_heading") or ""),
        sections=list(raw.get("sections") or []),
    )


class RetiredLibrary:
    """Every recovered page, indexed by the URLs the old site used for it."""

    def __init__(self, content_dir: str = CONTENT_DIR) -> None:
        self.games: list[RetiredGame] = []
        self.by_slug: dict[str, RetiredGame] = {}
        self.by_results_slug: dict[str, RetiredGame] = {}
        if not os.path.isdir(content_dir):
            return
        for name in sorted(os.listdir(content_dir)):
            if not name.endswith(".json"):
                continue
            game = _load_one(os.path.join(content_dir, name))
            self.games.append(game)
            self.by_slug[game.slug] = game
            for slug in (game.results_slug, *game.results_aliases):
                if slug:
                    self.by_results_slug[slug.strip().strip("/").lower()] = game

    def get(self, slug: str) -> RetiredGame | None:
        return self.by_slug.get(str(slug or "").strip().strip("/").lower())

    def for_results_slug(self, slug: str) -> RetiredGame | None:
        return self.by_results_slug.get(str(slug or "").strip().strip("/").lower())

    def __len__(self) -> int:
        return len(self.games)


_library: RetiredLibrary | None = None


def library() -> RetiredLibrary:
    global _library
    if _library is None:
        _library = RetiredLibrary()
    return _library
