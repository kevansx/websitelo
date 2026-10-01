from __future__ import annotations

import argparse
import re

import requests


def _extract_between(text: str, start: str, end: str) -> str | None:
    i = text.find(start)
    if i < 0:
        return None
    j = text.find(end, i + len(start))
    if j < 0:
        return None
    return text[i + len(start) : j]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument(
        "--kind",
        choices=["banner", "tile"],
        default="banner",
        help="banner extracts #bannerJackpotAmount; tile tries to find lottoTicketAmount near a legacy link",
    )
    ap.add_argument("--legacy_link", default="/lotteries/French-Lotto")
    args = ap.parse_args()

    html = requests.get(args.url, timeout=10).text
    if args.kind == "banner":
        # <p id="bannerJackpotAmount">...</p>
        block = _extract_between(html, 'id="bannerJackpotAmount">', "</p>")
        if block is None:
            print("bannerJackpotAmount: MISSING")
            return
        # Strip tags if any
        txt = re.sub(r"<[^>]+>", "", block).strip()
        print("bannerJackpotAmount:", txt)
        return

    # tile mode
    idx = html.find(args.legacy_link)
    if idx < 0:
        print("tile: MISSING_LINK")
        return
    seg = html[max(0, idx - 600) : idx + 600]
    m = re.search(r'class="lottoTicketAmount"\s*>\s*([^<]+)\s*<', seg)
    if not m:
        print("tile_amount: MISSING")
        return
    print("tile_amount:", m.group(1).strip())


if __name__ == "__main__":
    main()

