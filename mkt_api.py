"""
The Marketing Module's service API, for reactivation sign-up links.

Only the prefill pair lives here. Everything else marketing-related reaches the
Module through the CRM, and this is the one thing the CRM does not front: the
Module holds a list of former customers who have no CRM record yet, and a
reactivation link carries a token that maps to their name, email and date of
birth so a 71-year-old is not asked to retype all of it.

Two rules run through the whole file.

The key never reaches a browser, which is why these are server-to-server and
not fetched from the sign-up page. The token in the customer's URL is opaque
and confers nothing; the details it maps to are personal and must never be in
a URL, a log line or an analytics payload.

And nothing here may block a sign-up. A token that has expired, a Module that
is down and a Module that is slow all have the same answer - no prefill, carry
on with an empty form - because the alternative is a campaign that stops
325,938 people from registering in order to save them some typing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class MktConfig:
    base_url: str
    api_key: str
    # Short on purpose. This call sits in front of a sign-up form, so a Module
    # having a bad day costs the customer a prefill, never the page.
    timeout_seconds: float = 3.0


def load_mkt_config_from_env() -> MktConfig | None:
    """
    The Module's service API, or None where it is not configured.

    Returning None rather than raising: the site has to run without this. Only
    reactivation links use it, and every other journey must be unaffected by
    its absence - including on a developer's machine and in the tests.
    """
    base_url = (os.environ.get("MM_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.environ.get("MM_API_KEY") or os.environ.get("MM_SERVICE_KEY") or "").strip()
    if not base_url or not api_key:
        return None
    return MktConfig(base_url=base_url, api_key=api_key)


class MktClient:
    def __init__(self, cfg: MktConfig):
        self.cfg = cfg
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "X-MM-API-Key": self.cfg.api_key}

    def prefill(self, brand: str, token: str) -> dict[str, Any] | None:
        """
        The sign-up details behind a reactivation token, or None for anything else.

        A dead token answers 404 with a reason, which is an ordinary outcome
        rather than an error: these links live thirty days and people forward
        them. The reason is returned to the caller to log; the token is not.
        """
        r = self.session.get(
            f"{self.cfg.base_url}/api/service/prefill",
            headers=self._headers(),
            params={"brand": brand, "token": token},
            timeout=self.cfg.timeout_seconds,
        )
        if r.status_code == 200:
            body = r.json()
            if isinstance(body, dict) and body.get("ok") and isinstance(body.get("prefill"), dict):
                return body
            return None
        if r.status_code == 404:
            try:
                body = r.json()
            except Exception:
                body = {}
            return {"ok": False, "reason": str((body or {}).get("reason") or "unknown")}
        r.raise_for_status()
        return None

    def prefill_registered(self, brand: str, token: str) -> None:
        """
        Tells the Module a prefilled form was actually completed.

        The gap between opening one and finishing it is the drop-off worth
        measuring, and only we know when the second happens. Nothing depends on
        it, so the caller treats a failure as nothing at all.
        """
        self.session.post(
            f"{self.cfg.base_url}/api/service/prefill/registered",
            headers=self._headers(),
            json={"brand": brand, "token": token},
            timeout=self.cfg.timeout_seconds,
        )
