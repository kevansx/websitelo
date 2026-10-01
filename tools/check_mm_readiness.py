from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _base() -> str:
    return os.environ.get("CRM_BASE_URL", "").strip().rstrip("/")


def _service_key() -> str:
    return os.environ.get("CRM_API_SERVICE_KEY", "").strip()


def _customer_token() -> str:
    return os.environ.get("READY_CHECK_TOKEN", "").strip()


def _headers(*, service_key: bool = False, token: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if service_key:
        h["X-CRM-API-Key"] = _service_key()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _request(method: str, path: str, *, service_key: bool = False, token: str | None = None, json_body: Any | None = None) -> tuple[int, Any]:
    url = f"{_base()}{path}"
    r = requests.request(method, url, headers=_headers(service_key=service_key, token=token), json=json_body, timeout=20)
    payload: Any
    try:
        payload = r.json()
    except Exception:
        payload = r.text
    return r.status_code, payload


def check_env() -> list[CheckResult]:
    out: list[CheckResult] = []
    out.append(CheckResult("env.CRM_BASE_URL", bool(_base()), "present" if _base() else "missing CRM_BASE_URL"))
    out.append(
        CheckResult(
            "env.CRM_API_SERVICE_KEY",
            bool(_service_key()),
            "present" if _service_key() else "missing CRM_API_SERVICE_KEY",
        )
    )
    return out


def check_health() -> CheckResult:
    try:
        sc, _ = _request("GET", "/api/v1/health")
        return CheckResult("api.health", sc == 200, f"HTTP {sc}")
    except Exception as e:
        return CheckResult("api.health", False, str(e))


def check_event_allowlist() -> list[CheckResult]:
    checks: list[CheckResult] = []
    canonical = ["signup_started", "checkout_started", "submit_attempt", "purchase_failed", "purchase_completed"]
    for ev in canonical:
        payload = {
            "event_id": f"readiness:{ev}:{uuid.uuid4().hex}",
            "event_type": ev,
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metadata": {"source": "readiness_check"},
        }
        try:
            sc, body = _request("POST", "/api/v1/marketing/events", service_key=True, json_body=payload)
            ok = sc == 200 and isinstance(body, dict) and bool(body.get("success"))
            checks.append(CheckResult(f"event.allowlist.{ev}", ok, f"HTTP {sc} {body!r}"))
        except Exception as e:
            checks.append(CheckResult(f"event.allowlist.{ev}", False, str(e)))
    return checks


def check_placements() -> list[CheckResult]:
    checks: list[CheckResult] = []
    for placement in ("home", "catalog", "checkout"):
        try:
            sc, body = _request("GET", f"/api/v1/marketing/banners?placement={placement}", service_key=True)
            ok = sc == 200 and isinstance(body, dict) and isinstance(body.get("banners"), list)
            count = len(body.get("banners", [])) if isinstance(body, dict) else 0
            checks.append(CheckResult(f"placement.{placement}", ok, f"HTTP {sc}, banners={count}"))
        except Exception as e:
            checks.append(CheckResult(f"placement.{placement}", False, str(e)))
    return checks


def check_tenant_offer_data() -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        sc, body = _request("GET", "/api/v1/bundles/example", service_key=True)
        # exact slug is tenant-specific; this check is advisory only.
        checks.append(CheckResult("tenant.bundle_endpoint", sc in {200, 404}, f"HTTP {sc}"))
        if sc == 404:
            checks.append(CheckResult("tenant.bundle_seed_data", False, "No known active bundle slug provided"))
        else:
            checks.append(CheckResult("tenant.bundle_seed_data", True, "Bundle endpoint reachable with sample slug"))
    except Exception as e:
        checks.append(CheckResult("tenant.bundle_endpoint", False, str(e)))
    return checks


def check_quote_anti_tamper() -> list[CheckResult]:
    checks: list[CheckResult] = []
    token = _customer_token()
    quote_payload_raw = os.environ.get("READY_CHECK_QUOTE_PAYLOAD_JSON", "").strip()
    tamper_payload_raw = os.environ.get("READY_CHECK_TAMPER_PAYLOAD_JSON", "").strip()

    if not token or not quote_payload_raw or not tamper_payload_raw:
        checks.append(
            CheckResult(
                "quote.anti_tamper",
                False,
                "skipped: set READY_CHECK_TOKEN, READY_CHECK_QUOTE_PAYLOAD_JSON and READY_CHECK_TAMPER_PAYLOAD_JSON",
            )
        )
        return checks

    try:
        quote_payload = json.loads(quote_payload_raw)
        tamper_payload = json.loads(tamper_payload_raw)
    except Exception as e:
        checks.append(CheckResult("quote.anti_tamper", False, f"invalid JSON env payload: {e}"))
        return checks

    try:
        sc_ok, body_ok = _request("POST", "/api/v1/checkout/quote", token=token, json_body=quote_payload)
        ok_quote = sc_ok == 200 and isinstance(body_ok, dict) and bool(body_ok.get("success"))
        checks.append(CheckResult("quote.valid_payload", ok_quote, f"HTTP {sc_ok}"))
    except Exception as e:
        checks.append(CheckResult("quote.valid_payload", False, str(e)))
        return checks

    try:
        sc_bad, body_bad = _request("POST", "/api/v1/checkout/quote", token=token, json_body=tamper_payload)
        rejected = sc_bad in {400, 409, 422}
        checks.append(CheckResult("quote.tampered_payload_rejected", rejected, f"HTTP {sc_bad} {body_bad!r}"))
    except Exception as e:
        checks.append(CheckResult("quote.tampered_payload_rejected", False, str(e)))
    return checks


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="LottoExpress Marketing Module readiness checks.")
    parser.add_argument("--strict", action="store_true", help="Fail on any non-passing check (including advisory checks).")
    args = parser.parse_args()

    results: list[CheckResult] = []
    results.extend(check_env())
    if not all(r.ok for r in results):
        for r in results:
            print(f"[{'OK' if r.ok else 'FAIL'}] {r.name}: {r.detail}")
        return 2

    results.append(check_health())
    results.extend(check_event_allowlist())
    results.extend(check_placements())
    results.extend(check_tenant_offer_data())
    results.extend(check_quote_anti_tamper())

    hard_fail_names = {
        "api.health",
        "event.allowlist.signup_started",
        "event.allowlist.checkout_started",
        "event.allowlist.submit_attempt",
        "event.allowlist.purchase_failed",
        "event.allowlist.purchase_completed",
        "placement.home",
        "placement.catalog",
        "placement.checkout",
    }

    failed_hard = [r for r in results if (r.name in hard_fail_names and not r.ok)]
    failed_any = [r for r in results if not r.ok]

    for r in results:
        print(f"[{'OK' if r.ok else 'FAIL'}] {r.name}: {r.detail}")

    if failed_hard:
        return 1
    if args.strict and failed_any:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

