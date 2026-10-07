## LottosOnline website (Flask)

The LottosOnline.com website, rebuilt from the legacy PHP site onto the CRM. It runs on the same engine as the
Lotto Express website (CRM Public Website API v1, `/api/v1`) with a LottosOnline layer on top:

- `lo_routes.py`: every legacy URL (the URL contract), redirects, captured page content, sitemap, robots,
  tracking tags.
- `lo_lotteries.py`: the 19 lotteries, their slugs and CRM game codes.
- `lo_banners.py`, `lo_homescreen.py`: home carousel; Add to Home Screen and its free-ticket offer.
- `templates/lo/`, `static/brands/lottosonline/`: the LottosOnline design (Live Lottos design system, LottosOnline
  brand). `money.css` restyles the engine's cart, wallet and account pages.

### Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on Linux: source .venv/bin/activate
pip install -r requirements.txt
copy env.example .env           # then fill in the values (see Settings)
python app.py
```

Without a CRM key, set `CRM_FAKE=1` and `WEBSITE_ENV=local` in `.env` to use the local stand-in CRM
(`fake_crm.py`; it refuses to run anywhere else). Tests: `python -m pytest -q`.

### Deploy (Linux): gunicorn + systemd behind Azure Front Door

The IT team owns Azure Front Door. The origin is this app behind gunicorn (and nginx if the server uses it).

1. **Code and Python**
   ```bash
   sudo mkdir -p /opt/lottosonline-website && cd /opt/lottosonline-website
   sudo git clone https://github.com/kevansx/websitelo.git .
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   mkdir -p data            # writable by the service user: CRM cache and home-screen claims live here
   cp env.example .env      # fill in; never commit .env
   ```
2. **systemd** `/etc/systemd/system/lottosonline-website.service`
   ```ini
   [Unit]
   Description=LottosOnline website (gunicorn)
   After=network.target

   [Service]
   User=lottosonline
   WorkingDirectory=/opt/lottosonline-website
   EnvironmentFile=/opt/lottosonline-website/.env
   ExecStart=/opt/lottosonline-website/.venv/bin/gunicorn -w 2 --timeout 120 -b 127.0.0.1:${WEBSITE_PORT} app:app
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   Then `sudo systemctl daemon-reload && sudo systemctl enable --now lottosonline-website`.
3. **Health check** for the Front Door origin probe: `GET /health` returns 200.
4. **Nightly job (gift packs)**: a pack left sealed for 14 days opens itself and its gift is granted. Add to the
   service user's crontab (03:15 every night):
   ```
   15 3 * * * cd /opt/lottosonline-website && set -a && . ./.env && set +a && .venv/bin/flask --app app packs-auto-open
   ```
5. **Jackpot alerts (every 30 minutes)**:
   ```
   */30 * * * * cd /opt/lottosonline-website && set -a && . ./.env && set +a && .venv/bin/flask --app app jackpot-alerts
   ```
   Push needs a VAPID key pair in `.env`: run `.venv/bin/flask --app app push-keys` once and paste the three lines
   it prints into `.env`. Keep `LO_VAPID_PRIVATE_KEY` secret and never change the pair once customers subscribe
   (a new pair silently breaks every existing subscription).
6. **Memberships and cart reminders**: two more jobs in the same crontab:
   ```
   5 * * * * cd /opt/lottosonline-website && set -a && . ./.env && set +a && .venv/bin/flask --app app membership-emails
   */10 * * * * cd /opt/lottosonline-website && set -a && . ./.env && set +a && .venv/bin/flask --app app abandoned-checkout
   ```
   Emails go out over SMTP when `SMTP_HOST` is set (see Settings); until then every email is written to
   `data/outbox/` instead, so nothing is sent by accident and nothing is lost.
7. **Update**: `cd /opt/lottosonline-website && git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart lottosonline-website`

#### What Front Door must do (for the IT team)

- **Forward** `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` (the app trusts one proxy hop), so
  canonical tags, redirects and payment return URLs use `https://www.lottosonline.com`.
- **Set `X-Geo-Country`** on every request, overwriting any value the visitor sent. Country blocks depend on it
  (the header name is the `GEO_COUNTRY_HEADER` setting).
- **Caching**: static files are served from content-hashed paths (`/assets/lo/<hash>/...`, `/assets/engine/<hash>/...`),
  so they can be cached for a long time, and ignoring query strings is safe. Do not cache HTML, `/cart`,
  `/checkout`, `/wallet`, `/account`, `/login` or any response that sets a session cookie.
- **No edge redirects for old URLs**: the app answers every legacy URL itself (301s included) from the URL
  contract. Edge rules on top risk redirect chains and lost rankings. The old Cloudflare rules are not needed.

### Settings

See `env.example`. The ones that matter at launch:

| Setting | Purpose |
|---|---|
| `CRM_BASE_URL`, `CRM_API_SERVICE_KEY` | The CRM and the **LottosOnline brand's** service key |
| `WEBSITE_SECRET_KEY` | A new long random value for this site only |
| `WEBSITE_ENV=production` | Turns on the tracking tags (GTM, Mixpanel, Facebook, Zendesk); they stay off everywhere else |
| `CRM_CACHE_DB_PATH` | `/opt/lottosonline-website/data/crm_cache.sqlite` |
| `WEBSITE_NOINDEX=1` | Hides the site from search engines. Not needed on `www1.` / `staging.` and other lottosonline.com test hosts: they are hidden automatically. Never set it on www |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | The email sender for membership, jackpot-alert, withdrawal and cart emails (SendGrid: `smtp.sendgrid.net`, 587, user `apikey`) |
| `LO_SITE_URL`, `LO_ASSET_URL` | Address used for links in emails (default `https://www.lottosonline.com`) and for the email logo (defaults to `LO_SITE_URL`; set `https://www1.lottosonline.com` until the new site is live on www) |
| `LO_SUPPORT_EMAIL` | Where withdrawal requests go (default support@lottosonline.com, the help-desk inbox) |
| `LO_WITHDRAWALS_ON`, `LO_WITHDRAWAL_DAYS` | Switch the withdrawal form on (`1`) and the promised turnaround in working days. Leave off until support's payout process is agreed |
| `LO_HOMESCREEN_OFFER` | `0` switches the home-screen free-ticket offer off |
| `LO_HOMESCREEN_PRODUCT_CODE` | The CRM product for the free Australia Saturday Lotto line (auto-detected if blank) |
