"""
Import legacy Lotto Express lottery page content (from PHP) into Jinja partials.

We extract two blocks:
- lotteryDetails (accordion + highlights): <div class="... lotteryDetails">...</div>
- lotteryPageCopy (Know more...): <div id="lotteryPageCopy">...</div>

Then we clean CDN PHP snippets and write:
- templates/content/lottery_<game_code>_details.html
- templates/content/lottery_<game_code>_copy.html

This keeps content "ready" for future new CRM games: if a partial doesn't exist,
the app falls back to generic content templates.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _clean_php(html: str) -> str:
    # Replace legacy CDN prefix with root.
    html = html.replace("<?php echo $GLOBALS['cdn']; ?>", "/")
    html = html.replace('<?php echo $GLOBALS["cdn"]; ?>', "/")
    # Drop any remaining php tags inside the extracted blocks.
    html = re.sub(r"<\?php[\s\S]*?\?>", "", html)
    # Normalize indentation a bit.
    html = re.sub(r"\r\n", "\n", html)
    return html.strip() + "\n"


def _extract_div_block(src: str, start_marker: str) -> str | None:
    i0 = src.find(start_marker)
    if i0 < 0:
        return None
    i = i0
    depth = 0
    # Find the first "<div" at or after marker.
    first_open = src.find("<div", i0)
    if first_open < 0:
        return None
    i = first_open
    depth = 1

    open_re = re.compile(r"<div\b", re.IGNORECASE)
    close_re = re.compile(r"</div\s*>", re.IGNORECASE)

    pos = i + 4
    while pos < len(src):
        m_open = open_re.search(src, pos)
        m_close = close_re.search(src, pos)
        if not m_close:
            break
        if m_open and m_open.start() < m_close.start():
            depth += 1
            pos = m_open.end()
            continue
        depth -= 1
        pos = m_close.end()
        if depth <= 0:
            return src[i0:pos]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(__file__)), help="repo root")
    ap.add_argument("--legacy", default=None, help="legacy lotteries dir (defaults to ../wwwroot/wwwroot/lotteries)")
    ap.add_argument("--force", action="store_true", help="overwrite existing partials")
    args = ap.parse_args()

    repo_root = Path(args.root).resolve()
    legacy_dir = Path(args.legacy).resolve() if args.legacy else (repo_root.parent / "wwwroot" / "wwwroot" / "lotteries")
    out_dir = repo_root / "templates" / "content"
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "American-Mega-Millions.php": "megamillions",
        "American-Powerball.php": "powerball",
        "EuroMillions.php": "euromillions",
        "EuroJackpot.php": "eurojackpot",
        "French-Lotto.php": "lotto-fr",
        "SuperEnalotto.php": "superenalotto",
        "Australian-Lotto-645.php": "sat-lotto-au",
        "Oz-Lotto.php": "oz-lotto-au",
    }

    details_marker = '<div class="col-xs-12 col-sm-12 col-md-12 lotteryDetails">'
    copy_marker = '<div id="lotteryPageCopy">'

    for fn, game_code in mapping.items():
        src_path = legacy_dir / fn
        if not src_path.exists():
            print("missing_legacy:", src_path)
            continue
        src = _read_text(src_path)

        details = _extract_div_block(src, details_marker)
        copy = _extract_div_block(src, copy_marker)

        if not details:
            print("missing_details:", fn)
        if not copy:
            print("missing_copy:", fn)

        if details:
            out_details = out_dir / f"lottery_{game_code}_details.html"
            if out_details.exists() and not args.force:
                print("skip_exists:", out_details.name)
            else:
                out_details.write_text(_clean_php(details), encoding="utf-8")
                print("wrote:", out_details.name)

        if copy:
            out_copy = out_dir / f"lottery_{game_code}_copy.html"
            if out_copy.exists() and not args.force:
                print("skip_exists:", out_copy.name)
            else:
                out_copy.write_text(_clean_php(copy), encoding="utf-8")
                print("wrote:", out_copy.name)


if __name__ == "__main__":
    main()

