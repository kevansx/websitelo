# Pre-launch Test Plan — LottoExpress Website

Purpose: identify every critical customer path, verify each one works, and define
what must pass before the site goes online.

Approach: two layers.

1. **Automated tests** (`tests/`, run with `python -m pytest tests/`): fast Flask
   test-client tests with the CRM stubbed at the `CRMClient` boundary. These lock
   in routing, template rendering, session behavior, auth gating, and error
   handling, and act as the regression suite for every future change.
2. **Manual staging checklist**: things that cannot be validated with a stubbed
   CRM — real payments, email delivery, geo-blocking, cross-browser rendering —
   verified once on the staging/production environment before DNS cutover.

Priorities: **P0** = blocks launch. **P1** = must work at launch but has a
workaround (support/manual). **P2** = fix soon after launch.

---

## 1. Critical paths

### P0 — Revenue path (browse → pick → cart → checkout → order)

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Homepage renders: hero, jackpot carousel, countdowns | `/` | Smoke render + countdown markup | Visual check, countdown ticks |
| Catalog / play page renders with picker and products | `/catalog`, `/play/<game>`, `/lotteries/<slug>` | Smoke render, products present | Pick numbers, quickpick, add line |
| Banner countdown shows time remaining (bug fixed 2026-08-19) | `/play/<game>` | Regression test: `.wl-countdown` span with `data-remaining` served; React no longer clobbers it | Verify ticking on 2+ game pages |
| Add to cart (logged in / logged out capture) | `POST /cart/add` | Both paths tested | — |
| Cart page: view, edit line, remove, promo, offers | `/cart`, `POST /cart/*` | View/clear/remove tested | Promo code + offer toggle with real CRM quote |
| Checkout with sufficient balance | `POST /checkout` | — (staging) | Full purchase, order confirmed |
| Checkout with insufficient balance → top-up → resume | `POST /checkout`, `/checkout/after-topup` | — (staging) | Full path incl. payment |
| Order confirmation + tickets + scan polling | `/orders/<id>` | Render tested (stubbed) | Real ticket + scan appears |

### P0 — Auth

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Register (validation, currency/title options) | `GET/POST /register` | Success + CRM-failure paths | Email verification mail arrives |
| Login / logout / bad credentials | `GET/POST /login`, `/logout` | All three | — |
| Session token gates protected pages | `/account`, `/orders`, `/wallet/*`, `/legacy-orders` | Redirect-to-login tested | — |
| Forgot / reset password | `/forgot-password`, `/reset-password` | Page render + post | Real email link round-trip |
| Email verification | `/verify-email`, resend/dismiss | — | Real token round-trip |

### P0 — Wallet & payments

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Balance display in header and account | `/account` | Rendered from stub | Matches CRM |
| Add funds page (amounts, saved cards) | `/wallet/add-funds` | Render tested | — |
| Top-up: hosted payment page (HPP) redirect | `POST /wallet/add-funds` | — | Real payment, success + declined card |
| Top-up: direct card + 3DS challenge | `.../emerchant/3ds/...` | — | Real 3DS challenge |
| Payment return pages: success / failed / cancelled | `/wallet/topup/{success,failed,cancelled}`, `/wallet/topup/return/<status>` | Render tested | Return from real processor lands correctly (allowlisted URLs) |
| Saved card delete | `POST /wallet/cards/<id>/delete` | — | Delete + verify gone |
| Withdrawal request | account withdrawal section | — | Submit + support receives it |

### P0 — Account & orders

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Account page: details, wallet, orders tabs | `/account` | Render + order history detail rows | Update details round-trip |
| Order history incl. expanded ticket rows | `/account#orders` | Covered (`test_account_order_history.py`) | — |
| Orders list + detail + scan refresh | `/orders`, `/orders/<id>` | Render tested | Scan URL opens |
| Legacy orders (tab visibility, list, detail, 404) | `/legacy-orders*` | Covered (`test_legacy_orders.py`) | Spot-check real imported data. **Before launch: set `LEGACY_ORDERS_SHOW_EMPTY=0`** |

### P1 — Results, jackpots, countdowns

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Results index + per-game results | `/results`, `/results/<game>`, `/lottery-results/<slug>` | Smoke render | Numbers match official draws |
| Number checker | `POST /api/results/<game>/check-numbers` | — | Known winning/losing lines |
| Jackpot amounts + cutoff countdowns everywhere | `/`, `/play/*`, results | Countdown markup tests | Values sane vs CRM; ticks in browser |

### P1 — Marketing & promotions

| Step | Route(s) | Automated | Manual |
|---|---|---|---|
| Promotions listing + promo detail + offer start | `/lotteries/promotions`, `/promotions/<slug>`, `/offer/<slug>` | Smoke render | Bundle purchase end-to-end |
| Banners (home/catalog placements) | via CRM | Stubbed render | Real banner images + links |
| Attribution tracking | `POST /api/track/*` | Endpoint accepts posts | Events visible in Marketing Module |

### P1 — Compliance & safety

| Item | Automated | Manual |
|---|---|---|
| Country blocking (geo) | — | VPN check from a blocked country |
| Legal pages: terms, privacy (+AU/world), responsible gaming, ID verification info | All render 200 | Content/legal review |
| Cookie banner, 18+ marks, GambleAware/GamCare links | In base template render | Visual check |
| Refund links removed from order lists (2026-08-18 change) | Covered | — |

### P2 — Legacy compatibility & infrastructure

| Item | Automated | Manual |
|---|---|---|
| Legacy `.php` URL redirects | Representative sample tested | — |
| `sitemap.xml`, `/health`, 404 page, 500 page | Tested | Monitoring hooked to `/health` |
| Admin login gate | Gate tested | Real password/token works |
| Static assets served at `/resources/*` (incl. new 6aus49 logos) | Logo files exist | CDN/caching headers |

### Error handling (all priorities)

| Scenario | Automated | Manual |
|---|---|---|
| CRM down → friendly flash message, page still renders | Tested per page group | Kill CRM on staging, click around |
| CRM 404 on detail pages → not-found page | Tested | — |
| Unknown URL → branded 404 | Tested | — |
| Unhandled exception → branded 500 (no stack trace leaked) | Tested | — |

---

## 2. Manual staging checklist (run once before DNS cutover)

Environment first: production `.env` reviewed — `CRM_BASE_URL`, `CRM_API_SERVICE_KEY`,
`WEBSITE_SECRET_KEY` (not the dev default), `WEBSITE_CANONICAL_DOMAIN`,
`CRM_SYNC_ENABLE=1`, `LEGACY_ORDERS_SHOW_EMPTY=0`, reCAPTCHA keys, GTM/GA IDs.

1. Register a fresh account (real email) → verification email arrives → verify.
2. Log out, log in, wrong-password rejection, forgot-password email round-trip.

> Testing note: CRM emails link to the brand primary domain (`lottoexpress.com`),
> which still serves the old site until DNS cutover. When testing on `www1`,
> change the host in emailed links (verify-email, reset-password) to
> `www1.lottoexpress.com` before opening them. After cutover the links are correct
> as-is — re-verify both email round-trips then.
3. Add funds via hosted payment page — approve, decline, and cancel; balance and
   transaction list update correctly; return URLs land on branded pages.
4. Direct-card top-up with 3DS challenge (if enabled for the brand).
5. Buy a single-play ticket with sufficient balance → order appears in
   `/account#orders` and `/orders/<id>`; ticket scan appears after polling.
6. Buy with insufficient balance → prompted to top up → purchase resumes.
7. Buy a promo bundle from `/promotions`.
8. Check draw results page against official results for 2 games; number checker.
9. Countdown timers tick on homepage, play pages, and results pages (Chrome,
   Firefox, Safari, and one mobile device).
10. Legacy order customer sees Legacy Orders section; fresh customer does not.
11. Withdrawal request from account; support inbox receives it.
12. Contact form submission.
13. VPN from a blocked country → blocked; from an allowed country → works.
14. Old bookmarked `.php` URLs redirect (spot-check 5).
15. Kill CRM briefly → site shows friendly errors, no stack traces; recovers.
16. `/health` returns ok; error pages branded; no dev build banner in footer.

Launch gate: all P0 rows green (automated suite passing + manual checklist items
1–7 done), P1 verified or consciously waived, environment checklist signed off.

### Bugs found during testing

| Date | Bug | Status |
|---|---|---|
| 2026-08-19 | Play-page banner countdown clobbered by legacy React widget ("To Be Announced") | Fixed in `react.js` (guards) + regression test |
| 2026-08-19 | `POST /cart/clear` crashed with 500 (`NameError`); "Reuse last purchase" never populated | Fixed in `app.py` + tests |
| 2026-08-20 | **CRM bug (open, report to CRM team):** `POST /api/v1/auth/register` returns HTTP 500 "Internal Server Error" when the phone number already belongs to another account, instead of a clean validation error like duplicate email gets ("Email already registered"). Reproduced on production: register any account with a phone, then register a different email with the same phone. Not documented/changed in API doc v56 (identical to v53) — still needs a CRM-side fix. | Website now shows a friendly message with a phone hint instead of the raw 500; CRM fix pending |

| 2026-08-27 | Checkout offer cards could advertise a discount percentage the website invented: the badge fell back to a hardcoded tier ladder (10/15/20% by cart value) or a flat 10% when the CRM returned a rule without a percent. The thresholds belong to the CRM's offer rules. | Fixed in `cart.html`: the badge shows only the CRM's `discount_percent` for the matched rule. Each card's match is now logged (`cart upsell card <sku> x<lines>: rule_id=... crm_discount_percent=...`) so a missing CRM rule is distinguishable from a website matching failure. **Note:** the discount attaches to the offered item, so a manually built cart correctly shows no discount |
| 2026-08-27 | Play page under-quoted the price: the picker took the amount from `price_in_base_cents` but labelled it with the **customer's** currency symbol, so a base-currency price was shown as if it were EUR (e.g. SuperEnalotto 3 lines shown as EUR 7.50, charged as EUR 9.00 by the CRM quote in the cart). | Fixed: play route now passes `prices_by_currency` and the picker resolves amount + currency together, falling back to the base amount **with the base currency symbol** so an amount is never mislabelled. Test added. Use `tools/debug_product_prices.py <game_code>` on the server to see the CRM's per-currency prices |
| 2026-08-27 | Cart showed an affordable total that checkout then rejected with 402 ("Insufficient wallet balance" with EUR 24.00 in the wallet and "Funds Required: EUR 23.10" on the button). The cart subtracted a **website-derived** upsell/offer discount (hardcoded 10/15/20% tiers, per-item estimates) from the CRM quote total — including quote totals that already carried the CRM's own discount — so the confirm figure could sit below what the CRM debits. | Fixed in `app.py` + `cart.html`: one authoritative payable figure (`_quote_payable_cents`) drives both the affordability check and the confirm button; a saving the quote doesn't evidence is no longer displayed. 402s now show the CRM's own required/available amounts and log them. Regression test added |
| 2026-08-21 | **CRM bug/config (open, report to CRM team):** wallet top-up init for the brand's default processor returns `mode: "direct_card"` with `crm_card_form_url` = `/wallets/topup/<id>/card`, which is the CRM back-office page gated behind **staff** login. Customers redirected there see the CRM admin sign-in and cannot pay. The URL must be public/tokenized, or the brand should be configured for an HPP website flow. Workaround for QA: enable the Testing processor for the brand in CRM Admin and set `WALLET_TOPUP_PROCESSOR=testing` on the website. | Open — CRM-side fix/config needed |

### API alignment audit (2026-08-20, against API doc v56)

Fixed:

- Checkout fallback (`POST /api/v1/checkout`) now sends `use_wins: true` so
  customers can spend winnings; previously winnings balances triggered 402
  insufficient-balance despite a sufficient displayed balance.
  **Both of these were wrong and were reversed on 2026-09-14 — see the wallet
  funding audit below.**
- Cart affordability and add-funds prechecks now prefer
  `wallet.available_balance_cents` (excludes reserved funds) over
  `balance_cents`.
- Cart add enforces the documented frontend line rules (superseded 2026-08-27 by
  product-driven limits — see the currency + line-rule audit below).
- Register now forwards marketing attribution (`acquisition_click_id`,
  `acquisition_source_code`, `acquisition_campaign_code`).
- CRM client can send `X-CRM-Brand-Slug` (set `CRM_BRAND_SLUG` env; only needed
  with a shared/global service key).

### API v58 — Website Processor Rules routing (2026-08-25)

API v58 adds CRM-owned processor routing for wallet top-ups. When Processor
Rules are enabled for the brand, the CRM picks the processor (the website's
`processor` field is ignored, so `WALLET_TOPUP_PROCESSOR` becomes a no-op) and
owns the fallback sequence across processors via a durable routing session.

Implemented on the website:

- Top-up init captures `routing.session_id` / `routing.processor`; the
  routing-selected processor is authoritative for the direct-card allowlist
  (`WALLET_DIRECT_CARD_PROCESSORS` — see the Worldpay entry below, which is what
  happens when a CRM-enabled processor is missing from it).
- If init fails and the error payload carries `routing.can_advance: true`,
  the site re-posts the CRM-supplied `routing_session_id` to init (up to 4
  attempts) instead of surfacing the failure. It never retries the failed
  processor directly.
- The post-payment polling page (`/wallet/topup/return/...`) understands the
  new nested `intent.status` shape and, on a failed intent whose routing state
  allows advancing, posts `routing.resume_payload` back to init and redirects
  the customer to the next processor (capped at 5 advances per journey).
- `routing.exhausted: true` renders a terminal "all providers tried" message.
- Init responses are followed processor-neutrally (`redirect_url`,
  `next_action_url`, hosted `redirect` form, `crm_card_form_url`, or
  options→HPP start) rather than assuming Expefast shapes.

### API v60 — a declined direct card advances without a round trip (2026-09-02)

Until now the site could only advance a routing session in two places: when
`init` itself failed, and when the customer came back through a return URL onto
a failed intent. A direct-card decline sat in between. The charge raised, the
site showed the failure page, and the remaining processors in the rule were
never tried — the customer saw "declined" while a provider that would have
taken the payment was still sitting in the sequence untouched.

API 60 closes that: every JSON charge response for a routed intent carries the
current `routing` state, and a decline or technical failure updates the attempt
before responding. So the next processor can be started from the decline itself.

Implemented on the website:

- The `wallet_topup_charge` error handler reads `routing` off the error payload
  and, when `can_advance` is true, posts `resume_payload.routing_session_id`
  back to init and sends the customer into the next processor's flow.
- The same applies to a decline that arrives as a 200 body rather than a 402.
- All three advance sites (init failure, charge failure, return-flow failure)
  now go through one helper, `_advance_topup_routing`, which owns the
  five-advance guard. Three copies of this logic was one too many already.
- A next processor that takes cards directly gets its own trip through the
  payment step. The card was given to one processor; replaying it against
  another without asking is not the site's call to make, and it is also how you
  end up charging two providers for one top-up.
- The failed intent is never retried and the failed processor is never called
  again directly — advancing creates the next attempt, which is the CRM's model.
- Compatibility for staggered CRM deploys: when the charge error carries no
  `routing`, the site reads it off `GET /wallet/topup/<id>` before giving up.

Only when advancing is disallowed, exhausted, capped, or the next processor
fails to start does the customer see the terminal failure page.

**Follow-up: the site assumed every processor has a hosted page (2026-09-02).**

Confirmed with the CRM team that Worldpay and Z1 are direct-card only — there is
no `/hpp/start` for either. The site's answer to "no direct card here" was
always "then use the hosted page", which for those two calls a route that does
not exist. The customer got a failure page for a processor that was ready to
take a card. Harmless while Worldpay was allowlisted and charged directly;
live the moment a routing advance lands on such a processor, and the Colombia
cascade (Worldpay → TRAXX → CCM → Emerchant → EltroVox) can do exactly that.

The flow is now read off what the response advertises:

- `_topup_hosted_ready` — `options.hpp` or `options.hosted_checkout`. CCM and
  MEU use the second name, which is why both are checked.
- `_topup_direct_card_advertised` — the CRM's own `options.direct_card`.
- `_topup_direct_card_ready` — the above, plus the allowlist guard, which is
  now applied **only where a hosted page exists to fall back to**. Vetoing a
  processor that has no hosted flow guarantees a dead end; trusting the CRM at
  worst ends at the same failure and at best takes the payment.
- Nothing starts a hosted page unless one was advertised. Where neither flow is
  on offer, the response's processor-neutral instructions are followed, and
  only then does it fail.
- The "pay on our provider's secure page instead" button is hidden when the
  processor has no hosted page, rather than offering a button that can only
  fail.

The per-processor rule this encodes, from the CRM team (not in API 60, which
documents neither Worldpay nor CCM):

| Processor | Direct card | HPP |
| --- | --- | --- |
| Worldpay | yes | no |
| Z1 | yes | no |
| TRAXX | yes | yes |
| Emerchant | if enabled | yes |
| EltroVox | if enabled | yes |
| CCM | no | yes (`hosted_checkout`) |

Answered by the CRM team on 2026-09-02 (see the TRAXX entry below): TRAXX does
have a hosted page, API 60's "EltroVox / Emerchant / Testing only" line for
`/hpp/start` is stale, and TRAXX advertises it as `options.hosted_checkout`
rather than `options.hpp`. The table above stands.

Retiring `WALLET_DIRECT_CARD_PROCESSORS` is still open, pending the CRM deploy
that makes `available` authoritative. It no longer applies to TRAXX either way.

### Every advance onto TRAXX strands a pending intent (2026-09-02)

A Colombian customer made six attempts at €75 in eight minutes. Each one reads
the same in the CRM: Worldpay `failed` / `REFUSED`, then a TRAXX intent
`pending` with no card and no result, then — 13 to 56 seconds later — another
Worldpay attempt with a different card. Six Worldpay refusals across five cards,
six stranded TRAXX intents, nothing paid.

The advance itself is behaving as API 60 describes: the Worldpay decline carries
`can_advance`, the site posts the `resume_payload`, and the CRM creates the next
attempt on TRAXX. What follows is the problem. The customer never touches TRAXX
— no card, no result — and the next thing they do starts a *new* routing
session, which begins at the front of the Colombia rule (Worldpay) again. Two
things are true at once and they compound:

- **The site cannot use the TRAXX intent.** `direct_card` reads as unavailable
  (the field-shape item above), and the two capability sources disagree on
  whether there is a hosted page to fall back to: the table the CRM team gave us
  says TRAXX has one, but API 60's `POST /wallet/topup/<id>/hpp/start` is
  documented for "EltroVox HPP, Emerchant WPF, or Testing internal HPP" plus MEU
  only, and TRAXX has no `options` response shape documented at all. TRAXX *is*
  in the `charge` endpoint's list. If the API doc is right, TRAXX is direct-card
  only like Worldpay and Z1, and an advance onto it hits the same dead end the
  entry above fixed for those two — with the failure page showing Worldpay's
  refusal, which is why the customer restarts from scratch.
- **A dead-ended advance cannot be cleaned up.** There is no abandon or cancel
  endpoint for an intent, and per API 60 the CRM "never reuses an unknown or
  pending attempt", so each one is stranded for good. That is the entire content
  of the pending TRAXX rows: they are litter from a failed advance, not payments
  anyone is waiting on.

**Answered the same evening.** The CRM team confirmed the stranded intents as
2709, 2711, 2713, 2715 and 2718, and gave the shape. TRAXX is unlike every other
processor at both ends of its `options`:

```json
{
  "direct_card": { "allowed": true, "status": "available" },
  "hosted_checkout": { "start_url": ".../wallet/topup/<id>/hpp/start",
                       "return_urls": { "success": "…", "fail": "…", "cancel": "…" } }
}
```

No `available` bool, no `charge_url`, no `cards_url`, and `hosted_checkout`
rather than `hpp`. Charge when `allowed === true` **and** `status ===
"available"`; if `direct_card` is absent, do not charge. The site was looking
for `available` and a `charge_url`, so it read a processor that was ready to
take a card as offering nothing.

Three changes, and the third is the one that would otherwise have wasted the
deploy:

- `_topup_direct_card_offer` replaces the boolean and reports *which* shape
  answered. Both are honoured. A missing URL is not a refusal — charge and
  hosted start are addressed by intent id, so the URL was never load-bearing —
  but a missing or disagreeing `direct_card` block still is.
- The hosted start no longer swallows a `CRMError`. That one silent `return
  None` is why "the site never called `/hpp/start`" and "the CRM refused the
  call" looked identical from both sides of the API while we were diagnosing
  this.
- **The allowlist no longer applies to the `allowed`/`status` shape.** It was
  written to second-guess `available`, which the CRM had returned true for
  processors that then refused the charge; no processor answered
  `allowed`/`status` when it was written. Adding `traxx` to the default would
  have fixed nothing on a server carrying its own `WALLET_DIRECT_CARD_PROCESSORS`
  value — which production does, since Worldpay was added to it by hand. It is
  in the default too, for the day TRAXX moves to the `available` shape.

So an advance onto TRAXX now lands on the site's own card step and charges
TRAXX, and a decline there carries routing metadata onward to CCM rather than
stopping. Hosted checkout remains the fallback when the CRM says direct card is
not allowed.

**Second pass, 2026-09-03.** With the above live, a $15 attempt from the same
Colombian customer ran Worldpay `failed`/`REFUSED` → TRAXX `failed` → Emerchant
`pending`, in 65 seconds. The dead end is gone: TRAXX was attempted rather than
stranded, and the cascade carried on past it, which it had never done. What
stopped is the customer, at the third card form, and the cause of the third
card form was ours:

- TRAXX failed with no card recorded against it, which is the CRM refusing the
  charge rather than a bank declining it — the shape of a brand with TRAXX
  "Direct card" switched off. The site was treating that refusal as a routing
  event and advancing, when it is a configuration answer: nothing reached a
  bank, and TRAXX's own `hosted_checkout` would have taken the payment. The
  config refusal is now checked *before* the advance and uses the processor's
  own hosted page where it has one, so a switched-off toggle costs a redirect
  instead of a processor from the rule. Where the processor has no hosted page,
  it still advances, because there the alternative really is a failure page.
- The second card form arrived with no explanation. Card details cannot be
  carried across processors — the CRM is explicit about that, and it is right —
  so an advance onto a card-taking processor has to ask again. Unexplained, it
  reads as the site having lost the payment. Every `pending` row at the tail of
  a cascade is a customer who stopped at one of these. It now says why.

Still with the CRM team, in the order that matters:

1. **Worldpay is first in the Colombia rule and refused five cards in a row.**
   The site now finishes what the advance starts, but that is where the money is
   going. Confirmed as real declines, so the question is whether Worldpay should
   lead that rule at all.
2. An endpoint to abandon an intent the site cannot use. Confirmed as not built:
   there is no cancel or abandon on a pending routed intent, and the CRM never
   reuses one, so 2709/2711/2713/2715/2718 are stranded for good. Any advance
   that dead-ends will keep leaving rows like them behind.
3. API 60's `/hpp/start` section still lists EltroVox, Emerchant and Testing
   only, and documents no TRAXX response shape. Worth correcting so the next
   person reads it right.

### Country blocking did not work (2026-09-02)

Asked for the list of blocked countries so Malta could be added, and the answer
was that there wasn't one: `block_website` is false on all 258 rows of the CRM's
country table. The United States is the only country marked inactive, which
stops a US registration but does not stop US browsing — the request-level check
reads the blocked flag only.

Three separate faults, each of which on its own would have made a Malta block
look applied while doing nothing.

**The env list was dead config.** `WEBSITE_BLOCKED_COUNTRIES_ISO2` was only read
when the country was *missing* from the countries cache. The CRM's table carries
every country, so the cache always had an answer and the branch never ran.
Setting it would have blocked nobody. It is now checked first, on its own
authority, ahead of the CRM's flag.

**The block was steerable by the visitor.** Geo came from the first match in a
fixed list of CDN headers starting with `CF-IPCountry`. Those are ordinary
request headers that anyone can send. Confirmed against production: `/register`
preselects the geo country, a plain request preselected `CA`, and the same
request with `CF-IPCountry: MT` preselected Malta.

By elimination the edge (Azure Front Door) injects `X-Geo-Country`, and its
value wins over a client-sent duplicate — established by sending
`CloudFront-Viewer-Country: X`, an invalid value that the ISO2 regex skips: the
real country still came through, which it could not have done had the injected
header been that one. So a named trusted header is now checked first and settles
it. `GEO_COUNTRY_HEADER` defaults to `X-Geo-Country`; the other CDN headers are
still read, but only when the trusted one is absent.

**A multi-country list would have half-worked.** `_parse_iso2_list` split on
`[,\\s]+`, which in a raw string is a class of comma, backslash and the letter
*s* — not whitespace. `MT GB` arrived as one token matching nothing. One country
would have worked and two would not, which is the worst way for it to fail.

Blocking now covers both directions: browsing, on the country the edge reports,
and registration, on the country the customer selects. Both layers stay live —
CRM `block_website` still blocks, and covers every brand at once; the env list is
the fast lever that needs no CRM edit and no deploy.

Manual checks:

- [ ] With `WEBSITE_BLOCKED_COUNTRIES_ISO2=MT`, a VPN in Malta gets the 403 page
      and an allowed country does not.
- [ ] Sending `CF-IPCountry: IE` from that Malta VPN still gets the 403.
- [ ] Registration with Malta selected is refused from an allowed country.
- [ ] `/health` and `/resources/...` still answer from a blocked country, or the
      403 page loads unstyled and the load balancer marks the site down.

### The CRM's block list never reached the site (2026-09-02, second pass)

The CRM then blocked Malta and nothing changed, which is a fourth fault behind
the three above and the one that mattered most: the site was never reading the
list.

Fetching the countries table was a step inside the general background sync,
which only runs when `CRM_SYNC_ENABLE` is set, and it is off unless someone sets
it. With it off the countries table was never fetched, `block_website` was
unknown for every country, and the request-level check answered "not blocked" to
everyone. Blocking a country is a compliance control and it was riding on a
performance switch — so the CRM could block a country, the site would agree in
principle, and the visitor would browse.

The countries table now refreshes on the site's own initiative, independent of
`CRM_SYNC_ENABLE`, every `COUNTRY_BLOCKS_REFRESH_SECONDS` (default 300). An
empty table is fetched inside the request, because answering from a list that
was never loaded is the one case worth making a visitor wait for; after that
refreshes happen behind the request. The attempt is stamped before the call, so
a CRM outage backs off to the same interval instead of retrying on every page.

**The first attempt at this shipped broken**, and it is worth recording why
because it is the same fault twice. Where there is already a list to answer
from, the refresh runs on a thread so the visitor is not held up — and it took
its CRM client from `get_crm()`, which keeps the client on Flask's `g`. There is
no `g` off a request, so the thread raised `Working outside of application
context` on its first line, the warning went to the log, and every page carried
on answering 200. A deployed server has a populated table, so it always took
that path: the fix looked fine in tests, which start from an empty cache and
therefore fetch inside the request, and did nothing at all in production. The
thread now builds its own client, the way `store_games_cached` already did.

The same fault was sitting in `_sync_once`, the general background loop behind
`CRM_SYNC_ENABLE`. It runs on a thread too and reaches the CRM through
`get_crm()` throughout, so that loop has never worked — turning the switch on,
as suggested, would have changed nothing. It now runs inside an application
context, and `get_token()` returns `None` off a request instead of raising on
the session lookup.

Two things worth knowing before the next deploy:

- **It applies the whole list, and the list is large.** 51 of the CRM's 258
  countries carry `block_website`, matching exactly the set marked inactive, and
  they include the United States, Canada, Australia, the Netherlands, Denmark,
  Greece, Poland, Romania and Singapore. A blocked country gets a 403 on every
  page. If any of those are wrong, correct them in CRM Admin rather than here.
- **`/admin` is exempt from the block.** It is password-protected, and it holds
  the controls for the list, so gating it would mean a wrong entry could only be
  undone on the server — by someone who is not in a blocked country.

Manual checks:

- [ ] With nothing in `WEBSITE_BLOCKED_COUNTRIES_ISO2`, a VPN in a country the
      CRM has flagged gets the 403 within five minutes of the CRM change.
- [ ] `/admin/crm-cache` still answers from that same VPN.
- [ ] Unsetting the flag in CRM Admin restores access within five minutes.

### Worldpay top-ups stuck pending: the site was vetoing the CRM's routing (2026-08-29)

**Symptom.** Charges for customers the CRM routed to Worldpay sat in a pending
state and never collected.

**Cause.** Website-side, not CRM or Worldpay. The CRM routes by country and
reports per-intent direct-card capability, and for Worldpay it returned
`options.direct_card.available: true` with a `charge_url`. The site then
overrode that against a hardcoded set of processors:

```python
if used_processor and used_processor not in {"eltrovox", "emerchant", "testing"}:
    direct_card_available = False
```

Worldpay was not in it, so `payment_flow` flipped to `hpp` and the site called
`wallet_topup_hpp_start` on a processor with no hosted page configured. The CRM
refused, the site flashed the error and returned to the add-funds form, and the
intent it had already created was left pending with nothing collected.

**Fix.** The list is now `WALLET_DIRECT_CARD_PROCESSORS`, defaulting to
`eltrovox,emerchant,worldpay,testing`. It stays as a guard — the CRM has
advertised direct card for processors that then rejected the charge — but it is
env-driven, so enabling a processor CRM-side no longer needs a website deploy.
The processor is logged whenever the guard downgrades a payment to hosted.

The fallback for the opposite case was also fragile: when the CRM refuses a
direct charge the site retries it on the hosted page, but the trigger was an
exact match on *"direct card charging is only available for eltrovox/emerchant
intents"*. That message names the allowed processors and the list grows, so the
match now ignores the list; otherwise the first CRM-side change to the wording
would have left intents abandoned in exactly the same way.

Covered by `tests/test_wallet.py`: every configured processor is charged
directly, an unlisted one still goes to the hosted page, the list is
configurable, and a refused charge falls back rather than abandoning the intent.

**Deploy:** website service only. No CRM or Worldpay configuration change.

### Processor discovery was minting a EUR 5.00 pending intent per login (2026-08-30)

**Symptom.** Reviewing the first Worldpay top-ups after the fix above, a
customer appeared to have paid twice: a pending EUR 5.00 at 07:12 and an
identical completed one at 07:17. The customer had not tried twice. The pending
row recorded no card (`****`) where the completed one recorded
`MASTERCARD ****9365`, so no card was ever submitted against it.

**Cause.** The add-funds page has to know whether the customer's country routes
to a hosted-only processor, because that decides whether to ask for card and
billing details. The CRM does not expose Processor Rules, so the only way to ask
is a `start_hpp: false` init — and the CRM persists every init as a payable
intent. The probe is hardcoded to 500 cents, so each one leaves an abandoned
EUR 5.00 pending top-up. The answer was cached in the session, so this happened
once per login rather than once per page view, but a customer logging in three
times produced three of them.

**Confirmed** by the CRM intent metadata for one of them:

```json
{
  "created_by": "customer",
  "purpose": "wallet_topup",
  "website_routing_attempt": 1,
  "website_routing_rule": "CO",
  "website_routing_session_id": "d6f16e87-0820-4c92-8916-28a634a073c4"
}
```

Website routing metadata and nothing else: a rule was matched and a routing
session allocated, but there is no processor transaction, no gateway reference
and no card. The intent never left the CRM. That one was GBP 5.00 where the
first was EUR 5.00 — the probe sends 500 minor units regardless of currency,
which is the signature to look for.

**Identifying the backlog:** `purpose: wallet_topup`, status pending, amount
exactly 500 minor units, `website_routing_attempt: 1`, and no processor
transaction. Those are probes, no customer ever saw them and no money is
involved, so they can be closed as abandoned without contacting anyone. A
genuine abandoned top-up is distinguishable by the amount alone in most cases,
since 500 is only ever a coincidence.

This also settles the open question about the `AUTHORISED` gateway event seen
against the first pending row: probes do not reach the gateway, so that was a
last-known event denormalised onto the customer rather than a live
authorisation hold. No customer money was held.

**Where the probe came from.** It was a website invention, not something the CRM
asked for. Added 2026-08-27 in `2061ab7` alongside CCM support, to answer a
question API 58 provides no way to ask: which processor will this country route
to, *before* the customer has entered an amount. The add-funds page wanted that
at render time to decide whether to collect card and billing details, because
CCM collects them on its own page.

The API's position is the opposite of the probe's premise. It says the website
"does not need access to the configured rules", and its recommended flow never
asks in advance: collect the amount, call init once, then follow the response,
including `crm_card_form_url` for a CRM-hosted card form. `start_hpp: false` is
documented, but as a way to avoid creating unused *HPP sessions* while offering
a choice UI on a real top-up — one init per payment. Init "creates a payment
intent" regardless, which is what the probe overlooked; the original code
comment asserted that "abandoned probes are inert".

Worth noting that neither CCM nor Worldpay appears anywhere in API 58. Both were
enabled CRM-side after the document the website was built against, so the site
has been inferring behaviour for processors its spec does not cover. That is the
same root as the Worldpay allowlist failure above.

**Fix: Add Funds is now two steps.** The probe is gone, along with
`WALLET_HPP_ONLY_PROCESSORS` and `WALLET_TOPUP_PROCESSOR_PROBE`.

1. `GET/POST /wallet/add-funds` asks only for an amount and creates nothing on
   GET. The POST calls init once, with the customer's country so Processor Rules
   match on something real.
2. Where the customer goes next is read off that response, not guessed:
   `options.direct_card` usable and the processor allowlisted, and they get
   `/wallet/topup/<intent_id>/pay`; a `crm_card_form_url`, and they get the
   CRM's own form; anything else starts the hosted page for the intent that
   already exists.
3. `POST /wallet/topup/<intent_id>/pay` charges that intent. The intent id is
   checked against the one the session started, so it cannot be swapped in the
   address bar. 3DS, pending-settles-by-webhook, and the
   charge-refused-fall-back-to-hosted path are unchanged.
4. `POST /wallet/topup/<intent_id>/hosted` lets a customer on the card step
   switch to the hosted page — the choice UI `start_hpp: false` is actually for
   — without creating a second intent.

A customer with no country on record is asked for one on the amount step, since
that is exactly the case that used to fall through to the "No Match" rule. They
are asked once and never twice: the typed name is matched against the countries
cache, so an empty cache means nothing they type will parse, and a second bounce
would be a customer who can never top up at all. "No Match" is the safety net.

The
one behaviour given up is routing on the billing country typed into the card
form: it is now collected after routing, so it updates the profile for next time
rather than steering this payment. The CRM matches rules on the customer's
country, and a card's billing address is not always that, so this is closer to
the documented model than what it replaces.

Covered by `tests/test_wallet.py`: browsing Add Funds ten times creates nothing,
a card payment and a hosted payment each create exactly one intent, switching to
the hosted page reuses the intent, the payment step refuses an intent the
session did not start, and the amount reaching the CRM is the customer's rather
than a placeholder.

**Deploy notes.** Website service only; no CRM or processor change, and no
migration. Worth knowing:

- Anyone sitting on the old Add Funds page when the deploy lands will post card
  and billing fields the new handler ignores. They get the amount they typed and
  the new card step, and re-enter the card once. Nothing is charged twice —
  the old page could not charge without the CRM creating an intent first.
- `WALLET_HPP_ONLY_PROCESSORS` and `WALLET_TOPUP_PROCESSOR_PROBE` are inert now.
  Leaving them set does nothing; they can be deleted at leisure.
- The `topup_routing` cache table from the previous fix is no longer read or
  written. It can be dropped whenever convenient.
- Verified by hand alongside the suite: the top-up-to-finish-a-purchase journey
  keeps its `next` through both steps and returns to checkout, and the
  hosted-page switch works mid-journey.

**Still open.** A read-only routing lookup from the CRM — country in, processor
and capabilities out, no intent created — would let the amount step show the
customer what to expect before they commit. Not needed for correctness now.

### Hosted-only processors (CCM): amount-only add-funds form (2026-08-27)

CCM collects card + billing on its hosted payment page, so the site must not
ask for those details first. Superseded by the 2026-08-30 entry above: the site
no longer works out in advance whether the customer is headed for a hosted page.
The amount step asks for nothing else, and a CCM-routed intent goes straight to
CCM because its init response offers no usable direct-card option.

- Hosted-only detection: an init response with no usable `options.direct_card`,
  or a routed processor outside `WALLET_DIRECT_CARD_PROCESSORS`.
- After a successful payment, any billing address echoed in the status payload
  is captured into the customer profile (gap-filling only, never overwrites).
  Card data cannot be captured from a hosted page (PCI); if the CRM vaults the
  card it appears under saved cards automatically.

Manual staging checks for CCM:

- [ ] Customer whose country routes to CCM sees the amount-only form and lands
      on the CCM page after one click.
- [ ] Customer whose country routes to a direct-card processor still sees the
      full card + billing form.
- [ ] After a successful CCM payment, profile address is populated if it was
      empty before.

Manual staging checks once rules are enabled in CRM Admin:

- [ ] Top-up with a rule whose first processor fails technically → customer is
      transparently moved to the next processor's payment page.
- [ ] Exhaust all processors → terminal failed page with the "all providers"
      message (no infinite loop).
- [ ] Customer cancels on HPP → cancelled page, no automatic advance.

### Checkout offers: CRM-authoritative pricing (2026-08-27)

The CRM owns offer pricing end to end — its rules hold the cart-value
thresholds, it names the discount percentage, and `/checkout/submit` re-prices
the same cart again. Every website-side calculation was removed:

- The 10/15/20% cart-value ladder is gone. `offer_discount_percent` is now
  derived only from the quote, and the per-item saving shown on each cart row is
  `discount_in_customer_cents` from `quote.lines[]` rather than a share of a
  percentage applied here. Nothing is displayed unless the quote evidences it.
- The offer total comes from `discount_breakdown[]` rows of type
  `checkout_offer_rule` (`amount_in_customer_cents`). The totals already have it
  deducted, so it is no longer subtracted a second time.
- Offer rules are keyed to a locked line count (`offered_quantity`), so a card
  offering a different quantity can never be discounted. Cards are now re-cut to
  a quantity the CRM has a rule for; the old fixed "4 Lines - Best Odds" card
  could never match a 3-line rule.
- Only documented cart-item fields are sent (`_crm_cart_items`). The site's
  private `_is_upsell` marker used to travel inside `options`, which is the field
  the CRM prices add-ons from, alongside `offer_rule_id` and price estimates.
- Recoverable CRM rejections no longer dead-end the customer
  (`_checkout_recovery_action`): a 409/expired quote is re-quoted, a refused
  offer selection is dropped and re-quoted, and a rejected promo code is cleared
  — each with a plain message, on both the cart and at submit.

Diagnostics in the server log per cart render:

- `cart upsell card <sku> x<n> lines: rule_id=... crm_discount_percent=...` —
  whether each card bound to a CRM rule.
- `cart upsell card <sku> re-cut from <n> to <m> lines to match a CRM offer rule`.
- `cart quote applied offers: requested=[...] applied_by_crm=[...]
  offer_discount_cents=... promo_discount_cents=...` — from
  `applied_mm_offer_rule_id`, so a missing CRM rule is distinguishable from the
  website failing to request one.
- A warning when rule ids were requested and the CRM applied none.

Manual staging checks (one real checkout per repointed SKU — MS1, PS1, FRL01):

- [ ] Card advertises a percentage; cart shows the same saving; the confirm
      figure equals the quote total; the order completes and the order detail
      shows the discounted amount.
- [ ] `applied_by_crm` in the log lists the requested rule id.
- [ ] A cart under the €5 base-item floor shows no upsell cards.

### Currency + line-rule audit (2026-08-27, against API doc v58)

`price_in_base_cents` is an amount in the tenant's base currency, so it may only
be shown to a customer whose display currency *is* that base currency. Every
customer-facing price now resolves
`prices_by_currency[<display currency>].amount_cents` first:

- Play picker product lines and add-ons (`play_picker.js` `priceForCurrency`);
  when a currency has no saved price the picker falls back to the base amount
  **and switches the symbol to the base currency**, so nothing is mislabelled.
  The play route backfills `prices_by_currency` from `/store/products` when
  `/store/games/<code>` omits it.
- The cart's cached-price fallback (used only when a quote carries no totals)
  and the upsell item estimate, via `_product_price_cents` in `app.py`.
- Offer/bundle landing page: `locked_price_eur_cents` is legacy base cents (not
  necessarily EUR) and is now labelled with `bundle.base_currency`.
- Catalog/home tiles show jackpots only — no product prices.

The CRM quote stays authoritative: cart totals and the confirm button use
`_quote_payable_cents`, and checkout re-prices the same payload.

Line rules are now read from the product instead of hardcoded (`_line_count_error`):
`website_max_lines_per_item` for the cap, multiples of `bundle_min_lines` for
bundle-priced games, `sale_unit_lines` as the minimum when
`partial_bundle_sales_enabled` (AU partial bundles), and the fixed Lotto (IE)
two-line minimum. Falls back to 50 lines when the SKU isn't in the cache.

Also from v58: the customer's country is what Website Processor Rules match on,
so register forwards the selected `country` and top-up init carries the known
country (the hosted-only flow collects no billing). A
`PAYMENT_ROUTES_EXHAUSTED` error is shown as "payments are not available for
your country — contact support" instead of a retry prompt.

### Checkout offers: the quote path is now the only priced path (2026-08-27)

Discounts still weren't landing, and the reason was structural: nothing surfaced
when the quote path failed. `POST /api/v1/checkout` was used as a silent
fallback, and it prices the cart on its own terms, so every failed quote became a
full-price order that looked successful from both ends.

- **The fallback is no longer silent or unconditional.** It logs at ERROR with
  the reason, and it is refused outright when the cart has an offer rule, a promo
  code or a bundle — the customer is told nothing was charged and keeps their
  cart. `CHECKOUT_DIRECT_FALLBACK=off|auto|on` (default `auto`) forces or
  disables it for a tenant.
- **A missing quote id is logged with the response body** (`_quote_id_from`),
  which is the line that would have identified this weeks ago. The id is read
  from `quote_id`, `id`, `quote.quote_id` or `quote.id`, and non-numeric ids are
  submitted as issued — previously an id the site couldn't cast to `int` was
  discarded, which silently routed the order down the undiscounted path.
- **`include_eligible_checkout_offers` is no longer sent.** It isn't implemented
  in the CRM, and nothing now depends on having asked: eligible offers are read
  from `eligible_checkout_offers`, `eligible_offers`, `checkout_offers` or
  `offers`, at the top level or on the quote, and each rule's id/quantity/percent
  are read from any of the plausible field names. A quote that lists no offers
  now logs a warning naming the consequence (no card can carry a rule id, so the
  CRM prices every line at full).

Diagnosing against the live CRM:

```
python tools/debug_checkout_quote.py <email> <password>            # sweep every SKU
python tools/debug_checkout_quote.py <email> <password> SE1 3      # one cart, in full
```

The sweep prints one row per SKU (subtotal, quote id, eligible offers). Single-cart
mode adds the raw response, the discount breakdown, the `checkout` placement
banners, and a re-quote with the first rule id found.

### Measured: the CRM cannot discount a website lotto cart yet (2026-08-27)

Run against `crm.cloudandahalf.com` with a real EUR customer token, once the
office IP was whitelisted. Every SKU in `/store/products`, at 1–8 lines,
single-product and mixed carts:

- `POST /api/v1/checkout/quote` with `product_code` + `lines[]` returns
  `{"quote": {"currency", "eligible_checkout_offers", "funding", "items",
  "subtotal_cents"}}` — **no `quote_id`** and `eligible_checkout_offers` is
  **always `[]`**. Unchanged by cart size, product, mixed carts, `intent`,
  `tid`, or an `X-CRM-Brand-Slug` header.
- No quote id means `POST /api/v1/checkout/submit` is unreachable for these
  carts, so the order can only be placed through `POST /api/v1/checkout`, whose
  documented request body is `items` + `use_wins` only: it carries no
  `quote_id`, no `promo_code` and no `selected_checkout_offers`. **No discount of
  any kind — offer rule, promo code or bundle — can reach a website lotto order
  by this route.**
- Posting a rule id the site did not receive is correctly refused: `400 Invalid
  checkout offer selection`. A promo code is validated at quote (`400 Invalid
  promo code`), which shows the endpoint knows about MM pricing — it just returns
  no offer rules to this cart shape.
- The `quote_id` + `discount_breakdown` + `eligible_checkout_offers` contract in
  API 58 belongs to the **MM-managed offers quote**, whose items are
  `{product_id, quantity, config_json}`. `/store/products` exposes no numeric
  `product_id` (only `code`), so the website cannot construct that request:
  `{"product_id": 1}` → `400 Unknown or inactive product_id: 1`, and a
  `product_code` in the MM shape → `400 Invalid numbers for product SE1`.
- `GET /api/v1/marketing/banners?placement=checkout` returns zero banners, so
  offers are not discoverable there either (`cart` and `play` are not valid
  placements: `400 Invalid placement`).

So the 27 configured offer rules cannot take effect from the website until the
CRM either (a) returns `eligible_checkout_offers` and a `quote_id` for
`product_code` + `lines[]` carts and honours `quote_id` at
`/api/v1/checkout/submit`, or (b) exposes numeric `product_id` values on
`/store/products` plus the `config_json` shape for lotto lines, so the site can
use the MM-managed quote. Either way the website side is already written against
the rule-id contract and needs no further change.

Until then the site behaves honestly rather than breaking: with no rule ids, no
card advertises a discount, nothing is at stake at checkout, and orders complete
at the CRM's full price through `/api/v1/checkout` with an ERROR line in the log
for every quote that carried no offers.

Also observed during this run: SKUs were being moved onto their website variants
between consecutive `/store/products` calls (`MS1` → `MSX-W`, `PS1` → `PSX-W`,
`OZLOT01` → `OZQ-W`, `IRSH01` → `ILS-W`). The `-W` suffix marks a
website-sellable product, so this is the intended catalogue, not drift. The site
reads codes from `/store/products` on each request and hardcodes none, so it
follows the change on its own — but an offer rule still pinned to the pre-`-W`
code cannot match a website cart, which is worth confirming for all 27 rules
once the repointing is finished.

### Mobile number picker: full-screen line editor (2026-08-27)

Under 768px the stylesheet collapses each line to a single row and hides the
number grids, so numbers were unreachable on a phone: the line row carried no
working edit control, and nothing set the `.showTicket` state the legacy mobile
styles were written for. The picker now drives that state:

- Each line opens full screen from the pencil icon or by tapping the row, with
  Quick Pick (hidden once the line is complete, as the legacy styles intend),
  Clear, Done and a close X. Escape and a resize past 768px also close it.
- Opening a line hides the page furniture (nav, banners, how-to-play, other
  lines, order summary, details, long copy, footer) and restores each element to
  the display it had, so a dismissed cookie prompt does not come back.
- The backdrop follows completeness: cream while the line is short of numbers,
  mint once it is complete.
- The open line stays in the page flow (`body.leEditingLine` rules at the end of
  `mobile.css`) instead of the legacy fixed 540px, which clipped games with two
  large grids such as Mega Millions.
- The page now lands on quick-picked lines (the main site's behaviour), so the
  collapsed mobile rows have numbers to show and "Add Quick Pick" on mobile adds
  a picked line.

Manual check on a phone: play page → pencil on line 2 → change a number → Done →
the row shows the new numbers and the total matches the line count; repeat with
Clear (line goes incomplete, backdrop turns cream, Play Now excludes that line).

### Cart: lines are edited in the cart, with the product page's boards (2026-08-28)

Changing one line used to post to `/cart/edit-line` and land the customer back on
`/play`, which lost their place and rebuilt a whole ticket to alter one row. The
boards now open in the cart itself, and the rows they sit in were shrunk: a line
is a small label, its numbers as compact tiles (the same tiles the picker
collapses to on a phone, not the large balls) and a small Edit and remove
control on one row.

- The number-board engine is shared: `static/.../js/line_editor_core.js` holds
  the grids, the quick-pick/clear/toggle rules and the full-screen state, and
  both `play_picker.js` and the new `cart_line_editor.js` drive it, so the two
  pages cannot drift apart.
- Desktop: Edit expands the board inline under the line, with Done and Cancel.
  Mobile: Edit opens the same full-screen editor as the product page, with the
  close X, Clear and Done bar. No navigation in either case; the Edit button
  remains a real form post to `/cart/edit-line` as the no-JS fallback.
- Done posts to `/cart/update-line`, which drops the stored quote id so the CRM
  re-prices the cart. An incomplete line refuses to save. Cancel, Escape and
  closing restore the page exactly as it was, element by element.
- Three legacy-CSS traps are handled in the cart's own style block, each with a
  test in `tests/test_cart_line_editor.py`: the panel sizes every button to
  191x67 `!important`; `#main` carries the site's dark background; and the play
  page's `.lines:hover` grows a line, which in the cart pulls the card out from
  under the pointer and flickers every frame until the controls are unclickable.

Manual check: cart → open an item → Edit on line 1 → Clear → Done is refused →
pick a full line → Done → the row shows exactly those numbers, the item total is
unchanged, and the page furniture is back. Repeat on a phone (full screen) and
with Cancel (nothing changes).

### SEO: taking over lottoexpress.com without losing the rankings (2026-08-28)

The old site's indexed URLs were measured, not guessed: the archived copies of
lottoexpress.com list 850 URLs, and every one of them was replayed against this
app to see what it answered. What that found, and what changed.

**Site-side, done.**

- **Every legacy redirect is now 301.** They were all 302, which asks Google to
  keep the old URL indexed and withhold its signals from the new one.
  `legacy_redirect()` is the single place this is set.
- **Ten of the twelve indexed game pages were dead ends.** `/lotteries/German-Lotto`,
  `/lotteries/American-Powerball` and eight others answered 200 with a "currently
  unavailable" page, because slugs were resolved by fuzzy-matching the CRM's game
  *names* and the CRM has since renamed them ("German Lotto" → "Lotto 6aus49 (DE)").
  `brand_config.py` now maps each archived slug to a confirmed `game_code`;
  name matching remains only as a fallback for games added later. A 200 page that
  says "not available" is a soft 404: Google keeps the URL and ranks nothing.
- **Eight of thirteen indexed results pages 404'd.** Same cause, same fix.
- **Old URL shapes are accepted as linked.** Mixed case (`/lotteries/EuroMillions`),
  `.php`, sub-pages (`/EuroMillions/Lucky-5`, `/French-Lotto/10-to-win`) and one-off
  draws (`-Superdraw`) all resolve to the game. `/safe-play`, `/lottery-results/`
  and lowercase `/favicon.ico` were 404s and now redirect.
- **Products the CRM does not sell** (Australian Powerball, La Primitiva, El Gordo)
  keep their own pages. They 301'd to `/catalog` and `/results`, which is a
  specific well-ranked page handed to a generic one — Google treats that as a
  soft 404, so the signal was being lost anyway. Their copy was recovered from
  the archive and is served at the original URLs. See below.
- **Real status codes.** `/play/<unknown>` returned **500** (the CRM's 404 escaping
  as a server error) and `/results/<unknown>` returned **200** with an empty page;
  both are 404 now. Expired offers and promotions 301 to the promotions index.
- **`<head>` metadata**, from `seo.py` via a context processor, on every page:
  per-page `<title>` and `<meta name="description">`, absolute `rel=canonical`,
  robots, Open Graph and Twitter tags, and Organization JSON-LD. The game and
  results titles/descriptions are the old site's own, recovered from the archive,
  so the wording those pages ranked on is preserved.
- **`noindex, follow`** on account, orders, cart, wallet, admin and token pages.
  Nothing public is noindexed.
- **`robots.txt` now exists** (there was none) and advertises the sitemap on the
  canonical host. **`sitemap.xml`** was twelve static URLs — some of them legacy
  paths that redirect — and omitted every play and results page; it now lists all
  33 canonical URLs with `lastmod`, on the canonical host rather than whichever
  `Host` header the request arrived with.
- **Internal navigation links at canonical URLs.** The nav and footer pointed at
  `/lotteries/<slug>`, so every visitor and crawler took a redirect hop to reach
  the same page.
- **Two site generations older than the PHP one are still indexed**, and were
  404ing. Before PHP this domain ran a localised ASP.NET MVC site
  (`/en/home/faq/`, `/fr/home/termsandconditions/`, `/home/result`) and before
  that an ISAPI site that served every page from one entry point
  (`/pl.dll?PageID=1041`). 67 archived URLs between them, plus `/promotions/`,
  `/main.html`, `/winners.html` and the root `/feed/`. They are matched in the
  404 handler against `brand_config.legacy_path_to_path` — which was declared
  but never wired to anything — and 301 to the nearest current page; the root
  feed now goes to `/blog/feed/`, which finally exists. French was never
  rebuilt, so those URLs land on the English equivalent.

  The map is matched **exactly, never by prefix**. Redirecting whole sections
  would convert genuine 404s into 301s and hide broken internal links, so
  `/home/not-a-real-page` still 404s. `tests/test_seo.py` guards both halves.

`tests/test_seo.py` asserts all of the above against the real archived URLs.

### Retired products: the pages for lotteries we stopped selling (2026-08-28)

Three products the old site sold are not in this CRM: **Australian Powerball**,
**Spanish Lotto 6/49 La Primitiva** and **El Gordo**. Seven archived URLs point
at them — three product pages and four "winning numbers" pages.

**Why they are pages and not redirects.** The product pages carried 1,894–2,240
words each of purpose-written copy: draw schedule, odds, a nine- to
seventeen-row prize table and a set of FAQs, each with its own title and
description. Redirecting that to `/catalog` handed a specific, well-ranked page
to a generic one, which Google treats as a soft 404 — the ranking was being lost
either way, just quietly. The copy is recovered by `tools/retired_harvest.py`
into `content/retired/<slug>.json` and served at the original URL.

**Why they carry no live numbers.** The CRM's `/api/v1/draw-results` is keyed by
the `game_code` of a game in its catalogue, and it holds 556 draws across exactly
the ten games it sells — nothing for these three. A results page for them would
render an empty grid, which is the soft 404 we are trying to avoid. So the four
retired results URLs 301 to the matching **product** page instead of the generic
`/results` index: someone searching "Australian Powerball winning numbers" gets
the Australian Powerball page, not a list of ten other lotteries.

| Archived URL | Now |
|---|---|
| `/lotteries/Australian-Powerball` | 301 → `/lotteries/australian-powerball` (200) |
| `/lotteries/Spanish-Lotto-649-La-Primitiva` | 301 → `/lotteries/spanish-lotto-649-la-primitiva` (200) |
| `/lotteries/Syndicate/El-Gordo` | 301 → `/lotteries/el-gordo` (200) |
| `/lottery-results/australian-powerball-winning-numbers` | 301 → `/lotteries/australian-powerball` |
| `/lottery-results/el-gordo-winning-numbers` | 301 → `/lotteries/el-gordo` |
| `/lottery-results/spanish-lotto-649-la-primitiva-winning-numbers` | 301 → `/lotteries/spanish-lotto-649-la-primitiva` |
| `/lottery-results/spanish-lotto-winning-numbers` | 301 → `/lotteries/spanish-lotto-649-la-primitiva` |

**Saying so honestly.** The recovered copy was written while we sold the game and
still says things like "buy your ticket today" and "how to claim your prize". So
the page opens with an unmissable notice that Lotto Express no longer offers it,
before any of that copy; the copy sits under "How *X* worked at Lotto Express";
and the prize tables and draw dates are labelled as published-at-capture and not
maintained, because El Gordo's still names a December 2023 draw date. Every call
to action on the page points at a game we do sell — the two Australian draws for
Australian Powerball, the pan-European ones for the Spanish pair.
`tests/test_retired.py` asserts each of those, including that no `/play/` link
for the retired product itself can appear.

**Matching order matters.** The retired lookup runs *before* `resolve_game_code`
in both `/lotteries/<slug>` and `/lottery-results/<slug>`. That resolver scores
slugs against CRM game names and will read "australian-powerball-winning-numbers"
as the US Powerball; these seven slugs are known exactly, and exact beats fuzzy.
The `legacy_slug_to_path` entries remain as the fallback for a deploy missing
`content/retired/`, and must keep pointing outside `/lotteries/` or the redirect
would loop.

**Full-site replay, 2026-08-28.** All 1248 archived URLs (pages *and* assets)
replayed against the app: 617 answer 200, 216 redirect once to a live page, 16
are deliberate 410s (WordPress plumbing), and 399 are 404. Every one of those
404s is old application plumbing rather than a page — 88 images, 57 ASP.NET
`.axd` handlers, 41 scripts, 97 fonts, 42 stylesheets and 13 `api` calls — apart
from five: four PHP session XHR endpoints (`/resources/php_functions/*.php`,
never pages, never indexed as such) and one mangled `/C/O` link. **No page URL
the old site published is unreachable.**

Re-run after any routing change with:

```bash
python tools/url_replay.py --base http://127.0.0.1:8003 --prefix lottoexpress.com/ --assets --csv replay.csv
```

**State of the cutover, verified live at 2026-08-28 18:20 PT.**

The switch happened during this work. `lottoexpress.com` now serves this app on a
valid certificate, `www.lottoexpress.com` 301s to it, and the deployed build has
the changes above: `/lotteries/German-Lotto` → 301 `/play/lotto-6aus49`,
`/robots.txt` and a 33-URL `/sitemap.xml` return 200, canonical tags and
descriptions render, `/play/nope` is 404. All 44 archived marketing, game and
results URLs answer 200 or 301 against production.

**Settled since:**

- **Canonical hostname is the apex**, not www as first chosen. Infrastructure had
  already shipped www → apex 301 with the apex serving and `WEBSITE_CANONICAL_DOMAIN`
  left at `lottoexpress.com`, which is internally consistent — canonical tags,
  sitemap and the redirect all agree. Keep it. Flipping to www now would be a
  second hostname migration on top of the first, for no gain: 301 consolidation
  works in either direction. Do not set `WEBSITE_CANONICAL_DOMAIN` to www while
  Front Door redirects www → apex, or every page would point its canonical at a
  URL that redirects back.
- **HTML caching is fixed.** HTML now answers `no-store`; the earlier
  `public, max-age=86400, immutable` is gone.
- **Nothing is geo-blocked.** CRM website policies report no blocked countries and
  a Googlebot user agent is served a normal 200, so there is no 403 risk to
  crawling.
- **Legacy assets are cached by the app.** `/resources/*` was answering `no-store`
  — every page reload re-downloading the whole legacy CSS/JS/image set, which is a
  Core Web Vitals cost. `legacy_resources()` now sends a month for versioned
  requests (`?v=<build_id>`) and images/fonts, and an hour for anything else, so a
  deploy still reaches people the same day. Front Door's caching rule covers
  `/static/*` only; extending it to `/resources/*` would let the edge serve them
  too, but the app's own headers are enough.

**Still outstanding.**

1. ~~**The blog: archived URLs under `/blog/` 404ing.**~~ **Resolved — the blog is
   now served by this app.** See `docs/BLOG.md` for how it works and how to
   publish. The short version:

   The plan had been to route `/blog/*` at Front Door to the WordPress origin,
   but there is no origin left to route to (checked 2026-08-28):

   - `wp.lottoexpress.com` → `138.91.164.145`, an IIS host that answers, but
     `/blog/`, `/blog/feed/` and `/blog/wp-login.php` all return IIS "File or
     directory not found" and `/` serves the default *IIS Windows Server* page.
     Retried with `Host: www.lottoexpress.com` and `Host: lottoexpress.com` in
     case of host-header binding: same 404s.
   - `blog.lottoexpress.com` is a CNAME onto the apex, so it lands on Front Door.
   - The legacy site copy in `Lotto Express\wwwroot\wwwroot` has no `blog`
     directory and no rewrite or proxy rule for one in `Web.config`.
   - The archived blog is WordPress 6.7.1 and every self-reference (REST root,
     pingback, shortlink, canonical) is `https://www.lottoexpress.com/blog/`, so
     it was served under the main hostname at `/blog` by the old edge. Nothing
     names a separate host.

   So the content was recovered from the Internet Archive instead
   (`tools/blog_harvest.py`) and is served from `content/blog` at exactly the
   URLs WordPress used — 115 posts, 9 categories, 36 tags, the paginated index
   and the RSS feed, with the images restored to
   `/blog/wp-content/uploads/...`. Nothing was redirected because nothing moved.

   What the archive had, and what happened to each part:

   | Archived | Count | Now |
   | --- | --- | --- |
   | Posts | 115 recovered of 117 | 200 at the same URL |
   | Uploads | 337 | 200, recompressed, same paths |
   | Tag archives | 43 | 200 |
   | Category archives | 18 | 200 |
   | Paginated index | 8 | 200; past the end 301s to page one |
   | Feeds | 2 | `/blog/feed/` 200; `/blog/comments/feed/` 410 |
   | WordPress plumbing | 15 | 410 Gone, deliberately |
   | ShortPixel/oEmbed junk paths | 18 | 301 to the page they hang off |

   The two posts that did not recover are `/blog/q_glossy` and `/blog/ret_img`,
   which were never posts — they are ShortPixel proxy artefacts.

   Post bodies were cleaned on the way in: HubSpot, MonsterInsights and GTM
   removed, images pulled back off the ShortPixel CDN, and in-body links
   rewritten to canonical URLs so `/lotteries/Irish-Lotto/Lucky-5` now links
   straight to `/play/lotto-ie` instead of through a 301. Those internal links
   are part of why the product pages rank.

   **If the WordPress install is ever found**, this does not have to be undone:
   put a `/blog/*` route in front of it at Front Door and requests stop reaching
   the app. If you do, first change WordPress's `siteurl`/`home` to
   `https://lottoexpress.com/blog` — they are currently the `www` host and Front
   Door 301s `www` to the apex, which would loop.

   The root-level feed URLs in the archive (`/feed/`, `/feed.xml`, `/atom.xml`,
   `/index.xml`, `/feeds/all.atom.xml`) were never feeds — the old site answered
   its homepage HTML at 200 for them — so they need nothing.
2. **`www1.lottoexpress.com` is broken**: TLS fails (`*.azureedge.net` certificate)
   and it returns Front Door's 404. If it is still wanted for QA, rebind it; when
   it comes back it must not be indexable, so either 301 it to the apex or keep it
   behind auth. Leaving it dead is also fine.
3. **Search Console:** verify both hostnames (so the www → apex redirect can be
   seen working), submit `https://lottoexpress.com/sitemap.xml`, and check
   Pages → "Not found (404)" for how long the domain was answering 404 before the
   cutover. Then watch coverage and the `/lotteries/*` and `/lottery-results/*`
   redirect targets for two to four weeks.
4. **Optional:** `/ads.txt` and `/app-ads.txt` 404. The old site answered HTML for
   them, so there is nothing to preserve — only needed if programmatic ads are sold.
5. **Replay the archived URLs after every deploy that touches routing.**
   `tools/url_replay.py` pulls the list from the Wayback CDX API and requests
   each one, reporting anything that 404s, 500s, redirects twice or redirects to
   a dead page:

   ```bash
   python tools/url_replay.py --base https://lottoexpress.com
   python tools/url_replay.py --base https://lottoexpress.com --prefix lottoexpress.com/blog/
   ```

   It exits non-zero when something is broken, so it can gate a release. Add
   `--assets` to include the old site's images, scripts and fonts; that run
   always exits non-zero, because ~390 dead assets from the retired ASP.NET and
   WordPress stacks are expected. Compare the count against the baseline in the
   SEO section above rather than expecting zero, and use `--csv` to diff.

Documented but not implemented on the website (conscious gaps, revisit post-launch):

- Catalog wheels (`/store/games/<code>/wheels`, `wheel_catalog_key`).
- Multi-draw/subscription scheduling (`ticket_mode`, `draw_weeks`, `draw_weekdays`,
  `start_on_date`).
- Saved items (Save for Later), progressive jackpots, website policies endpoint.

### Wallet funding: a balance is two pots, and one of them needs permission (2026-09-14)

Customer A1009227 held USD 14.86 — USD 5.07 deposited, USD 9.79 won — and was
refused a USD 5.80 Powerball line four times (15:17:00, 15:19:51, 15:22:02,
17:12:47 UTC). The CRM was right every time. Checkout spends added funds and
leaves winnings alone unless the request carries `use_wins: true`, which the
customer has to authorise, and nobody had asked her.

**The contract.** `wallet.balance_cents` is the total. So is
`available_balance_cents` — it is added plus wins after reservations, not
"spendable without winnings". The only figure a default checkout will spend is
available added funds: `added_funds_balance_cents` less
`reserved_added_funds_cents`. Every total in that response is a trap, and this
repo fell into two of them.

**What was wrong here.**

- The checkout fallback sent `use_wins: true` on every order, spending
  winnings with no authorisation at all. The CRM preserves winnings by default
  precisely so that cannot happen by accident; the website overrode it. Now the
  flag is only ever sent because the customer pressed the button that says so,
  and it is read from that request rather than remembered.
- An earlier fix on the same day read `available_balance_cents` as the
  spendable figure. It is a total, so that was the same mistake wearing a
  different field name. Both readings are pinned shut in
  `tests/test_checkout_winnings.py`.

**What the site does now.** `quote.funding` gives two shortfalls — with the
winnings and without — and the cart branches on them. Deposits short but
winnings would cover it is a question ("use winnings, or add funds"), not a
refusal. Only when both pots together fall short does anything say insufficient
funds, and then it names the real gap. A 402 carrying unspent winnings is
handled on the same terms, for quotes that arrive without a funding object.

Header, wallet tab and cart all show three amounts. A total on its own beside a
pay button is a promise the button cannot keep.

### Mail-order customers invited onto the website (2026-09-18)

Former AS400 customers are being invited to open a website account, with a link
of the form `/register?lst=<token>`. The CRM holds their record; the token is
the key to it.

**The token is captured in `_load_context`, not in the register view,** exactly
as `spt` and `rt` are. That is what lets someone open the link, read about the
games for ten minutes, and still be recognised when they reach the form. Like
those two it is held apart from `mkt`, never logged, and stripped from
analytics — it is a lookup key for a name and a date of birth, not attribution.

**The email is not theirs to type.** The CRM issued the invite against an
address it has already verified, and that address is the identity being
claimed. It is rendered read-only with a line saying how to get it changed, and
— this is the part that matters — `POST /api/v1/auth/legacy-signup/claim` does
not carry an email field at all. `readonly` is a courtesy to the person filling
the form in; anyone can reopen the box in devtools, and it changes nothing.

**Date of birth is required on this path and only this path.** 34,521 of these
records have none, and the CRM only refuses an under-18 when it is given a date
to judge, so until KYC the form is the whole age check.

**A dead invite is never a dead end.** Expired, already claimed, unknown, CRM
down, a claim refused for a reason nobody anticipated, or a claim that succeeds
without returning a usable set-password token — every one of them falls through
to the ordinary sign-up, because someone in their seventies who followed a link
from an envelope must still end up with an account. The one thing the failure
message must not do is say *why*: the CRM endpoint answers about a token and
never about an address, precisely so a list of emails cannot be tested against
it, and a message here naming the reason would hand that back.

**The invited form has no password box.** The claim endpoint does not take a
password, and the CRM answers it with a set-password token instead, so a box on
this form would be typed into, thrown away, and then asked for again on the
next page — three entries for one password, for a list whose median age is 71.
They choose it once, on the page built for it, and the submit button says
Continue rather than Create New Account. The cost is that a *failed* claim can
no longer quietly register them, since there is nothing to register with: they
are put back on the full form with the CRM's message and an instruction. Their
typed details are lost at that point, which is deliberate — stashing a name and
a date of birth in the session cookie to survive the redirect is the thing the
reactivation prefill goes out of its way not to do.

Currency defaults from the country on the CRM record (GB to GBP, US to USD,
everything else keeping the existing EUR default), and is still theirs to
change. A customer the CRM has on file in Liverpool should not be offered a
euro account because that is what the form always did.

A successful claim returns a short-lived `spt` and is handed to `/set-password`
exactly as an emailed link would be, so there is one implementation of choosing
a first password. The field name is read tolerantly (`spt`, `set_password_token`,
`token`) because these endpoints are in no published version of API.md — the
last time a field name was guessed at, a payment flow failed live on
`hosted_url`.

Every existing bot control applies unchanged. The invite path is the more
attractive target of the two, since it makes accounts against addresses the CRM
has already verified.

### Support staff viewing an account as the customer (2026-09-17)

CRM staff with `customers.login_as` open this site as a customer without the
customer's password. The CRM sends the staff browser to
`/support/login-as/<audit_id>?token=…`; the site trades that handoff for a
customer bearer token the CRM restricts to `GET`, `HEAD` and `OPTIONS`.

**The handoff is a credential in a URL,** brand-bound, single-use and good for
two minutes. It is exchanged on arrival and never stored, never logged and
never sent to analytics; the session is recorded by audit id instead. The route
redirects straight to `/account` under `Referrer-Policy: no-referrer` and
`Cache-Control: no-store`, so it leaves the address bar, the history and the
`Referer` of everything the next page loads. It is also excluded from marketing
capture — a support session is not a visit, and filing it as one would put
staff activity in the customer's acquisition record.

**The staff browser was probably already signed in as somebody,** quite
possibly the customer from the previous ticket. Everything customer-scoped goes
before the new token lands: the cart and quote, the cached wallet, a staged
billing address, pending checkout state, account filters, and any set-password,
reactivation or payment-link token still sitting in the session. One customer's
things appearing under another's name is the failure worth preventing here.

**Read-only is enforced by the server, not by greying out buttons.** A
`before_request` guard refuses every non-GET while the marker is live, so a
route added later is covered without anyone remembering to cover it. This
matters because much of this site changes state without asking the CRM
anything — adding to a cart, applying a promo code, staging an address — and
the CRM's own refusal would never see those. `/login` is exempt, or the marker
outlives the tab and traps the next person at that desk; `/admin` is exempt
because it has its own gate and its own credential. API callers get the
contract's `SUPPORT_SESSION_READ_ONLY` so they know not to retry.

The banner is on every page for the hour the session lasts, not flashed once.
The marker clears on logout and on any real login (password, set-password or
registration), and expires on its own at the CRM's one-hour ceiling — checked
on read, so the session ends rather than degrading into a page whose every
request is refused.

---

## 3. Automated suite layout

| File | Covers |
|---|---|
| `tests/test_public_pages.py` | Home, catalog, play page (+countdown regression), results, static/legal pages, legacy redirects, sitemap, health, 404 |
| `tests/test_auth.py` | Login success/bad-credentials/missing-fields, logout, register, forgot password, auth gates on protected routes |
| `tests/test_cart_checkout.py` | Cart render (numbers as compact tiles), add-to-cart logged in and logged-out capture, invalid payloads, clear cart, checkout auth gate |
| `tests/test_wallet.py` | Add-funds render, top-up return pages (success/failed/cancelled), auth gates |
| `tests/test_legacy_signup_invite.py` | AS400 invite links (`?lst=`): token capture and secrecy, prefill, read-only verified email, required date of birth, claim instead of register, and every dead-invite path falling back to an ordinary sign-up |
| `tests/test_support_login_as.py` | Staff "Login As" handoff: service-key exchange, token never stored/logged/tracked, prior customer's cart and wallet cleared, server-side write block, persistent banner, every documented failure, expiry and marker clearing |
| `tests/test_account_order_history.py` | Account order history detail rows; legacy section visibility |
| `tests/test_legacy_orders.py` | Full legacy orders feature (tab, list, pagination, detail, 404, errors) |
| `tests/test_pricing_currency.py` | Display-currency pricing (`prices_by_currency`), product-driven line rules, country persisted for processor routing, `PAYMENT_ROUTES_EXHAUSTED` messaging |
| `tests/test_checkout_offers.py` | Offer discounts shown only when the quote evidences them, card line counts matched to CRM rules, item payload hygiene, recovery from 409 / refused offer / rejected promo, no silent full-price fallback, quote ids honoured as issued |
| `tests/test_play_page_mobile.py` | Mobile full-screen line editor: controls on every line, picker wiring, shared engine loaded first, page furniture restored, lines quick-picked on load |
| `tests/test_checkout_winnings.py` | A wallet is two pots: added funds are spent by default and winnings only on the customer's say-so. A cart the deposits cannot cover but the winnings can is a question, not a refusal; both pots short is the only case that says insufficient funds, and it names the real gap. Covers the authorisation never being sent unasked or outliving its order, the 402 recovery for quotes with no funding object, three amounts in the header, cart and wallet tab, and the two totals (`balance_cents`, `available_balance_cents`) that must never be read as spendable |
| `tests/test_cart_line_editor.py` | Editing a line in the cart: board markup and per-SKU schema shipped, saves via `/cart/update-line` and drops the stale quote, opens in place instead of navigating, legacy-CSS guards |
| `tests/test_seo.py` | Cutover parity for the real archived legacy URLs: 301 (not 302) to the right game/results/static page, old casing and `.php` and sub-pages accepted, retired products routed rather than dropped, no redirect chains, 404 for missing games, per-page canonical/title/description, noindex only where intended, robots.txt and full sitemap on the canonical host, internal links canonical, the blog is part of the site rather than a hole in it |
| `tests/test_retired.py` | The three products the CRM does not sell: their recovered pages answer 200 at their own URL, every archived play and results URL reaches one in a single hop, the "no longer offered" notice precedes the recovered copy, stale prize tables and draw dates are labelled, no call to action leads to the retired product, the pages carry their own title/description/canonical and are in the sitemap, and a legacy slug with no recovered page still reaches the catalogue |
| `tests/test_blog.py` | The recovered blog: every post answers at its original URL with its own title/description/canonical and `BlogPosting` markup, the old marketing stack and ShortPixel proxy did not come back, images are local, in-body links reach products in one hop, pagination and category/tag archives behave as WordPress's did, junk paths walk back to their page, WordPress plumbing is 410, posts are in the sitemap with real `lastmod` |

Run: `python -m pytest tests/` from the repo root. All tests stub the CRM — no
network access, safe to run anywhere.
