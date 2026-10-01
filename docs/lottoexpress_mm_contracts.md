# Lotto Express Marketing Module Contracts

This document locks the implementation contract between the Lotto Express website and CRM/Marketing Module.

## Ownership Boundaries

- **Website team (external repo: `lottoexpress-website/...`)**
  - UI/templating: offers menu, promotions pages, homepage featured promotions, checkout upsell, event emission.
- **CRM/Marketing Module team**
  - API behavior, tenant readiness, event allowlists, anti-tamper quote/submit enforcement, offer data configuration.
- **QA/Analytics**
  - Cross-system UAT, attribution validation, KPI reporting sign-off.

## Locked Endpoints

- `POST /api/v1/marketing/events`
- `GET /api/v1/marketing/banners?placement=<placement>`
- `GET /api/v1/bundles/<bundle_slug>`
- `POST /api/v1/checkout/quote`
- `POST /api/v1/checkout/submit`

## Placement Mapping

- `catalog` -> Promotions nav menu + `/lotteries/promotions`
- `home` -> Homepage featured promotions
- `checkout` -> Checkout/cart upsell surface

## Canonical Tracking Taxonomy

- `click` (registration click requires `metadata.cta=register`)
- `signup_started`
- `signup_completed`
- `checkout_started`
- `submit_attempt`
- `purchase_failed`
- `purchase_completed`
- Optional: `first_purchase_completed`

## Attribution Contract

- Incoming URL canonical params: `src`, `cmp`, `tid`, `intent`
- Event mapping:
  - `src` -> `source_code` (omit when `intent=lifecycle`)
  - `cmp` -> `campaign_code`
  - `tid` -> `click_id`
- Checkout mapping:
  - pass canonical aliases/marketing fields to quote/submit calls
- **Lifecycle rule**:
  - when a lifecycle link does not include `src`, website must not send `marketing_source_code`.

## Upsell/Promo Anti-Tamper Contract

- CRM enforces:
  - selected upsell SKU matches offered SKU
  - line count equals offered quantity (`len(lines) == offered_quantity`)
- Website renders CRM totals only; no local final-total calculations.

## Required Tenant Data

- At least one active bundle
- At least one active upsell rule tier
- At least one active promo code

