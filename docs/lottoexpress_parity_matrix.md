# Winnow vs Lotto Express Parity Matrix

| Capability | Winnow Baseline | Lotto Express Target | Owner |
|---|---|---|---|
| Promotions menu | MM offers visible in nav | Match behavior using `catalog` placement | Website |
| `/lotteries/promotions` | Active offers listed with CTA | Match behavior using `catalog` placement | Website |
| Homepage featured promotions | MM `home` placement cards | Match behavior with Lotto Express branding | Website |
| Bundle landing page | `/offer/<bundle_slug>` content + start | Match behavior (CRM-authoritative content) | Website |
| Checkout upsell | Eligible offers + requote | Match behavior + LE branded upsell box | Website |
| Promo code apply | Requote via CRM, error/success states | Match behavior + CRM-driven messages | Website |
| Tracking events | Canonical taxonomy emitted | Match taxonomy + idempotent event IDs | Website |
| Attribution flow | `src/cmp/tid/intent` persisted | Match flow + lifecycle `src` omission rule | Website |
| Payment return diagnostics | `campaign_touch` diagnostics | Match behavior and dashboard visibility | Website |
| Event allowlist | Canonical types accepted | Canonical types accepted for LE tenant | CRM/MM |
| Quote anti-tamper | Enforced in CRM | Enforced in CRM | CRM/MM |
| Funnel/campaign reporting | Non-zero flow and conversion | Equivalent LE visibility in exports/reports | QA/Analytics |

## Notes

- This matrix is a rollout gate. Any row marked not-ready blocks production launch.
- Website paths are in external repo (`lottoexpress-website/...`) and are listed for coordination.

