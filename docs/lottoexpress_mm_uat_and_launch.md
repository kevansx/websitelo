# Lotto Express MM UAT + Launch Checklist

Use this checklist for parity/UAT sign-off and staged rollout.

## A. Offer Surface Validation

- [ ] Offer created in Marketing Module appears in promotions menu (`catalog` placement).
- [ ] Offer appears on `/lotteries/promotions` list.
- [ ] Featured promotions on homepage render from `home` placement (or configured fallback).
- [ ] Offer CTA opens expected target (`/offer/<bundle_slug>` when bundle-based).

## B. Checkout Upsell Validation

- [ ] Eligible upsells render in branded Lotto Express card style.
- [ ] Select/deselect triggers requote and updates CRM-authoritative totals.
- [ ] Upsell unavailable/empty state renders cleanly.
- [ ] Mobile layout remains readable and clickable.

## C. Promo/Quote/Submit Validation

- [ ] Promo code apply updates quote.
- [ ] Invalid/expired promo errors are user-friendly.
- [ ] Checkout submit succeeds with valid quote.

## D. Tracking + Attribution Validation

- [ ] Canonical events visible in CRM/Marketing exports:
  - `click` (`metadata.cta=register`)
  - `signup_started`, `signup_completed`
  - `checkout_started`
  - `submit_attempt`
  - `purchase_failed`
  - `purchase_completed`
- [ ] `checkout_started` only fires when entering checkout, not cart page view.
- [ ] Idempotent event IDs dedupe retries correctly.
- [ ] Payment return diagnostics (`campaign_touch`, `phase=payment_return`) are present.
- [ ] Lifecycle attribution rule:
  - lifecycle links without `src` do not send `marketing_source_code`.

## E. Anti-Tamper Acceptance

- [ ] Valid upsell quote payload succeeds.
- [ ] Tampered payload with changed line count (`len(lines) != offered_quantity`) is rejected or discount removed.

## F. Reporting Validation

- [ ] Events export has expected counts by event type.
- [ ] Funnel progression is non-zero and coherent.
- [ ] Campaign attribution fields (`source/campaign/click`) populate as expected.

## G. Staged Rollout

### Stage 1 — Internal
- [ ] Enable for internal traffic only.
- [ ] Monitor errors, quote latency, and event ingestion.

### Stage 2 — Limited Campaign
- [ ] Enable for limited production campaign.
- [ ] Compare KPI movement vs baseline.

### Stage 3 — Full Rollout
- [ ] Full rollout after KPI and stability checks pass.

## H. Week-1 KPI Baseline Tracking

Capture **Winnow baseline** and **Lotto week-1 target/actual** for:

- [ ] quote -> submit conversion
- [ ] promo redemption rate
- [ ] upsell attach rate
- [ ] offer CTR by placement (menu/promotions/home featured)

