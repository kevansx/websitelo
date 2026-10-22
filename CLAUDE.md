# LottosOnline website: instructions for Claude

Read this first, every session. The full handover (history, decisions, open items) is
`W:\Desktop\claude transition\Lottos Online Site Build\2026-10-14 Lottos Online - Handover to a new Claude session.md`.

## What this is

The rebuild of LottosOnline.com (a profitable EUR lottery-ticket messenger site, operator Marvicap Limited) from the
old PHP site onto the company's own platform (the CRM, Public Website API v1). Flask + Jinja, a fork of the Lotto
Express website engine with a LottosOnline layer (`lo_*.py`, `templates/lo/`, `static/brands/lottosonline/`).
The owner is Joey. His words: "profitable, significant revenue, excellent SEO, we cannot risk anything."

## Paths

- Repo (this folder): `C:\work\lottosonline-rebuild\site` (same folder as `W:\work\lottosonline-rebuild\site`; C:\work is a
  junction to the W: portable drive). GitHub: `https://github.com/kevansx/websitelo.git`, branch `main`.
- Project folder: `C:\work\lottosonline-rebuild\` with `legacy\` (old PHP code, read-only reference), `inventory\`
  (live crawl, URL contract, Search Console exports), `crm-setup\` (CRM product request and the CRM team's reply),
  `design\pack-handover\` (gift-pack design, storyboard.md is authoritative), `tools\` (contract builder/checker).
- Lottos Online documents: `W:\work\lottosonline-rebuild\documents\` (`Plans\` and `CRM asks\`). Joey's earlier plans
  and briefs (2 to 14 Oct) are in Joey's own documents folder: ask Joey for them. **Read the relevant Plans docs before
  building any feature.**
- Staging: https://www1.lottosonline.com (auto-noindex). Status page: https://www1.lottosonline.com/health/crm.
  www.lottosonline.com is still the OLD PHP site until the IT team switches Azure Front Door over.

## Run and test

- Local preview: launch entry `lottosonline`, port 8010 (`python app.py`). Without a CRM key: `CRM_FAKE=1` and
  `WEBSITE_ENV=local` in `.env` (`fake_crm.py`, refuses to run anywhere else; its test login is in its docstring).
  `SESSION_COOKIE_SECURE=0` in the local `.env` lets a phone on the LAN log in (http://10.0.0.202:8010).
- Tests: `python -m pytest -q` (744 passing on 14 Oct 2026). Run them before every commit.
- Email previews (local only): http://localhost:8010/dev/emails. Export the email files: `flask --app app emails-export emails`.
- URL contract: `python ..\tools\check_contract.py --app` (2,489 of 2,495 pass; the 6 wait on Joey's decisions B1 to B3).

## Release cadence

1. Finish a piece of work, run the full test suite, check it in the local preview (screenshots for visual changes).
2. Commit with a plain-English message ending in the Co-Authored-By line, then **Claude pushes** to `kevansx/websitelo`
   `main` from this PC (HTTPS; the PC's credential is jevansxje-gif, a collaborator; never git@ URLs).
3. Confirm the push reached GitHub (`git ls-remote origin refs/heads/main` matches `git rev-parse HEAD`). Joey pulls
   to the server himself: never give him PuTTY or server commands (Joey, 19 Oct). Say when requirements.txt changed.
4. Joey says "it is live on www1". Then check www1 yourself (curl the pages, /health/crm) before reporting.
5. Production (www) is cut over by the IT team via Azure Front Door; never touch DNS or Front Door.

## How Joey wants to work (firm rules)

- Ops steps: ONE exact step at a time, each command block labelled **PowerShell (your PC)**, **PuTTY (server)** or
  **Browser**, no "if you haven't yet" asides, no alternative paths, and say what output he should see.
- End every finished task with a **Verify** checklist: concrete action + expected result.
- Always give full absolute Windows paths for documents (clickable links break for him).
- Finished Lottos Online documents go to `W:\work\lottosonline-rebuild\documents\` (`Plans\`, `CRM asks\`) with dated,
  plain-English names. Never save them in another business's or project's folder, and never write the name of Joey's
  company or any of Joey's own folder paths into this repo, the launch board, or anything the CRM or IT teams see.
- Fix things on our side whenever possible. Anything for the CRM team goes in ONE complete list, only true blockers,
  never a trickle of asks. Check www1 and /health/crm before claiming something is outstanding.
- Recreate competitors' layouts and animation, never their wording (grep for their phrases before reporting).
- Wording rules: a gift pack is "a gift" / "a free entry", never "win", "prize", "jackpot" or "lucky"; nothing
  promises a win ("likely", "you could win"); 18+ and play responsibly on customer pages.
- Never email customers in Denmark (DK), on any send. A send with no country filter includes Denmark.
- Marketing emails/alerts only to customers who allow marketing email (`lo_mail.marketing_allowed`).
- No secrets in code, commits or chat. `.env` is gitignored. Never print API keys.
- Present tense in anything for outside parties; never describe the CRM ("Cloud and a Half") as an outside company:
  it is the company's own platform.

## Code map (LottosOnline layer)

- `lo_routes.py` URL contract, redirects, legacy pages, sitemap/robots, tracking tags (production only).
- `lo_lotteries.py` the 19 lotteries, slugs, CRM game codes. `lo_store.py` product kinds (base `LO-XXXXX`, tiers
  `-4/-8/-16/-1W/-3W/-5W`, subscription `-W`), `cart_item_error` guard at /cart/add and checkout, MIN_LINES.
- `lo_banners.py` home carousel (real incentives only; CRM "home" marketing banners slot in automatically).
- `lo_homescreen.py` Add to Home Screen + free Australia Saturday Lotto line (terms approved 2 Oct; page /home-screen-offer).
- `lo_packs.py` gift packs: first_play, return, explorer, long_play, surprise (~1 order in 4 at random, min gap 2,
  guaranteed by gap 8, max 1 per 7 days, 1 in 4 gold, never spend-based). Gift granted via
  `POST /api/v1/marketing/incentives/grant-free-ticket` (idempotency `pack-<id>`). Constants at the top of the file.
- `lo_push.py` web push (VAPID; never rotate keys), `lo_alerts.py` jackpot alerts (push first, email second).
- `lo_members.py` weekly syndicates (LO-USPOW-W €3.90, LO-USMEG-W €5.00, LO-EUEUR-W €2.95).
- `lo_withdraw.py` withdrawal requests to support (off unless `LO_WITHDRAWALS_ON=1`; no promised turnaround).
- `lo_recover.py` abandoned-checkout reminders (30 min, 24 h). `lo_mail.py` the one email sender (SMTP or
  `data/outbox`), `send_template()` for designed emails. `lo_emails.py` all 24 email designs (SendGrid Handlebars),
  `lo_hbs.py` the renderer.
- Cron jobs on the server (README.md): packs-auto-open nightly, jackpot-alerts */30, membership-emails hourly,
  abandoned-checkout */10.

## Gotchas

- Python run inside a bash heredoc mangles backslashes (`\n` became real newlines, `\2026` became a control byte).
  Write scripts to a file with the Write tool, or use the Edit tool.
- `components.css` already defines `.lo-lot`, `.lo-hero` and similar: check before naming new classes.
- The CRM sends draw cut-offs without a time zone: treat them as UTC.
- Engine scripts depend on element IDs in the play, cart and payment pages: restyle with CSS, keep the IDs.
