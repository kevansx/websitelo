# Lotto Express — Page Inventory (excluding Results + Blog)

This file is the working inventory for migrating the legacy PHP site (`wwwroot/wwwroot/`) into the standalone Flask site (`lottoexpress-website/`).

## Legend
- **implemented**: Flask route exists and has a dedicated template that is intended to match legacy markup (may still need polish).
- **placeholder**: Flask route exists but renders generic `page.html` placeholder copy.
- **missing**: no Flask route yet (or legacy route would 404).
- **deferred**: intentionally excluded by current scope.

## Sources used
- Legacy sitemap: `wwwroot/wwwroot/sitemap.xml`
- Legacy pages: `wwwroot/wwwroot/*.php`, `wwwroot/wwwroot/wallet/*.php`, `wwwroot/wwwroot/lotteries/**/*.php`, `wwwroot/wwwroot/promotions/**/*.php`
- Flask routes: `lottoexpress-website/app.py`
- Flask templates: `lottoexpress-website/templates/*`

---

## Public core pages

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/` | `/index.php` | `wwwroot/wwwroot/index.php` | public | `app.py: home()` → `templates/home.html` | implemented | Homepage markup is ported. |
| `/catalog` | (legacy had lottery landing pages instead of a single catalog) | `wwwroot/wwwroot/lotteries/*.php` | public | `app.py: catalog()` → `templates/catalog.html` | implemented | Needs parity checks vs legacy navigation expectations. |
| `/play/<game_code>` | `/lotteries/<slug>` and `/lotteries/<slug>.php` | `wwwroot/wwwroot/lotteries/**/*.php` | public | `app.py: play()` → `templates/play.html` | implemented | Shared template; per-game content comes from `templates/content/lottery_*`. |
| `/offer/<bundle_slug>` | `/promotions/<slug>` and `/promotions/<slug>.php` | `wwwroot/wwwroot/promotions/**/*.php` | public | `app.py: offer()` → `templates/offer.html` | implemented | Requires completing promo slug → bundle mapping. |
| `/lotteries/promotions` | `/lotteries/promotions` and `/lotteries/promotions.php` | `wwwroot/wwwroot/lotteries/promotions.php` | public | `app.py: promotions_index()` → `templates/promotions_index.html` | implemented | CRM-driven banners. |
| `/health` | (legacy `health.html`) | `wwwroot/wwwroot/health.html` | public | `app.py: health()` | implemented | Used for uptime checks. |

---

## Public static/info pages (currently placeholder in Flask)

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/about` | `/about-us` `/about-us.php` | `wwwroot/wwwroot/about-us.php` | public | `app.py: about()` → `templates/page.html` | placeholder | Must port full legacy markup. |
| `/contact` | `/contact-us` `/contact-us.php` | `wwwroot/wwwroot/contact-us.php` | public | `app.py: contact()` → `templates/page.html` | placeholder | Must port full legacy markup + contact form handling strategy. |
| `/faq` | `/faq` `/faq.php` | `wwwroot/wwwroot/faq.php` | public | `app.py: faq()` → `templates/page.html` | placeholder | Must port full legacy markup. |
| `/terms` | `/terms-and-conditions.php` | `wwwroot/wwwroot/terms-and-conditions.php` | public | `app.py: terms()` → `templates/page.html` | placeholder | Must port full legacy markup. |
| `/privacy` | `/privacy-policy.php` `/privacy-policy-au.php` `/privacy-policy-world.php` | `wwwroot/wwwroot/privacy-policy*.php` | public | `app.py: privacy()` → `templates/page.html` | placeholder | Must port full legacy markup and keep variants (world/AU) if required. |
| `/responsible-gaming` | `/responsible-gaming.php` | `wwwroot/wwwroot/responsible-gaming.php` | public | (none yet) | missing | In sitemap; must be added. |
| `/identity-verification-info` | `/identity-verification-info.php` | `wwwroot/wwwroot/identity-verification-info.php` | public | (none yet) | missing | In sitemap; must be added. |
| (404 handler) | `/404-page.php` | `wwwroot/wwwroot/404-page.php` | public | (none yet) | missing | Implement Flask 404 page + legacy `/404-page.php` route. |
| `/sitemap.xml` | `/sitemap.xml` | `wwwroot/wwwroot/sitemap.xml` | public | (none yet) | missing | Serve legacy sitemap (or generate). |

---

## Auth pages

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/login` | `/login.php` | `wwwroot/wwwroot/login.php` | public | `app.py: login()` → `templates/login.html` | implemented | Ported to legacy markup/IDs so legacy CSS/JS applies. |
| `/register` | `/register.php` | `wwwroot/wwwroot/register.php` | public | `app.py: register()` → `templates/register.html` | implemented | Ported to legacy layout; some legacy JS intentionally avoided to not require reCAPTCHA locally. |
| `/logout` | `/logout.php` | `wwwroot/wwwroot/logout.php` | logged-in | `app.py: logout()` | implemented | |
| `/forgot-password` | (legacy used popup + `/resources/php_functions/forgot-password.php`) | `wwwroot/wwwroot/resources/php_functions/*` | public | (none yet) | missing | Implement with CRM password reset endpoints. |
| `/reset-password` | (legacy `set-password.php`) | `wwwroot/wwwroot/set-password.php` | public | (none yet) | missing | Implement token-based reset using CRM endpoints; map legacy URL. |

---

## Cart / checkout

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/cart` | (legacy shopping cart pages were PHP) | `wwwroot/wwwroot/resources/php_functions/api/*` | logged-in | `app.py: cart()` → `templates/cart.html` | implemented | Uses CRM quote; UI parity still needs audit. |
| `/checkout` (POST) | (legacy checkout PHP endpoints) | `wwwroot/wwwroot/resources/php_functions/*` | logged-in | `app.py: checkout_submit()` | implemented | Uses `POST /api/v1/checkout/submit` when quote_id present. |

---

## Wallet journeys (logged-in)

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/wallet/topup` | `/wallet/add-funds.php` | `wwwroot/wwwroot/wallet/add-funds.php` | logged-in | `app.py: wallet_topup()` → `templates/wallet_topup.html` | implemented | |
| `/wallet/topup/return/<status>` | `/wallet/add-funds-success.php` `/wallet/add-funds-failed.php` | `wwwroot/wwwroot/wallet/add-funds-*.php` | logged-in | `app.py: wallet_topup_return()` → `templates/wallet_topup_return.html` | implemented | Legacy routes currently redirect to `status=success` placeholder. |
| (n/a) | `/wallet/confirm-order.php` | `wwwroot/wwwroot/wallet/confirm-order.php` | logged-in | (none yet) | missing | Must implement or redirect to modern equivalent. |
| (n/a) | `/wallet/order-placed.php` | `wwwroot/wwwroot/wallet/order-placed.php` | logged-in | (none yet) | missing | Must implement or redirect to `/orders`. |
| (n/a) | `/wallet/confirm-syndicate.php` | `wwwroot/wwwroot/wallet/confirm-syndicate.php` | logged-in | (none yet) | missing | Syndicates likely deferred; still needs a safe UX path. |
| (n/a) | `/wallet/add-funds-for-promo.php` | `wwwroot/wwwroot/wallet/add-funds-for-promo.php` | logged-in | (none yet) | missing | Map to `/wallet/topup` with context if possible. |
| (n/a) | `/wallet/add-funds-for-purchase.php` | `wwwroot/wwwroot/wallet/add-funds-for-purchase.php` | logged-in | (none yet) | missing | Map to `/wallet/topup` and/or checkout continuation. |

---

## Orders (logged-in)

| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/orders` | (legacy was inside `account.php#orders`) | `wwwroot/wwwroot/account.php` | logged-in | `app.py: orders()` → `templates/orders.html` | implemented | Needs parity vs legacy order list UI. |
| `/orders/<id>` | (legacy order detail inside account components) | `wwwroot/wwwroot/resources/page_components/account-page/*` | logged-in | `app.py: order_detail()` → `templates/order_detail.html` | implemented | Needs parity vs legacy order detail UI. |

---

## Account area (logged-in) — full legacy scope

Legacy `account.php` contains tabs + many accordion sections:\n- Profile\n- Communication Preferences\n- Password Change\n- Security Q&A\n- Limits\n- Self-Exclusion/Timeout/Close Account\n- Wallet: Withdrawal, Transaction History, Winnings, Transaction Summary\n- Orders: Order History, Transaction Summary\n\n| Canonical URL (Flask) | Legacy URL(s) | Legacy source | Auth | Flask route/template | Status | Notes |
|---|---|---|---:|---|---|---|
| `/account` | `/account.php` | `wwwroot/wwwroot/account.php` | logged-in | `app.py: account()` → `templates/account.html` | placeholder | Must replicate full legacy UI and wire CRM-supported endpoints; stub the rest. |

---

## Promotions inventory (legacy files)

These legacy files exist and must be mapped via `brand_config.py: legacy_promo_slug_to_bundle_slug`:\n- `wwwroot/wwwroot/promotions/specialoffer1.php` … `specialoffer5.php`\n- `wwwroot/wwwroot/promotions/American-Mega-Millions-with-Free-Play_zkadq.php`\n- and many historical files under `wwwroot/wwwroot/promotions/old/`.\n\n**Status**: currently **missing** mappings (Flask will 404 unknown promo slugs).\n+
---

## Deferred (current scope)
- Results pages: `/lottery-results/*`, `/results*` (excluded)\n- Blog: `/blog/*` (excluded)\n+
