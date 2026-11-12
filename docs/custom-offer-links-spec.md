# Custom offer links: a supervisor-made offer for an agent, paid from one link

**For:** the CRM team and the Lotto Express / Winnow Lotto website teams
**From:** Joey (owner) · Marketing Module
**Version:** 2 (12 Nov 2026), which replaces version 1
**Brands in version 2:** Lotto Express and Winnow Lotto. Lottos Online will follow once its new site is live.

> ### What changed since version 1
> Nothing from version 1 is removed. Version 2 adds:
> 1. **How the payment is taken** (new section 6). In short: exactly like the existing
>    top-up, with nothing new added to the payment itself. The one thing to get right is
>    passing the customer's own IP and browser details through, not our server's.
> 2. **Checks when the offer is created** (section 3.3). An offer that can't be paid is
>    refused at creation, not discovered by the customer.
> 3. **Full tracking** (new section 8). There's one new table, `custom_offer_events`, and
>    one new endpoint, 5.4. With them, every view, button press, browser problem, payment
>    step and refusal is recorded against the offer.
> 4. **A request id on every call** (5.0), so one failure can be traced across the
>    website, the CRM and the processor.
> 5. **A return page that checks the payment** rather than guessing (5.1 `payment`
>    block, section 7).
> 6. **"Call me back" on the page** when a payment fails (section 7).
> 7. More acceptance tests (17 to 30).

---

## 1. Why we are doing this

Today's agent payment links fail too often, and taking an agent's deal to a payment
has too many steps. Each step is a place it can break:

- set-password tokens,
- the login screen,
- tracking parameters,
- pre-built offers that marketing has to create first.

The new flow removes all of them. **A supervisor types what was agreed and the
amount, picks the agent who gets the sale, presses Send, and the customer opens a
page that shows that offer and a Pay button.** That's it.

We also need to know **exactly** why a link didn't turn into a payment. "The link
failed" isn't an answer. Section 8 makes every step visible.

> **Version 1: supervisors only.** Only supervisors can create offers, and they must
> choose which agent the sale is attributed to. Build this as a permission
> (`custom_offers.create`) so agents can be given it later without a release (see section 3).

### Design rules (please keep to these)

1. **The link carries nothing but a random code.**
   - No customer id, email, token, password or tracking parameter.
   - The code is the only thing that ties the payment to the customer, the agent and the offer.
2. **No login.**
   - The page never asks the customer to sign in or set a password.
   - It never shows account details.
3. **The money goes to that customer's wallet**, whoever opens the link. A
   forwarded link can only ever add credit to the right customer's account.
4. **Reuse what already works.**
   - Payment uses the existing CRM wallet top-up and processor routing.
   - Email uses the Marketing Module's existing promo email send.
   - No new payment integration.
5. **The payment is the existing top-up, unchanged** (section 6). The offer page only
   hands over to it, and never handles card data.
6. **Record everything, show nothing sensitive.** Every step is written to
   `custom_offer_events`, but no card data, password or full email ever goes in it.
7. **Fail loudly and plainly.**
   - Every error the customer can see has a clear message, a reference and a way to
     contact us.
   - Every error the agent can see is written to be read out on the phone.

---

## 2. The flow at a glance

```
Supervisor (CRM customer screen)
  │  1. "New offer": description + amount + attributed agent  →  pre-flight checks (3.3)  →  Create
  ▼
CRM  ── creates offer row, code = random 22 chars ──►  link: https://lottoexpress.com/o/<code>
  │  2. Send (email) / WhatsApp / Copy                              [event: sent_email / whatsapp_clicked / link_copied]
  ▼
Customer opens https://lottoexpress.com/o/<code>                    [event: viewed + device data]
  │  3. Website asks CRM: GET offer by code (5.1)
  │  4. Customer presses Pay → website asks CRM to start the payment (5.2)   [event: pay_clicked / pay_started / pay_refused]
  ▼
The existing top-up payment flow for that processor, exactly as the website checkout uses it
  │                                                                  [events from CRM: pay_started, processor_answer, 3ds_result]
  ▼
Back to https://lottoexpress.com/o/<code>/done → CRM checks the real status (5.1 payment block)
  │  5. Success webhook (existing) → wallet credited → offer PAID    [event: paid]
  ▼
Attributed agent (and the supervisor who created it) alerted "Offer paid"
  →  the tickets are placed from the wallet, credited to the attributed agent   [event: fulfilled]
```

---

## 3. What the supervisor sees (CRM)

### 3.1 Who can create offers

- **Version 1: supervisors only.** Gate the panel behind a permission
  `custom_offers.create`, given to the supervisor role (and admins) only.
- Users without the permission don't see the **New offer** form. They do see the
  list of the customer's offers (read-only) so an agent knows a link was sent.
- The server checks the permission on create, not just the screen.
- Later, giving agents the permission should need no code change. When an agent
  has it, the **Attributed agent** field defaults to themselves.

### 3.2 The panel

On the customer screen, a **Custom offer** panel:

| Field | Rules |
|---|---|
| **Attributed agent** | Required. A dropdown of active agents on this brand; no default for supervisors, so they must pick one. Default it to the customer's current owner if there is one, highlighted so the supervisor confirms it. This agent gets the sale (section 9). Can't be changed after the offer is created; to change it, cancel and create a new one. |
| **Description** | Required. 5–500 characters. Plain text. Shown to the customer exactly as typed, e.g. *"Powerball, 10 lines for the next 4 draws"*. |
| **Amount** | Required. Always in the **customer's wallet currency**, which is shown next to the box and can't be changed. Minimum 10.00. **No maximum in version 1.** Build the check against an optional setting `CUSTOM_OFFER_MAX_AMOUNT` (per currency, empty = no limit), so a limit can be switched on later without a release. |
| **Create** | Runs the checks in 3.3, then creates the offer and shows the link with three buttons: **Send email**, **WhatsApp**, **Copy link**. |

Below the panel is a list of this customer's custom offers. Each row shows:
- status (Open, Paid, Expired, Cancelled),
- amount,
- attributed agent,
- created by (the supervisor),
- created at and paid at,
- the **last thing that happened**, taken from `custom_offer_events`, e.g.
  *"Opened 2 times, Pay pressed, declined: insufficient funds"*;
- a **Cancel** button on Open offers.

**One open offer per customer per amount, description and attributed agent.** Creating an identical
one while the first is still open returns the existing link instead of making a
second. This absorbs double-clicks and timeouts.

### 3.3 Checks before the offer is created (new)

The most frustrating failure is an offer that could never have been paid. Check these
on **Create**, and refuse with the sentence shown, written to be read out:

| Check | If it fails, the supervisor reads |
|---|---|
| The customer's account is active (not closed, blocked, self-excluded or on a time-out) | *"This customer can't make payments right now (account status: {status})."* |
| A deposit limit wouldn't be exceeded by this amount | *"This amount is over the customer's deposit limit. The most they can pay now is {x}."* |
| A payment route exists for the customer's country and currency (the same routing the top-up uses; today some countries return `no_match`) | *"We have no card payment route for customers in {country} in {currency}, so this link couldn't be paid. Please tell a manager."* |
| The customer has a billing address with at least country, city, postcode and first line (the existing top-up sends it to the processor) | *"This customer has no full billing address. Add it first, so the bank can check the card."* Also offer an **Add address** shortcut. |
| An email (for Send email) or a mobile in international format (for WhatsApp) exists | The Send email / WhatsApp button is greyed out with the reason as its tooltip. Copy link always works. |

Every refusal is recorded as a `create_refused` event (section 8), so we can see how often each one happens.

### 3.4 Buttons

- **Send email.** The CRM server calls the Marketing Module (section 10). On success
  show *"Sent to them@example.com."* On failure show the returned `error` text exactly
  as it comes back.
  - Record `sent_email`, or `send_email_failed` with the error.
- **WhatsApp.** Opens `https://wa.me/<customer phone in international format>?text=<message>`
  in the supervisor's browser. Use this message:
  *"Here is the offer we just discussed: <link>"*
  - Nothing is sent by the system; the supervisor sends it from WhatsApp (or copies
    the link to the agent to send from theirs).
  - Record `whatsapp_clicked`.
- **Copy link.** Copies the link for SMS or chat. Record `link_copied`.

---

## 4. CRM data: two new tables per tenant schema

```sql
CREATE TABLE custom_offers (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  code             CHAR(22)     NOT NULL UNIQUE,   -- random, URL-safe, ≥128 bits (see §11)
  customer_id      BIGINT       NOT NULL,
  agent_user_id    BIGINT       NOT NULL,          -- the attributed agent = who gets the sale
  created_by_user_id BIGINT     NOT NULL,          -- the supervisor who created it (audit)
  description      VARCHAR(500) NOT NULL,
  amount_cents     INT          NOT NULL,
  currency         CHAR(3)      NOT NULL,          -- the customer's wallet currency at creation
  status           ENUM('open','paid','expired','cancelled') NOT NULL DEFAULT 'open',
  expires_at       DATETIME     NOT NULL,          -- created_at + 72 hours
  payment_intent_id BIGINT      NULL,              -- the intent that paid it
  paid_at          DATETIME     NULL,
  wallet_tx_id     BIGINT       NULL,              -- the credit it produced
  fulfilled_at     DATETIME     NULL,              -- agent has placed the tickets
  cancelled_by_user_id BIGINT   NULL,
  created_at       DATETIME     NOT NULL,
  updated_at       DATETIME     NOT NULL,
  KEY (customer_id), KEY (agent_user_id, created_at), KEY (status, expires_at)
);

-- New in version 2. Append-only: rows are never updated or deleted.
CREATE TABLE custom_offer_events (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  code          CHAR(22)     NOT NULL,             -- the offer (or the code that was tried, for unknown codes)
  customer_id   BIGINT       NULL,                 -- NULL only for unknown codes
  event         VARCHAR(40)  NOT NULL,             -- see the list in section 8.2
  occurred_at   DATETIME(3)  NOT NULL,             -- milliseconds, UTC
  source        ENUM('crm','website_server','browser','processor','mm') NOT NULL,
  request_id    VARCHAR(40)  NULL,                 -- see 5.0
  user_id       BIGINT       NULL,                 -- CRM user, for CRM-side events
  payment_intent_id BIGINT   NULL,
  processor     VARCHAR(40)  NULL,
  ip            VARCHAR(45)  NULL,                 -- the customer's real IP (browser/website events)
  user_agent    VARCHAR(500) NULL,
  detail_json   JSON         NULL,                 -- the event's facts (section 8.2); never card data
  KEY (code, occurred_at), KEY (customer_id, occurred_at), KEY (event, occurred_at), KEY (payment_intent_id)
);
```

- `payment_intents.metadata_json` gets `"custom_offer_code": "<code>"` and
  `"custom_offer_request_id": "<request id>"` on every intent started from an offer. That
  links each attempt back to its offer and to the exact page visit, including the
  failed ones.
- **Expiry** is 72 hours. It matches the call-centre attribution window.
  - A sweep, or a check on read, sets `status='expired'` after `expires_at`, and records `expired`.
  - A payment already in progress when the offer expires is still honoured (see section 9).

---

## 5. CRM API for the website (server-to-server)

These endpoints are called **only from the website's server**, with the existing
website→CRM credentials. They are never called from the browser.

### 5.0 On every call (new)

- **`X-Request-Id` header.** The website makes one id per page load (a UUID). It
  sends that id on every CRM call that page load causes, and prints it on any error
  the customer sees as *"Reference: ABC123"* (the first 6 characters).
- The CRM stores the request id on every event and on the intent metadata.
- **The customer's real details travel with every call** as `client_ip`,
  `user_agent` and `accept_language`. Read the IP from the edge (Cloudflare
  `CF-Connecting-IP`, else the first `X-Forwarded-For`), never the website server's
  own IP.
- **Timeouts.** The website waits at most 10 seconds for 5.1 and 25 seconds for 5.2.
  - On a timeout it shows the error page with the reference.
  - It records `crm_unreachable` through 5.4 once the CRM answers again. Until then it
    keeps the event in its own log and retries.

### 5.1 Read an offer

```
GET /api/v1/custom-offers/{code}?view=page|done|poll
```

- `view=page`: records `viewed`.
- `view=done`: records `done_viewed`.
- `view=poll`: records nothing; used by the done page while it waits.

```jsonc
// 200
{
  "ok": true,
  "status": "open",            // open | paid | expired | cancelled
  "description": "Powerball, 10 lines for the next 4 draws",
  "amount_cents": 15000,
  "currency": "USD",
  "charge": { "amount_cents": 15000, "currency": "USD" },  // what the card is actually charged, if FX applies
  "statement_descriptor": "LOTTOEXPRESS",                  // what the bank statement will show
  "first_name": "Ahmed",       // first name only, for "Hi Ahmed". Nothing else about the customer.
  "expires_at": "2026-11-15T14:00:00Z",
  "payment": {                 // new: the latest attempt for this offer, or null
    "state": "declined",       // none | in_progress | succeeded | declined | failed_technical
    "category": "insufficient_funds",   // see 7.3; null unless declined
    "customer_message": "Your bank declined the payment because of insufficient funds. You have not been charged.",
    "can_retry": true            // whatever the CRM's existing payment rules allow
  }
}
// 404 { "ok": false } for an unknown code. The same response whatever the reason, so codes can't be probed.
```

On `view=done` and `view=poll`, if the latest intent is still pending, **the CRM asks the
processor for the status** before answering, using the existing status checks (the
ones the pending sweeps use today). It does this at most once every 10 seconds per
intent. That way the done page reports the real result instead of waiting for a webhook.

### 5.2 Start payment

```
POST /api/v1/custom-offers/{code}/pay
{ "return_url": "https://lottoexpress.com/o/{code}/done",
  "client_ip": "…", "user_agent": "…", "accept_language": "…"
  // plus anything else the existing website checkout already sends to start a top-up
}
```

- **Refuses** unless `status = 'open'` and the offer hasn't expired. Each refusal is
  recorded as `pay_refused` with its reason.
- **Creates a wallet top-up payment intent** for `customer_id`, using the offer's
  amount and currency, through the **existing top-up and processor routing**. That
  routing's existing retry, cascading and duplicate-payment handling applies unchanged.
  - It tags `metadata_json` with `custom_offer_code` and `custom_offer_request_id`.
- **Returns** exactly what the existing top-up returns, so the website continues the
  same way its checkout does today (section 6):

```jsonc
{ "ok": true, "next": { …whatever the existing top-up returns… } }
{ "ok": false, "error": "This offer has already been paid. Thank you!" }
```

**A declined or abandoned payment leaves the offer `open`.** The customer can press Pay
again, as far as the CRM's existing payment rules allow. Nothing about the link changes
between attempts.

### 5.3 When a payment succeeds (existing webhook)

When the existing top-up success webhook completes an intent carrying
`custom_offer_code`, **in the same transaction**:

1. Credit the wallet (existing behaviour).
2. Set the offer to `status='paid'`, filling in `paid_at`, `payment_intent_id` and `wallet_tx_id`.
3. Record `paid`.
4. Raise an **"Offer paid"** alert or task for `agent_user_id`, copied to `created_by_user_id`:
   *"<customer> paid <amount> for: <description>. Place the tickets."*

If the offer was already `paid` by another intent (a rare double payment), still
credit the wallet. Don't mark the offer twice. Record `double_payment` and raise a
supervisor alert, so the extra payment can be refunded or used, as the customer prefers.

Every webhook for an offer's intent, successful or not, also records
`processor_webhook` (section 8.2), including webhooks that fail to process.

### 5.4 Record page events (new)

```
POST /api/v1/custom-offers/{code}/events
{ "request_id": "…", "client_ip": "…", "user_agent": "…",
  "events": [ { "event": "pay_clicked", "at": "2026-11-12T14:03:22.120Z", "detail": { … } }, … ] }
```

- The website server relays browser events here. The browser never calls the CRM.
- Up to 50 events per call.
- The CRM accepts only the browser events listed in 8.2, and drops any field not
  listed for that event, so nothing unexpected can be stored.
- Unknown codes are accepted and stored with `customer_id = NULL`. That shows mistyped or
  truncated links, which is a real failure we want to see. They're still rate-limited
  (section 11).
- Always answers `{ "ok": true }` quickly. Recording must never slow down or break the page.

---

## 6. How the payment is taken (new)

**Exactly as the existing top-up does it.** The guiding principle is the fewest possible
points of failure, so the offer link adds nothing new to the payment:

- **The same flow for each processor** that the website checkout uses today: the same
  pages, the same card form, the same bank security checks (3DS) and the same data sent.
  The CRM's existing routing chooses the processor and handles retries exactly as it does now.
- **The offer page only hands over.** It continues the way the existing checkout does
  with whatever 5.2 returns. If the checkout loads anything for a processor (for example
  a processor's fraud-check script), the offer page does the same, and nothing more.
- **It never handles card data.** Card details are only ever entered on the existing
  payment pages. They never pass through, and are never logged by, the `/o/` page or the
  website server.

**The one thing to get right.** Because the website calls the CRM server-to-server, the
processor could end up seeing our server as the customer. That is a common cause of
fraud declines. So 5.0 and 5.2 pass the customer's own IP, user agent and language, and
the CRM must use those wherever the existing top-up would have used the browser's.
Acceptance test 20 checks this.

Everything else that affects approval rates (3DS settings, retries, cascading,
duplicate-payment protection, what each processor is sent) stays with the CRM's
existing payment setup. Changes to any of it belong in the separate payments plan, so
offer payments and normal top-ups never behave differently.

---

## 7. Website: one new page per brand

**Routes:** `GET /o/{code}` and `GET /o/{code}/done`, on https://lottoexpress.com and https://winnowlotto.com.

### 7.1 The offer page

- **Server-side:** call 5.1 (`view=page`) and render.
  - No login, no cookies needed, no tracking parameters read or written.
  - The page must work in a fresh browser, inside WhatsApp's, Instagram's and
    Facebook's in-app browsers, and on a slow phone.
  - Keep it under 150 KB, with no web fonts that block rendering.
- **Content:**
  - logo,
  - *"Hi {first_name}, here is the offer we discussed"*,
  - the description,
  - the amount (big, with currency). If `charge` differs, add *"Your card will be
    charged {charge}."*,
  - one **Pay {amount}** button,
  - the cards accepted,
  - *"This will show on your statement as {statement_descriptor}."*,
  - a short line: *"Paying adds {amount} to your {brand} account; your agent will
    place your tickets."*,
  - a contact line (phone / WhatsApp / email),
  - a small **"Ask us to call you"** link.
- **Pay:**
  - Disable the button on the first press and show "Connecting to secure payment…".
  - Call 5.2 server-side, then continue exactly as the existing checkout does with
    what it returns (section 6).
  - If 5.2 refuses, show its `error` and the reference.

### 7.2 The return page

**`/o/{code}/done`:** call 5.1 with `view=done` and show the result of `payment.state`.

| `payment.state` | What the page shows |
|---|---|
| `succeeded`, or offer `paid` | *"Payment received, thank you. {agent first name or 'Your agent'} will confirm your tickets shortly."* |
| `in_progress` | *"Checking your payment with your bank…"* with a spinner. Poll 5.1 with `view=poll` every 3 seconds for up to 60 seconds. If it is still in progress after that: *"Your bank hasn't confirmed yet. We'll let you know as soon as it's confirmed."* Show no Pay button. |
| `declined` or `failed_technical` | The `customer_message`, *"You have not been charged"*, then: a **Try again** button if `can_retry`, otherwise **Ask us to call you**; the contact line; the reference. |

**Never trust the processor's return parameters** for the result. Only 5.1 says what happened.

### 7.3 What the customer is told when it fails

The CRM returns `category` and `customer_message`. Use these words:

| Category | Customer message |
|---|---|
| `insufficient_funds` | "Your bank declined the payment because of insufficient funds. You have not been charged." |
| `limit_exceeded` | "This payment is over a limit on your card. Your bank can raise it, or you can try another card." |
| `do_not_honor` | "Your bank didn't approve this payment. A quick call to your bank usually fixes it, or you can try another card." |
| `3ds_failed` | "The security check with your bank wasn't completed. Please try again and finish the check in your banking app or by text code." |
| `card_details` | "Some card details didn't match. Please check the card number, expiry date and security code." |
| `card_blocked` | "Your bank couldn't approve this card for this payment. Please try a different card, or ask us to call you." |
| `technical` | "Something went wrong connecting to the payment provider. You have not been charged. Please try again in a minute." |

### 7.4 Other states, and what the page loads

- **Other statuses on `/o/{code}`:**
  - `paid`: show the thank-you text, no Pay button.
  - `expired` or `cancelled`: *"This offer is no longer available. Please contact us
    and we'll send you a new one,"* plus the contact line and **Ask us to call you**.
  - Unknown code: the same page as expired.
- **"Ask us to call you"** posts a `callback_requested` event, then shows *"Thanks, we'll call
  you shortly."* The CRM raises an urgent task for the attributed agent, copied to the supervisor.
- `noindex, nofollow`. The page isn't linked from anywhere on the site.
- **What the page loads:**
  - nothing third-party except what the existing checkout needs for the processor
    (section 6): no GA, pixel, chat widget, tag manager or font CDN;
  - a small first-party tracking script (section 8.3);
  - **never the full code in a third-party request**;
  - `Referrer-Policy: no-referrer`, so the code doesn't leak to the processor in the Referer header.

The page doesn't need the site's cart, product catalogue, offer rules or the
Marketing Module. It is a thin view over the CRM calls.

---

## 8. Tracking: knowing exactly what went wrong (new)

### 8.1 The rule

Every step from creation to tickets is one row in `custom_offer_events`. When a link
fails, someone reads its rows in order and can see where and why, without asking a
developer. The Marketing Module's **Payment links** page shows these rows as a timeline
for each link, next to the email events and the payment attempts.

### 8.2 The events

| Event | Source | `detail_json` (only these fields) |
|---|---|---|
| `created` | crm | amount, currency, agent_user_id |
| `create_refused` | crm | check (from 3.3), message. Recorded under the would-be code, or under `code = 'none'` with the customer_id |
| `sent_email` / `send_email_failed` | crm | error (as returned by the Module) |
| `whatsapp_clicked` / `link_copied` | crm | none |
| `cancelled` / `expired` | crm | by user_id, for cancelled |
| `viewed` | website_server | `first_view` (true/false), and how many views so far |
| `unknown_code_viewed` | website_server | the code length (truncated links show up as short codes) |
| `page_rendered` | browser | ms from navigation start to first render, in-app browser name if any (WhatsApp, Instagram, Facebook, TikTok, none), OS, browser and version, viewport, language, timezone, connection type (from `navigator.connection` where available), cookies enabled |
| `script_failed` | browser | which processor script failed to load, if the checkout uses one |
| `js_error` | browser | message (first 200 characters), source file, line. Never page content. |
| `pay_clicked` | browser | ms since page render |
| `pay_started` | crm | payment_intent_id, processor, routing rule, flow (hosted page / CRM card page), attempt number |
| `pay_refused` | crm | reason (e.g. not_open, expired, no_route, customer_blocked, or whatever the CRM's payment rules returned), plus the message shown |
| `redirected` | browser | the destination's host only (e.g. `pay.collectmoney.com`), never the full URL |
| `left_page` | browser | the last state seen (e.g. after `pay_clicked` but before `redirected`), sent with `sendBeacon` on `pagehide` |
| `returned` | website_server | which page (done) and the ms since `redirected` |
| `processor_answer` | crm | payment_intent_id, processor, state, category (7.3), code, message |
| `3ds_result` | crm | recorded only, where the processor reports it: frictionless / challenged / failed / not attempted |
| `cascaded` | crm | from processor, to processor, when the existing routing moves a payment on (recorded only, no new rules) |
| `processor_webhook` | processor | payment_intent_id, processed_ok, error, status. No raw payload. |
| `status_checked` | crm | payment_intent_id, the answer from the processor's status API |
| `paid` / `double_payment` | crm | payment_intent_id, wallet_tx_id |
| `callback_requested` | browser | the page state at the time (e.g. "after 2 declines") |
| `crm_unreachable` | website_server | which call (5.1 / 5.2), timeout or HTTP status, ms waited |
| `fulfilled` | crm | order_id, placed by user_id |

### 8.3 The page's tracking script

The page has one small first-party script, about 2 KB inline, with no library:
- It queues the browser events above.
- It sends them with `navigator.sendBeacon` to `POST /o/{code}/t` on the website's own
  domain. The website server adds the IP and user agent and relays them to 5.4.
- It sends on `pagehide` too, so an abandoned page still reports its last state.
- It catches `window.onerror` and `unhandledrejection` for `js_error`, capped at 5 per page load.
- It never reads form fields, the URL query or anything typed.

### 8.4 What is never recorded

- card numbers, CVVs or expiry dates;
- passwords or tokens;
- the full customer email;
- the free-text of anything typed on the processor's page;
- raw processor payloads (only the fields listed above).

The customer's IP and user agent are recorded, as they already are for logins and payments.

---

## 9. Attribution and the agent's sale

- **The code is the attribution.** The offer row already holds the customer and the
  attributed agent the supervisor chose, so no URL parameter, cookie or tracking id is
  involved anywhere.
- **What counts as the agent's sale is the tickets.** They're placed from the
  wallet as an ordinary agent order, which today's rules already count as that
  agent's sale:
  - `entered_on_behalf_of_user_id` = the attributed agent (`custom_offers.agent_user_id`),
    whoever actually places the order; `created_by_user_id` = whoever placed it;
  - also set `sale_source = 'custom_offer'`;
  - and store the code on the order (new nullable column `custom_offer_code`).

  **Why the tickets and not the top-up:** a wallet top-up isn't a sale in any of
  today's reports. Counting both would count the same money twice.
- **Paid but not yet played.** The CRM keeps a **"Paid offers to place"** queue:
  - offers with `status='paid' AND fulfilled_at IS NULL`, shown to the attributed
    agent and to the creating supervisor;
  - it escalates to the supervisor team after 24 hours;
  - `fulfilled_at` is set when an order carrying the code is placed.

  This makes sure money a customer paid never sits unplayed.
- **The attributed agent gets the sale**, never the supervisor who created the offer,
  and even if someone else places the tickets. When an order carries the code, the CRM
  fills `entered_on_behalf_of_user_id` from `agent_user_id` itself; don't rely on the
  person placing it to pick the agent again.
- **Late payment.** A payment started before `expires_at` and completed after it still
  counts and still marks the offer paid. A payment can't be *started* after expiry.

---

## 10. Marketing Module: the email and the reporting (we build this)

```
POST {MM_BASE_URL}/api/service/custom-offers/send
X-MM-API-Key: <the existing promo key>
{ "brand": "lottoexpress", "customer_id": 12345, "code": "<code>",
  "description": "…", "amount_cents": 15000, "currency": "USD",
  "agent": "47", "agent_name": "Priya", "created_by": "12" }
```

This uses the existing promo send, with the same key, opt-out checks, duplicate absorption
(an identical send within 3 minutes is answered `ok: true, duplicate: true`) and
read-aloud `error` messages as https://mkt.cloudandahalf.com/api/service.

- **The email's button is exactly `https://<brand site>/o/<code>`.** Nothing is
  appended to it, and click tracking is off for it, so the link isn't wrapped in a redirect.
- **No set-password token** is ever included.
- `agent` / `agent_name` are the **attributed agent** (the email is signed by them);
  `created_by` is the supervisor.
- The Module checks the code against `custom_offers` (right customer, still open) and
  logs every send attempt, whatever the outcome.

**Reporting.** This is already built and live in the Module for bundle links, and it
picks up custom offers as soon as the tables exist:
- **Payment links** (https://mkt.cloudandahalf.com/v2/brand/payment-links) lists every link
  and every failed send per brand, with where each one stopped and a full timeline
  per link.
- A **Custom offers** summary by attributed agent (filterable by supervisor) shows:
  created, sent, opened, Pay pressed, paid, amount paid, placed, and time from
  creation to payment.
- It also shows **where links stop**, broken down by in-app browser, country, processor
  and decline category.

---

## 11. Security and safety

- **Code generation.** A cryptographic random generator, 22 URL-safe characters
  (≈131 bits). Never derived from ids or times.
- **Rate limits.**
  - Rate-limit `GET /o/{code}`, `/o/{code}/t` and 5.1 per IP (for example 30 a minute);
    unknown codes count double.
  - 5.4 accepts at most 200 events per code per hour.
- **What the page reveals.** The first name, the description, the amount and the
  statement descriptor. No surname, email, phone, balance, address or card.
- **A forwarded link** can only credit the original customer's wallet. Our existing
  chargeback and fraud checks on top-ups apply unchanged, because the payment *is* a
  top-up.
- **Who can create.** Only users with `custom_offers.create` (supervisors in version 1),
  checked on the server.
- **Who can cancel.** Only supervisors. A cancelled offer can't be paid; a payment
  already in progress is handled as late payment (section 9).
- **Amount limits.** None in version 1. The optional `CUSTOM_OFFER_MAX_AMOUNT`
  setting (per currency, empty = no limit) lets one be added later without a release.
- **Card data.** None on the offer page, the website server or in any event (6, 8.4).

---

## 12. Acceptance tests (both teams sign off on all of these)

| # | Do this | Expect |
|---|---|---|
| 1 | Supervisor creates an offer: 150.00, "PB 10 lines × 4 draws", attributed to agent A | Link `https://<site>/o/<22 chars>`; listed as Open, 72-hour expiry, agent A and the supervisor shown; `created` event |
| 1a | An agent (no `custom_offers.create`) opens the customer screen, and also calls the create endpoint directly | No New offer form; list is read-only; the direct call is refused |
| 1b | Supervisor tries to create without picking an agent | Refused: "Choose the agent who gets this sale." |
| 2 | Create the identical offer again while it is open | Same link returned, no second row |
| 3 | Open the link in a private window on a phone | Offer page shows the first name, description, amount and statement descriptor. No login prompt. `viewed` and `page_rendered` events. |
| 4 | Open it inside WhatsApp's in-app browser, then Instagram's | Same as 3, and Pay works end to end, including the bank's security check where one appears; `page_rendered` names the in-app browser |
| 5 | Pay with a test card that is declined for insufficient funds | Done page shows the insufficient-funds message, "not charged", Try again; offer still Open; `processor_answer` with category `insufficient_funds` |
| 6 | Try again with a card that goes through | Wallet +150.00; offer Paid; alert raised to agent A and the supervisor; done page says thank you; `paid` event |
| 7 | Open the link again after paying | Thank-you state, no Pay button |
| 8 | Agent B (or the supervisor) places the tickets from the wallet with the code | Order has `sale_source='custom_offer'`, **agent A** as `entered_on_behalf_of_user_id`, the code stored; offer `fulfilled_at` set; leaves the queue; `fulfilled` event |
| 9 | An offer is paid and not placed within 24 hours | Supervisor escalation |
| 10 | The link after 72 hours, unpaid | "No longer available" page; 5.2 refuses; `pay_refused` reason `expired` |
| 11 | Supervisor cancels, then the customer opens the link | "No longer available" page |
| 12 | Unknown or mistyped code | Same page as 10; 5.1 returns the same 404; `unknown_code_viewed` recorded |
| 13 | Send email for a customer who has opted out | `ok:false`, the opt-out message shown to the agent as written; `send_email_failed` |
| 14 | Double-click Send email | One email; the second reply has `duplicate: true` |
| 15 | Amount 9.99, then a large amount (e.g. 5,000.00) with `CUSTOM_OFFER_MAX_AMOUNT` empty | 9.99 refused (minimum 10.00); 5,000.00 accepted |
| 16 | Agent sales report for the day | Includes the order from test 8 once, under agent A; nothing under agent B or the supervisor |
| 17 | Create an offer for a customer with no billing address | Refused with the 3.3 sentence and an Add address shortcut; `create_refused` |
| 18 | Create an offer for a customer in a country with no payment route | Refused with the no-route sentence; `create_refused` |
| 19 | Create an offer above the customer's deposit limit | Refused with the most they can pay; `create_refused` |
| 20 | Press Pay, then look at what the processor received (sandbox logs) | The customer's own IP and browser (not a server's), and otherwise exactly what a normal website top-up for the same customer sends |
| 21 | Press Pay, for each processor in the routing | The same payment pages and steps as a normal website top-up. The offer page's HTML and logs contain no card field. |
| 22 | Complete a payment whose webhook is delayed (sandbox delay) | The done page shows "Checking your payment…", then the right result within 60 seconds, from the CRM's status check; `status_checked` event |
| 23 | Pay twice successfully through two tabs (forced in the sandbox) | Both credited; offer marked paid once; `double_payment` and a supervisor alert |
| 24 | Press "Ask us to call you" | Thank-you text; urgent task for agent A, copied to the supervisor; `callback_requested` |
| 25 | Close the tab after pressing Pay but before the redirect | `left_page` recorded with the last state |
| 26 | Make the CRM unreachable, then open the link | Error page with a reference; `crm_unreachable` recorded once the CRM is back |
| 27 | Block any processor script the checkout loads | Pay still works as it does in the normal checkout; `script_failed` |
| 28 | Search every event for the test card number, CVV, the customer's email and any password | Not found anywhere |
| 29 | Look at the page's network requests | Only the site itself and what the existing checkout loads; no third-party request contains the code; `Referrer-Policy: no-referrer` |
| 30 | Open https://mkt.cloudandahalf.com/v2/brand/payment-links and click the test offer | The timeline shows every event from tests 3–8 in order, next to the email and payment attempts |

---

## 13. Who builds what

| Piece | Owner |
|---|---|
| `custom_offers` and `custom_offer_events` tables; the `custom_offers.create` permission (supervisors); the supervisor panel with Attributed agent; the pre-flight checks (3.3); Send / WhatsApp / Copy; Cancel; the Paid offers to place queue; alerts; callback tasks | CRM |
| Endpoints 5.1 (with the `payment` block and status checks), 5.2 (the existing top-up, with the customer's own IP and browser passed through), the webhook hook in 5.3, 5.4; the customer messages (7.3); `custom_offer_code` on orders; `sale_source='custom_offer'` | CRM |
| `/o/{code}`, `/o/{code}/done` and `/o/{code}/t`; request ids; handing over to the payment exactly as the checkout does; the tracking script (8.3); polling on the done page | Lotto Express and Winnow website teams |
| The email send endpoint (section 10, already built), the Payment links page (already built) and the Custom offers summary | Marketing Module |

**Done when** all 30 acceptance tests in section 12 pass. Build it all and release it once:
no phases and no partial releases to customers.

---

## 14. Settings to agree before go-live

| Setting | Proposed |
|---|---|
| `CUSTOM_OFFER_EXPIRY_HOURS` | 72 |
| `CUSTOM_OFFER_MIN_AMOUNT` | 10.00 in the wallet currency |
| `CUSTOM_OFFER_MAX_AMOUNT` | empty (no limit) for version 1 |
| Escalation if paid and not placed | 24 hours |
| Contact line on the page | each brand's support phone, WhatsApp and email |
| Statement descriptor shown on the page | each brand's descriptor, as the processors bill it |
