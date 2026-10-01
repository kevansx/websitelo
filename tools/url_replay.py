"""
Replay every URL the old site had indexed against a running copy of this one.

This is the check that the cutover did not drop pages: the archive knows which
lottoexpress.com URLs answered 200, and each of them should now answer 200 or
land on a page that does, in a single hop. Anything that 404s or 500s is a page
Google will drop.

    python tools/url_replay.py                            # against localhost:5000
    python tools/url_replay.py --base https://lottoexpress.com
    python tools/url_replay.py --prefix /blog/            # just the blog
    python tools/url_replay.py --csv report.csv

Read-only: it issues GETs and writes nothing to the target.
"""

from __future__ import annotations

import argparse
import csv
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (compatible; lottoexpress-url-replay)"
CDX = (
    "https://web.archive.org/cdx/search/cdx?url={prefix}&matchType=prefix"
    "&output=json&fl=original,statuscode,mimetype&collapse=urlkey&limit=40000"
)
# Assets are not pages; they are checked separately and never block a cutover.
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".woff2", ".ttf", ".ico", ".map")


def archived_paths(prefix: str) -> list[str]:
    url = CDX.format(prefix=urllib.parse.quote(prefix, safe="/:"))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    rows = json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8", "replace"))
    seen: dict[str, None] = {}
    for original, status, _mime in rows[1:]:
        if status != "200":
            continue
        parsed = urllib.parse.urlparse(original)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        seen.setdefault(path, None)
    return list(seen)


def fetch(base: str, path: str, timeout: int = 30) -> tuple[int, str]:
    """One request, no redirect following, so the hop itself can be inspected."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "") or ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)[:60]


def check(base: str, path: str) -> tuple[str, int, str, int]:
    """Status of the URL, and of its target when it redirects."""
    status, location = fetch(base, path)
    hop_status = 0
    if status in (301, 302, 307, 308) and location:
        target = urllib.parse.urlparse(location)
        hop_path = (target.path or "/") + (("?" + target.query) if target.query else "")
        hop_status, _ = fetch(base, hop_path)
    return path, status, location, hop_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5000", help="site to replay against")
    parser.add_argument("--prefix", default="lottoexpress.com/", help="archive prefix to pull")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--assets", action="store_true", help="include images, css and js")
    parser.add_argument("--csv", default="", help="write the full result table here")
    args = parser.parse_args()

    print(f"reading the archive for {args.prefix} ...")
    paths = archived_paths(args.prefix)
    if not args.assets:
        paths = [p for p in paths if not p.split("?")[0].lower().endswith(ASSET_SUFFIXES)]
    print(f"replaying {len(paths)} URLs against {args.base}\n")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda p: check(args.base, p), paths))

    counts = Counter(status for _p, status, _l, _h in results)
    broken = [r for r in results if r[1] in (0, 404, 500, 502, 503)]
    # 410 is a decision, not a failure: WordPress's REST API, pingback endpoint
    # and comment feed are deliberately not coming back.
    gone = [r for r in results if r[1] == 410]
    chained = [r for r in results if r[3] in (301, 302, 307, 308)]
    dead_ends = [r for r in results if r[3] in (404, 500)]

    print("status              count")
    print("-" * 28)
    for status, count in sorted(counts.items()):
        print(f"{status if status else 'error':<18} {count}")
    if gone:
        print(f"\n{len(gone)} URLs answer 410 Gone (deliberate, not counted as broken)")

    for label, rows in (("BROKEN", broken), ("REDIRECT CHAINS", chained), ("REDIRECTS TO A DEAD PAGE", dead_ends)):
        if not rows:
            continue
        print(f"\n{label} ({len(rows)}):")
        for path, status, location, hop in rows[:40]:
            print(f"   {status:>3} -> {hop or '-':>3}  {path[:70]}  {location[:50]}")
        if len(rows) > 40:
            print(f"   ... and {len(rows) - 40} more")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["path", "status", "location", "target_status"])
            writer.writerows(sorted(results))
        print(f"\nwritten: {args.csv}")

    return 1 if (broken or dead_ends) else 0


if __name__ == "__main__":
    sys.exit(main())
