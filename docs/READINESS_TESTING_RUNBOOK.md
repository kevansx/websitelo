## Lotto Express — Readiness Testing Runbook (Test + Production)

This is the Lotto Express launch-readiness runbook, aligned to Winnow's structure but tailored to the tools currently available in this repo.

### What you get today
- **CRM/MM readiness checks (fast, no browser)** via `tools/check_mm_readiness.py`
- **Template smoke render** via `tools/smoke_render_account.py`
- **Core app health check** via `/health`

### Current gap vs Winnow
- This repo does **not** yet include Winnow's full automation suite (`scripts/run_smoke.py`, `scripts/a11y_scan.py`, Playwright E2E, `run_readiness.py`).
- For launch confidence, run the checks below now, then add/port the missing suites as Phase 2.

---

## One-time setup (your machine)

From repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

---

## Environment variables (required)

Set these in `.env` or terminal:

```powershell
$env:CRM_BASE_URL = "https://<crm-host>"
$env:CRM_API_SERVICE_KEY = "<lottoexpress-service-key>"
```

Optional for anti-tamper quote checks:

```powershell
$env:READY_CHECK_TOKEN = "<customer-bearer-token>"
$env:READY_CHECK_QUOTE_PAYLOAD_JSON = '{"items":[...]}'
$env:READY_CHECK_TAMPER_PAYLOAD_JSON = '{"items":[...tampered...]}'
```

---

## Test server run order (recommended)

### 1) CRM/MM readiness check

```powershell
python tools\check_mm_readiness.py
```

Expected:
- Hard checks pass: env, API health, event allowlist, placements endpoint reachability.
- Advisory checks may fail if seed data/tokenized payloads are not configured.

### 2) Template render smoke

```powershell
python tools\smoke_render_account.py
```

Expected:
- Prints `Rendered OK`.

### 3) Website health endpoint

```powershell
curl https://<lottoexpress-test-domain>/health
```

Expected:
- HTTP 200 and JSON with `ok: true`.

---

## Production (safe mode)

All checks above are read-only/safe except optional quote anti-tamper checks, which require a real token.

Recommended production-safe baseline:

```powershell
python tools\check_mm_readiness.py
curl https://<lottoexpress-prod-domain>/health
```

---

## Interpreting failures quickly

### `check_mm_readiness.py` failures
- `env.*`: missing required env variables.
- `api.health`: CRM connectivity/auth problem.
- `event.allowlist.*`: marketing events contract or service key mismatch.
- `placement.*`: marketing banners endpoint/shape issue.
- `tenant.bundle_seed_data`: expected if no known bundle slug was supplied.
- `quote.anti_tamper`: expected skip until token + payload env vars are set.

### `smoke_render_account.py` failures
- Usually template/context regressions; inspect stack trace for missing variables or bad imports.

---

## Launch gate (minimum)

Before launch, require all:
- `check_mm_readiness.py` hard checks pass.
- `/health` returns 200 from deployed site.
- Manual quote/checkout sanity passes in test:
  - Product shown with expected CRM price
  - Cart quote totals match CRM quote payload
  - Checkout submit succeeds with `quote_id` path
- Pricing fallback path validated:
  - Simulate missing quote totals
  - Confirm fallback prices shown and admin warning keys increment:
    - `pricing_warning:last_event_at`
    - `pricing_warning:last_reason`
    - `pricing_warning:count`

---

## Phase 2 (recommended immediately after launch freeze)

Port Winnow's automated suites into Lotto Express:
- `run_smoke.py`
- `a11y_scan.py`
- Playwright E2E tests
- `run_readiness.py` orchestrator

This will give parity with Winnow's release confidence and nightly automation.
