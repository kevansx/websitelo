## Lotto Express Website (Flask)

Standalone Flask website repo for **Lotto Express**, backed by **CRM Public Website API v1** (`/api/v1`).

### Key goals
- **Isolated repo** (single-brand; no Winnow secrets reused)
- Uses **brand-scoped CRM service key** (`X-CRM-API-Key`) so CRM resolves the correct tenant/brand
- Preserves legacy Lotto Express URLs:
  - `/index.php`, `*.php` static pages
  - `/lotteries/<...>`, `/lottery-results/<...>`, `/promotions/<...>`
  - Wallet topup legacy redirects

### Local run
Create a `.env` (copy from `env.example`) and set:
- `CRM_BASE_URL`
- `CRM_API_SERVICE_KEY` (Lotto Express service key)
- `WEBSITE_SECRET_KEY` (new random secret for this repo)
- `WEBSITE_BRAND=lottoexpress`

Then:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Branding + legacy slug mapping
Edit `brand_config.py`:
- **logos/favicon**
- analytics IDs (or set `ANALYTICS_GTM_ID` / `ANALYTICS_GA4_ID` in env)
- mapping tables:
  - legacy lottery slugs → `game_code` (preferred) or `game_name` (fallback)
  - legacy results slugs → `game_code` (preferred) or `game_name` (fallback)
  - legacy promo slugs → `bundle_slug`

If a legacy lottery/results slug is not mapped, the website will attempt a best-effort resolution by calling `GET /api/v1/store/games` and matching by `game_name`.

### Deployment (Linux) – gunicorn + systemd + nginx
Recommended server layout (mirrors Winnow pattern):
- Code: `/opt/lottoexpress-website/`
- Venv: `/opt/lottoexpress-website/.venv/`
- Writable data: `/opt/lottoexpress-website/data/` (cache DB lives here)
- Env file: `/opt/lottoexpress-website/.env`

#### 1) Install + venv

```bash
sudo mkdir -p /opt/lottoexpress-website
sudo chown -R lottoexpress:lottoexpress /opt/lottoexpress-website

cd /opt/lottoexpress-website
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

#### 2) systemd unit
Create `/etc/systemd/system/lottoexpress-website.service`:

```ini
[Unit]
Description=Lotto Express Website (gunicorn)
After=network.target

[Service]
User=lottoexpress
Group=lottoexpress
WorkingDirectory=/opt/lottoexpress-website
EnvironmentFile=/opt/lottoexpress-website/.env
ExecStart=/opt/lottoexpress-website/.venv/bin/gunicorn -w 2 -b 127.0.0.1:${WEBSITE_PORT} app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lottoexpress-website
sudo systemctl status lottoexpress-website
```

#### 3) nginx reverse proxy + TLS
Example nginx server block (adjust domain + port):

```nginx
server {
  server_name lottoexpress.example.com;

  location / {
    proxy_pass http://127.0.0.1:8003;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

Use certbot to add HTTPS (Let’s Encrypt):
- Install certbot for nginx
- Run `certbot --nginx -d lottoexpress.example.com`

#### 4) Health check
- Website local health: `GET /health` returns 200
- CRM health: `GET /api/v1/health` on the CRM host

### CRM cache (Winnow-style)
This site uses a persistent SQLite cache (WAL mode) for outage tolerance and multi-worker deployments.\n+\n+Required env:\n+- `CRM_CACHE_DB_PATH=/opt/lottoexpress-website/data/crm_cache.sqlite`\n+- `WEBSITE_BRAND=lottoexpress`\n+\n+Optional:\n+- `CRM_SYNC_ENABLE=1` (background sync jackpots + draw results)\n+- `CRM_CACHE_ONLY=1` (offline mode: serve cache only; never call CRM)\n+\n+Server permissions:\n+- Ensure `/opt/lottoexpress-website/data/` is writable by the `lottoexpress` service user.

### Notes / gaps
- **Syndicate checkout** is not supported by `POST /api/v1/checkout` (CRM limitation per API doc).
- Promo pages require CRM bundles to exist (`GET /api/v1/bundles/<bundle_slug>`).
- Wallet topup return URLs must be allowlisted in CRM for the brand.

