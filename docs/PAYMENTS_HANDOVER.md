# Wallet top-ups: what we got wrong, for the other site

Written for a sibling site on the same CRM (Website API 58). Both problems below
were ours, not the CRM's, and both produced the same customer-visible symptom:
a top-up that goes "pending" and never completes, with no money taken and no
error anyone sees. If your site talks to `wallet/topup/*`, it is worth checking
for both even if payments currently look fine — the first only fires when a
processor is enabled CRM-side, and the second is silent by design.

Endpoint and field names below are the CRM's. Our own function names are
mentioned only where it helps you find the equivalent in your code.

Defects 1 and 2 were written on 2026-08-30 and cover the top-up flow itself.
Defects 3 to 8 were added on 2026-09-08 and all come from one week of running
multi-processor routing in production — read them together, because they
compound: each one turns a recoverable payment into a stranded intent, and the
CRM has no way to release a stranded intent afterwards.

Non-payment fixes from the same fortnight — country blocking, background CRM
work, draw countdowns, play-page draw days — are in `SITE_HANDOVER.md`.

## Defect 1: a hardcoded list of "processors we can charge directly"

**Symptom.** Worldpay was enabled in the CRM. Every customer the CRM routed to
Worldpay got a top-up stuck pending. Nothing reached the processor, so there was
nothing to retry or release — the intents were created and then abandoned.

**Cause.** The CRM tells you, per intent, whether it will accept a direct card
charge: `options.direct_card.available`, with a `charge_url` alongside it. We
did not trust that alone, because the CRM had returned `available: true` for
processors whose charge endpoint then rejected the intent. So we also checked
the routed processor against a list of processors we believed could be charged
directly — and that list was a literal in the source: `{eltrovox, emerchant,
testing}`.

Worldpay was not in it. So for Worldpay-routed intents we overrode the CRM and
sent the customer to the hosted payment page instead. Worldpay was not
configured for a hosted page, the CRM refused to start one, and the intent was
left sitting there. Enabling a processor in the CRM silently broke it on the
website, and fixing it required a code change and a deploy.

**Fix.** Keep the list — it guards a real CRM behaviour — but read it from
configuration rather than source. Ours is the `WALLET_DIRECT_CARD_PROCESSORS`
environment variable, defaulting to `eltrovox,emerchant,worldpay,testing`.
Adding a processor CRM-side is now an env change and a restart.

**Also do this**, because the list will go stale again. When a charge is refused
with the CRM's "direct card charging is only available for ..." error, do not
fail the payment: start the hosted page on the *same* intent and let the
customer carry on. That turns a stuck pending intent into a completed payment,
and it is what limits the damage next time a processor is enabled before anyone
updates the env.

## Defect 2: a "probe" that minted a real, payable intent per visit

**Symptom.** A pending wallet top-up for a fixed small amount — for us GBP/EUR
5.00, described in CRM reports as "Wallet top-up via worldpay (API)" — appearing
against customers who never tried to add funds. They accumulated steadily and
polluted every pending-payments report.

**Cause, and this is the part worth reading.** Nothing in the API asked for
this. We invented it.

The Add Funds page rendered a card form, and to render it correctly the page had
to know things it could only learn from the CRM: which processor the customer
would be routed to, and whether that processor could take a card directly or
needed the hosted page. But the CRM only answers that question as part of
`wallet_topup_init` — and `wallet_topup_init` **creates a payment intent**.

So on page load we called `wallet_topup_init` with a placeholder amount of 500
minor units and `start_hpp: false`, read the routing out of the response, and
threw the response away. A throwaway question to the CRM, from our side. A real,
chargeable, permanently pending payment intent, from the CRM's side.

We then made it worse before we made it better, by caching the answer per
country to reduce the number of probes. That reduced the volume and kept the
defect.

Two things to take from this. `wallet_topup_init` is not a read. Treat every
call as committing to a payment you intend to collect. And if you find yourself
needing routing information before the customer has committed to an amount, the
page is asking for information in the wrong order — which is the fix.

**Fix: take the amount first, then let the CRM shape the payment step.**

The Add Funds page now asks only for an amount and calls nothing. The intent is
created once, when the customer submits that amount, for the amount they
actually typed. The response to that single `init` decides what happens next,
so there is nothing left to guess and nothing to probe:

1. `GET /wallet/add-funds` — amount input only. No CRM calls at all.
2. `POST /wallet/add-funds` — validate the amount, then one `wallet_topup_init`
   with the real `amount_cents`, `return_urls`, `start_hpp: false`, and the
   routing `country`. Read `options.direct_card` off the response.
   - Direct card available (and the routed processor passes the allowlist):
     redirect to the payment step for that intent.
   - Otherwise: `wallet_topup_hpp_start` on that same intent and redirect.
3. `GET /wallet/topup/<intent_id>/pay` — the card form, for an intent that
   already exists.
4. `POST /wallet/topup/<intent_id>/pay` — `wallet_topup_charge` against that
   intent. On the CRM's direct-card refusal, fall back to the hosted page on the
   same intent rather than failing.
5. `POST /wallet/topup/<intent_id>/hosted` — lets the customer switch to the
   hosted page themselves, reusing the intent.

Every route from step 3 on takes the intent id in the URL, so **check it against
the one in the session** before doing anything with it, or you have handed
anyone a way to drive a charge at an intent that is not theirs.

The invariant to hold on to, and the one to write tests around: **one intent per
top-up the customer actually asked for, and never one from browsing.** Our two
guard tests load the Add Funds page ten times and assert zero `init` calls, and
complete a payment and assert exactly one.

## Defect 3: assuming every processor has a hosted page

**Symptom.** A customer routed to Worldpay or Z1 saw a failure page for a
processor that was sitting there ready to take a card.

**Cause.** The site had exactly one answer to "the CRM says no direct card
here": use the hosted page. Worldpay and Z1 have no hosted page at all — there
is no `/hpp/start` for either — so that answer called a route the CRM does not
have. Harmless for as long as Worldpay was on the direct-card allowlist and
charged directly; live the moment a routing advance lands on such a processor.

**Fix.** Read the flow off what the response actually advertises, and offer
nothing else:

- Direct card when `options.direct_card` says so.
- Hosted when `options.hpp` **or** `options.hosted_checkout` is present. Both
  exist; which one you get is per processor.
- Fail only when neither is there.

Hide the "pay on the secure page instead" button on the card form when the
processor has no hosted page, or you are offering a button that can only fail.

The per-processor rule, from the CRM team. API 60 documents neither Worldpay nor
CCM, and its `/hpp/start` section is out of date, so do not take the doc's word
for this:

| Processor | Direct card | Hosted page |
| --- | --- | --- |
| Worldpay | yes | no |
| Z1 | yes | no |
| TRAXX | yes | yes (`hosted_checkout`) |
| Emerchant | if enabled | yes (`hpp`) |
| EltroVox | if enabled | yes (`hpp`) |
| CCM | no | yes (`hosted_checkout`) |

## Defect 4: the allowlist vetoing a processor with nowhere else to go

The allowlist from Defect 1 is a guard over the CRM's answer. Applied to a
processor that has no hosted page, it guarantees a dead end: you refuse to
charge, and the only fallback does not exist. Trusting the CRM there at worst
ends at the same failure and at best takes the payment.

**Apply the allowlist only where a hosted page is actually available.**

## Defect 5: one processor's options do not look like another's

**Symptom.** Every Worldpay decline in Colombia advanced onto TRAXX, created an
intent, and stopped. Six attempts, six stranded `pending` TRAXX intents, nothing
paid. The customer restarted each time and landed back on Worldpay, because a
new top-up starts a new routing session at the front of the rule.

**Cause.** We looked for `options.direct_card.available` plus a `charge_url`.
TRAXX advertises neither. Its real shape, confirmed by the CRM team and absent
from API 60:

```json
{
  "direct_card": { "allowed": true, "status": "available" },
  "hosted_checkout": { "start_url": ".../wallet/topup/<id>/hpp/start",
                       "return_urls": { "success": "…", "fail": "…", "cancel": "…" } }
}
```

No `available` bool, no `charge_url`, no `cards_url`. So a processor that was
ready to take a card read as offering nothing at all.

**Fix.** Accept both shapes. Charge when `available === true` with a
`charge_url`, **or** when `allowed === true` and `status === "available"`. A
missing URL is not a refusal — `/charge` and `/hpp/start` are both addressed by
intent id, so you build them yourself and the advertised URL was never
load-bearing. An absent or disagreeing `direct_card` block still is a refusal.

**The trap that nearly wasted the deploy.** Teaching the site the new shape is
not enough on its own: the Defect 1 allowlist will then veto the processor
straight back onto the hosted page. Adding the processor to the list's *default*
fixes nothing on a server that sets `WALLET_DIRECT_CARD_PROCESSORS` by hand,
which production does. Track *which* shape answered and exempt the new one from
the allowlist entirely — the guard was written for `available`, a flag the CRM
had returned untruthfully, and it has nothing to say about a pair no processor
returned at the time.

## Defect 6: treating "we will not take a card" as a decline

**Symptom.** Worldpay refused, the site advanced to TRAXX, TRAXX came back
`failed` with no card recorded against it, and the site advanced again to
Emerchant, where the customer gave up. Three processors spent on one payment.

**Cause.** A charge refused with the CRM's "direct card charging is only
available for ..." error is a *configuration* answer — the brand has direct card
switched off for that processor and nothing reached a bank. We were feeding it
into the routing machinery like a real decline.

**Fix.** Check for that refusal **before** advancing, and fall back to the same
processor's own hosted page where it has one. A switched-off toggle then costs a
redirect instead of a processor from the rule and another card form. Where the
processor has no hosted page, advancing is right, because there the alternative
really is a failure page.

## Defect 7: failures that leave no trace, and intents that cannot be cleaned up

Two things made the above far slower to diagnose than they should have been, and
both are worth fixing before you need them.

**A swallowed error looks identical to a call never made.** Our hosted-page
start caught `CRMError` and returned `None` with no logging. From the CRM's side
of the API there was no successful session; from ours there was no record of
trying. Log every CRM refusal, and log what a processor advertised when you
decide you cannot use it — the mode, the top-level keys, the `options` keys and
the `direct_card` flags. Leave URL *values* out: they carry tokens.

**An advance you cannot use strands an intent for good.** There is no cancel or
abandon endpoint for a pending routed intent, and per API 60 the CRM never
reuses a pending or unknown attempt. So every dead-ended advance leaves a
permanent `pending` row that nobody is waiting on and nobody can clear. Ask your
CRM team for an abandon endpoint. Until it exists, the only defence is not
dead-ending, which is what Defects 3 to 6 are about.

## Defect 8: the second card form, unexplained

Card details cannot be carried to another processor — the CRM is explicit about
this and it is right — so an advance onto a processor that takes cards has to
ask for the card again. Unexplained, that reads to the customer as the site
having lost the payment, and they stop. **Every `pending` intent at the tail of
a cascade is somebody who stopped at one of those forms.** Say why you are
asking: the previous provider declined, and you have switched to another.

## Details that cost us time

**The routing country is the customer record's, not the form's.** Website
Processor Rules match on the country persisted on the CRM customer (API 58). We
read it from the customer record, falling back to geo-IP so a first top-up can
route before billing has ever been collected. A blank country falls through to
the CRM's "No Match" rule.

If you ask the customer for a missing country, **ask at most once**. We match
what they type against a cached country list, and if that cache is empty nothing
they type will ever parse — a second bounce is a customer who cannot pay at all.
Ask once, then send the top-up without a country and let "No Match" decide.

Watch for the country you *route* on diverging from the `billing_country` you
send. They are separate values and it is easy to let them drift apart.

**Processor Rules can advance on failure.** When `init` fails, the error payload
may carry `routing.can_advance: true` and `routing.resume_payload`. Retry `init`
with that `routing_session_id` and the CRM moves to the next eligible processor.
Never retry the same processor directly, and cap the attempts — we allow five.

**API 60: a declined charge advances too, without a round trip.** This is newer
than the rest of this document and worth implementing properly. A routed
direct-card decline on `wallet_topup_charge` now carries the same
`routing.can_advance` / `routing.resume_payload` in its *error* payload, so the
next processor can be started immediately rather than waiting for the customer
to come back through a return URL. The rules:

- Post the `resume_payload` to `init`. That creates the *next* attempt. Never
  retry the failed intent and never call the failed processor again.
- Never replay the card the customer gave to one processor at another. Send them
  through the next processor's own returned instructions — which for a
  card-taking processor means your card step again (see Defect 8).
- Keep a loop guard. Ours caps at five advances per session.
- A decline can arrive as an HTTP error *or* as a 200 with a failed status.
  Handle routing on both paths, and on `wallet_topup_status` when the customer
  returns from a hosted page.
- While CRM deployments are staggered, an older build answers the charge without
  routing but still carries it on the intent, so fall back to reading
  `wallet_topup_status` when the error payload has none.

**Read the mode defensively.** Deployments differ. We infer a usable `mode` when
it is missing: an `options` object means options, `redirect_url` means
`hpp_redirect`, `redirect` means `hosted_redirect` (a self-posting form rather
than a plain redirect). `direct_card` mode with a `crm_card_form_url` means the
CRM hosts the card form and you redirect to it rather than collecting fields.

**3DS comes back from the charge, not the init.** `wallet_topup_charge` can
return `mode: 3ds_method` (render a hidden form posting `unique_id` and
`signature` to `action_url`) or `mode: 3ds_redirect` (send them to
`next_action_url`). Neither is an error.

## Checklist for your site

- [ ] Is your direct-card processor list a literal in the source? Move it to
      config.
- [ ] Does anything call `wallet_topup_init` on a page load, before the customer
      has committed to an amount? That is the probe. Remove it.
- [ ] Does a refused direct-card charge abandon the intent, or fall back to the
      hosted page on the same intent?
- [ ] Do the pay routes verify the URL's intent id against the session?
- [ ] Do you route on the country from the CRM customer record?
- [ ] Do you handle `routing.can_advance` / `resume_payload` on init failure?
- [ ] Test: browsing Add Funds creates zero intents. Paying creates exactly one.
- [ ] Then check the CRM for existing pending intents at a suspiciously round
      amount. Those are probe residue, never submitted and never charged, and
      they can be marked failed or abandoned.
- [ ] Do you ever start a hosted page for a processor that has none? Check what
      you do when direct card is unavailable on Worldpay or Z1.
- [ ] Do you read `options.hosted_checkout` as well as `options.hpp`?
- [ ] Do you read `direct_card.allowed` / `status` as well as `available` /
      `charge_url`? TRAXX is invisible to you if not.
- [ ] Does your processor allowlist veto the shapes it was never written for, or
      processors with no hosted fallback?
- [ ] Does a "direct card charging is only available for ..." refusal advance
      the routing session, when it should try that processor's hosted page?
- [ ] Do you advance on a *charge* decline (API 60), not just an init failure —
      on the error path, the 200-with-failed-status path, and on status?
- [ ] Does any CRM call fail silently? Grep for a caught `CRMError` that returns
      without logging.
- [ ] When you decide a processor's response is unusable, do you log what it
      advertised? You will need it, and URL values must stay out of the log.
- [ ] Does the customer get told why a second card form is being shown?

## Our commits

| Commit | Change |
| --- | --- |
| `0f823ab` | Direct-card processor list moved to `WALLET_DIRECT_CARD_PROCESSORS` |
| `4a075b2` | Per-country routing cache — superseded, do not copy this one |
| `bcbb384` | Two-step Add Funds; probe, cache and their env flags removed |
| `b80c08a` | API 60: advance the routing session from a charge decline |
| `7304b68` | Follow the flow the response advertises; stop assuming a hosted page |
| `214127a` | Log what a processor advertised when an advance dead-ends |
| `3e05b9a` | TRAXX's `allowed`/`status` and `hosted_checkout` shapes |
| `149ca92` | Config refusal uses the same processor's hosted page, not the rule |
