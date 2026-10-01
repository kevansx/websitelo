# Lotto Express CRM/MM Readiness Gate

This gate must pass before website-facing frontend rollout.

## Hard Gate Checks

1. Tenant/API health reachable (`/api/v1/health`)
2. Canonical marketing events accepted for LE tenant:
   - `signup_started`
   - `checkout_started`
   - `submit_attempt`
   - `purchase_failed`
   - `purchase_completed`
3. Banner placements reachable and valid:
   - `home`
   - `catalog`
   - `checkout`
4. Required MM seed/config data available:
   - active bundle(s)
   - active upsell rule tier(s)
   - active promo code(s)

## Optional Strict Checks

- Quote anti-tamper validation (requires a customer token and example payloads):
  - valid quote payload passes
  - tampered payload is rejected (400/409/422)

## Runbook

From `lottoexpress-website/`:

```bash
python tools/check_mm_readiness.py
```

Strict mode:

```bash
python tools/check_mm_readiness.py --strict
```

Required env:

- `CRM_BASE_URL`
- `CRM_API_SERVICE_KEY`

Optional env for anti-tamper checks:

- `READY_CHECK_TOKEN`
- `READY_CHECK_QUOTE_PAYLOAD_JSON`
- `READY_CHECK_TAMPER_PAYLOAD_JSON`

## Gate Outcome

- **Pass**: proceed with frontend deployment tasks.
- **Fail**: pause frontend work and resolve CRM/MM readiness items.

