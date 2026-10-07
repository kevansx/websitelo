# LottosOnline emails

Built 7 October 2026 from the site's `lo_emails.py`. One file per email, in one shared LottosOnline layout.

## The files

- `html/<key>.html`: the template to load wherever the email is sent. Handlebars, the syntax SendGrid dynamic templates use (`{{name}}`, `{{#if}}`, `{{#each}}`). Links point at https://www.lottosonline.com.
- `preview/<key>.html`: the same email filled with sample data, to look at in a browser.
- `index.html`: every preview on one page.

The logo loads from https://www.lottosonline.com/static/brands/lottosonline/img/logo-on-dark.png, which exists once the new site is live on www. Until then it shows as the word LottosOnline; to use the files before the switch, change that one address to https://www1.lottosonline.com.

The site sends the ones marked "sent today" itself, from the same source. When the subject has `{{...}}` in it, paste it into the template's subject field as it is.

## Rules for every sender

- Never email customers in Denmark.
- "Marketing consent only" emails go only to customers who allow marketing email, and carry the preferences link (plus SendGrid's `{{{unsubscribe}}}` when a suppression group is used).
- `first_name` may be left out: greetings fall back to "Hi there".
- A list of balls is `[{"n": 7, "bonus": true, "hit": true}]`: `bonus` for the extra number (Powerball, Lucky Stars), `hit` for a number that matched the draw.

## Account

### Welcome (`welcome`)

- **Subject:** `Welcome to LottosOnline`
- **Preheader:** Your account is ready. Your first order comes with a gift pack.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** Account created (old site: welcome2).
- **Sent by:** Site or CRM
- **Data:** `email`, `first_name`, `homescreen_offer`, `set_password_url`

### Confirm email address (`verify_email`)

- **Subject:** `Confirm your email address`
- **Preheader:** One tap to confirm your email for LottosOnline.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** Account created, or the customer asks for a new link. Not on the old site.
- **Sent by:** CRM (the site calls its email-verification API)
- **Data:** `email`, `first_name`, `verify_url`

### Password reset (`password_reset`)

- **Subject:** `Reset your LottosOnline password`
- **Preheader:** Use this link to choose a new password.
- **From:** reminder@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The customer asks to reset their password (old site: reset_password2).
- **Sent by:** CRM (the site calls its password-reset API)
- **Data:** `email`, `expires_text`, `first_name`, `reset_url`

## Orders and money

### Order confirmation (`order_confirmation`)

- **Subject:** `{{#if is_renewal}}Your renewal is confirmed{{else}}Your order confirmation{{/if}}: {{order_ref}}`
- **Preheader:** Your entries are booked. Your ticket scans follow before the draw.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** An order is paid (old site: order_confirmation2). One template covers the old variants: no password set (set_password_url), automatic renewal (is_renewal), referred customer (referral_url not passed).
- **Sent by:** Site or CRM
- **Data:** `balance_used`, `descriptor`, `first_name`, `is_renewal`, `items`, `order_date`, `order_ref`, `pack_is_gold`, `pack_url`, `payment_method`, `referral_url`, `set_password_url`, `total`

### Funds added (`deposit_confirmation`)

- **Subject:** `LottosOnline deposit confirmation: {{deposit_ref}}`
- **Preheader:** Your funds are in your account and ready to play.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** A top-up to the account balance succeeds (old site: deposit_confirmation2).
- **Sent by:** Site or CRM
- **Data:** `amount`, `balance`, `continue_url`, `deposit_date`, `deposit_ref`, `descriptor`, `first_name`, `payment_method`

### Draw results (`results`)

- **Subject:** `Your {{lottery_name}} results for {{draw_date}}`
- **Preheader:** {{#if won}}You've won {{total_won}}. See your results.{{else}}Your numbers checked against the draw.{{/if}}
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** After each draw, to every customer with an entry in it (old site: result_email2, and result_email2lead when no password is set).
- **Sent by:** Site (needs draw results from the CRM) or CRM
- **Data:** `bonus_label`, `draw_date`, `first_name`, `jackpot_status`, `lines`, `lottery_name`, `next_draw_date`, `next_jackpot`, `play_url`, `referral_url`, `set_password_url`, `total_won`, `winning_balls`, `won`

### Winnings added (`winnings_paid`)

- **Subject:** `LottosOnline winnings: {{amount}} added to your account`
- **Preheader:** Your winnings are in your account.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** Winnings are credited to the customer's winnings balance (old site: deposit_winnings_confirmation).
- **Sent by:** Site (checks ticket statuses after each draw) or CRM
- **Data:** `amount`, `claim_note`, `draw_date`, `first_name`, `lottery_name`, `reference`, `winnings_balance`

### Withdrawal request received (`withdrawal_received`)

- **Subject:** `We've received your withdrawal request for {{amount}}`
- **Preheader:** Reference {{reference}}. We'll pay it within {{days}} working days.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The customer asks to withdraw winnings at /account/withdraw.
- **Sent by:** Site (lo_withdraw.py), sent today
- **Data:** `amount`, `days`, `first_name`, `method`, `reference`

### Withdrawal paid (`withdrawal_paid`)

- **Subject:** `Your withdrawal of {{amount}} has been paid`
- **Preheader:** Reference {{reference}}.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The team pays a withdrawal. Nothing sends this automatically yet: payouts are made by hand.
- **Sent by:** Team (send by hand when the payment is made) or CRM
- **Data:** `amount`, `first_name`, `method`, `paid_date`, `reference`

### Withdrawal request (to the team) (`withdrawal_request_staff`)

- **Subject:** `Withdrawal request {{reference}}: customer {{customer_id}}, {{amount}}`
- **Preheader:** Nothing has been paid or debited yet.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Internal (team)
- **When:** A customer asks to withdraw winnings. Goes to the support address.
- **Sent by:** Site (lo_withdraw.py), sent today
- **Data:** `amount`, `balance`, `customer_email`, `customer_id`, `customer_name`, `details`, `method`, `reference`

## Gift packs and offers

### Gift pack waiting (`pack_waiting`)

- **Subject:** `{{#if is_gold}}Your gold gift pack is waiting{{else}}Your gift pack is waiting{{/if}}`
- **Preheader:** Rip it open to reveal a free entry.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Marketing consent only
- **When:** A gift pack has been sealed for 3 days (packs open themselves after 14).
- **Sent by:** Site
- **Data:** `first_name`, `is_gold`, `opens_on`, `pack_url`, `unsubscribe`

### Gift pack opened for you (`pack_opened`)

- **Subject:** `We opened your gift pack: {{gift_title}}`
- **Preheader:** Your free entry is in your account.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** A gift pack left sealed for 14 days opens itself.
- **Sent by:** Site (nightly packs-auto-open job)
- **Data:** `first_name`, `gift_detail`, `gift_title`

### Free Saturday Lotto line added (`homescreen_free_line`)

- **Subject:** `Your free Saturday Lotto line is in`
- **Preheader:** Thanks for adding LottosOnline to your home screen.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The customer opens LottosOnline from their home screen while logged in, and the free line is granted.
- **Sent by:** Site (lo_homescreen.py, when the line is granted)
- **Data:** `draw_date`, `first_name`, `jackpot`

## Refer a friend

### Welcome, joined through a friend (`welcome_friend`)

- **Subject:** `Welcome to LottosOnline: {{referrer_first_name}} sent you`
- **Preheader:** Place your first order and you each get a gift pack.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** Account created through a friend's referral link (old site: welcome2referfriend).
- **Sent by:** Site or CRM
- **Data:** `first_name`, `referrer_first_name`, `set_password_url`

### Invitation from a friend (`refer_friend_invite`)

- **Subject:** `{{referrer_first_name}} is thinking of you`
- **Preheader:** Open your free LottosOnline account. You both get a gift pack.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Sent to a friend at a customer's request
- **When:** A customer sends their referral link to a friend by email (old site: refer_friend_invite).
- **Sent by:** Site, when a customer enters a friend's email
- **Data:** `invite_url`, `message`, `referrer_first_name`

### Friend reward (`referral_reward`)

- **Subject:** `{{#if is_referrer}}{{friend_first_name}} played: your gift pack is here{{else}}Your friend gift pack is here{{/if}}`
- **Preheader:** Rip it open to reveal a free entry.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** A referred friend's first paid order. Sent to both: the referrer (is_referrer) and the friend.
- **Sent by:** Site
- **Data:** `first_name`, `friend_first_name`, `is_referrer`, `pack_is_gold`, `pack_url`, `referral_url`, `referrer_first_name`

## Syndicates

### Syndicate joined (`syndicate_joined`)

- **Subject:** `You're in: {{syndicate_name}} syndicate, {{weekly_price}} a week`
- **Preheader:** 10 lines in every draw. Pause or cancel any time.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The customer joins a weekly syndicate.
- **Sent by:** Site (lo_members.py), sent today
- **Data:** `first_name`, `lines`, `next_payment`, `shares`, `syndicate_name`, `weekly_price`

### Syndicate renews tomorrow (`syndicate_renewal_due`)

- **Subject:** `Your {{syndicate_name}} syndicate renews tomorrow: {{weekly_price}}`
- **Preheader:** Nothing to do if you're happy to carry on.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The day before each weekly payment.
- **Sent by:** Site (lo_members.py), sent today
- **Data:** `cancel_url`, `first_name`, `renews_at`, `syndicate_name`, `weekly_price`

### Syndicate payment received (`syndicate_payment_received`)

- **Subject:** `Payment received: {{weekly_price}} for your {{syndicate_name}} syndicate`
- **Preheader:** You're in this week's draws.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** A weekly syndicate payment succeeds.
- **Sent by:** Site (lo_members.py), sent today
- **Data:** `first_name`, `next_payment`, `syndicate_name`, `weekly_price`

### Syndicate payment failed (`syndicate_payment_failed`)

- **Subject:** `We could not take your {{syndicate_name}} syndicate payment`
- **Preheader:** You're not in this week's draws until a payment goes through.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** A weekly syndicate payment fails.
- **Sent by:** Site (lo_members.py), sent today (day 0 and day 3)
- **Data:** `first_name`, `reason`, `syndicate_name`, `weekly_price`

### Syndicate cancelled (`syndicate_cancelled`)

- **Subject:** `Your {{syndicate_name}} syndicate membership is cancelled`
- **Preheader:** Nothing more will be taken.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Service (every customer)
- **When:** The customer cancels, or the membership ends.
- **Sent by:** Site (lo_members.py), sent today
- **Data:** `first_name`, `syndicate_name`

## Reminders and alerts

### Lines left in the cart (`cart_reminder`)

- **Subject:** `Your {{lottery_name}} lines are still in your cart`
- **Preheader:** Finish your order before the draw closes.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Marketing consent only
- **When:** 30 minutes after a logged-in customer leaves lines in the cart (no push device).
- **Sent by:** Site (lo_recover.py), sent today
- **Data:** `closes_at`, `first_name`, `lines`, `lottery_name`, `resume_url`, `unsubscribe`

### Last call for the cart (`cart_last_call`)

- **Subject:** `{{lottery_name}} closes {{closes_at}}`
- **Preheader:** Your lines are still waiting.
- **From:** confirmation@lottosonline.com
- **Who gets it:** Marketing consent only
- **When:** 24 hours after the first reminder, if the draw is still open. The last one for that cart.
- **Sent by:** Site (lo_recover.py), sent today
- **Data:** `closes_at`, `first_name`, `jackpot`, `lottery_name`, `resume_url`, `unsubscribe`

### Jackpot alert (`jackpot_alert`)

- **Subject:** `{{lottery_name}}: {{jackpot}}`
- **Preheader:** The jackpot you follow has passed {{threshold}}.
- **From:** alert@lottosonline.com
- **Who gets it:** Marketing consent only
- **When:** A jackpot the customer follows passes their chosen amount (push first; email if no push device).
- **Sent by:** Site (lo_alerts.py, every 30 minutes), sent today
- **Data:** `closes_at`, `jackpot`, `lottery_name`, `play_url`, `threshold`, `unsubscribe`
