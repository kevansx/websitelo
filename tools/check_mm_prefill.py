"""
Proves the Marketing Module's prefill API is configured and answering.

A 401 here has exactly one cause - the key is missing or wrong on one side -
and `GET /api/service` returns the contract in full from the code that
implements it, so a successful call proves the header rather than inferring it.

    python tools/check_mm_prefill.py
    python tools/check_mm_prefill.py --token <rt>

With a token it exchanges it too, and prints which fields came back rather than
their values: this is a terminal in an office and the values are somebody's
name and date of birth.
"""

from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mkt_api import load_mkt_config_from_env  # noqa: E402


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Marketing Module prefill readiness.")
    parser.add_argument("--token", default="", help="A reactivation token to exchange (optional).")
    parser.add_argument("--brand", default=os.environ.get("CRM_BRAND_SLUG") or "lottoexpress")
    args = parser.parse_args()

    cfg = load_mkt_config_from_env()
    if cfg is None:
        print("[FAIL] config: set MM_BASE_URL and MM_API_KEY in the server environment")
        return 2
    print(f"[OK]   config: {cfg.base_url}, key present ({len(cfg.api_key)} chars)")

    try:
        r = requests.get(
            f"{cfg.base_url}/api/service",
            headers={"Accept": "application/json", "X-MM-API-Key": cfg.api_key},
            timeout=10,
        )
    except Exception as e:
        print(f"[FAIL] /api/service: {type(e).__name__}: {e}")
        return 1

    if r.status_code == 401:
        print("[FAIL] /api/service: HTTP 401 - the key is missing or wrong on one side")
        return 1
    if r.status_code != 200:
        print(f"[FAIL] /api/service: HTTP {r.status_code}")
        return 1
    print("[OK]   /api/service: HTTP 200, the header is right")

    if not args.token:
        print("[SKIP] prefill: pass --token <rt> to exchange one")
        return 0

    try:
        body = requests.get(
            f"{cfg.base_url}/api/service/prefill",
            headers={"Accept": "application/json", "X-MM-API-Key": cfg.api_key},
            params={"brand": args.brand, "token": args.token},
            timeout=10,
        ).json()
    except Exception as e:
        print(f"[FAIL] prefill: {type(e).__name__}")
        return 1

    if not (isinstance(body, dict) and body.get("ok")):
        reason = (body or {}).get("reason") if isinstance(body, dict) else "unreadable"
        print(f"[OK]   prefill: declined, reason={reason} - the sign-up form stays empty and open")
        return 0

    prefill = body.get("prefill") if isinstance(body.get("prefill"), dict) else {}
    present = sorted(k for k, v in prefill.items() if str(v or "").strip())
    print(f"[OK]   prefill: campaign={body.get('campaign')}, fields present: {', '.join(present) or 'none'}")
    if "customer_number" not in present:
        print("[WARN] prefill: no customer_number - this account would not link to its AS400 history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
