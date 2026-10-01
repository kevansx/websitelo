"""
Quick template smoke test: renders account.html with mock data.

Usage (from repo root):
  python lottoexpress-website/tools/smoke_render_account.py
"""

from __future__ import annotations

import os
import sys

from flask import render_template

# Ensure repo root (lottoexpress-website/) is on sys.path when running from tools/.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import app as site  # noqa: E402


def main() -> None:
    with site.app.test_request_context("/account"):
        # Ensure before_request hooks run so `g.brand` and other globals exist.
        site.app.preprocess_request()
        html = render_template(
            "account.html",
            me={"first_name": "Test", "last_name": "User", "email": "test@example.com", "phone": "123"},
            wallet={"currency": "USD", "balance_cents": 12345, "withdrawable_cents": 10000},
            wallet_transactions=[],
            recent_orders=[],
        )
        print("Rendered OK. First 300 chars:\n")
        print(html[:300])


if __name__ == "__main__":
    main()

