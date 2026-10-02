"""Home-page banner carousel (after theLotter's top banner, reviewed 2 Oct 2026).

Each slide is text set straight on its own background (no card), with one illustration, a pill button and
small print. Slides come from two places:

* built-in slides below: the brand promise (the old home banner's own words), the biggest jackpots right now
  (live from the CRM jackpot feed), the lotteries available, and the two standing offers whose terms are
  published on the site (Spin to Win, VIP Rewards);
* special offers created in the CRM as marketing banners for the "home" placement
  (GET /api/v1/marketing/banners?placement=home: title, body, cta_label, cta_href, start/end, priority).
  They are slotted in after the first jackpot slide, highest priority first, so a new offer appears on the
  site the moment it is switched on in the CRM, in the LottosOnline style, with no code change.

A slide is a plain dict, so the template needs no knowledge of where it came from:
  theme, kicker, title, highlight, text, cta_label, cta_href, cta2_label, cta2_href, small_print,
  small_href, art ("balls" | "ball" | "wheel" | "crown" | "gift"), balls[], countdown_iso
"""
from __future__ import annotations

THEMES = ("brand", "rollover", "indigo", "night", "magenta", "gold")


def home_slides(rows: list[dict], featured: list[dict], crm_banners: list[dict] | None, *, logged_in: bool,
                lo_ball) -> list[dict]:
    slides: list[dict] = []
    top = [r for r in featured if r.get("jp") and r["jp"].get("display")]

    # 1. the old home banner, word for word
    slides.append({
        "id": "brand", "theme": "brand", "art": "balls",
        "kicker": "Buy Official Lottery Tickets",
        "title": "To Enter The Worlds Biggest Jackpots!",
        "tag": "Lowest Prices With Scanned Tickets!",
        "cta_label": "Play Now", "cta_href": "/lottery-tickets",
        "cta2_label": None if logged_in else "Open Free Account", "cta2_href": "/create-account",
        "balls": [lo_ball(r["lottery"]) for r in top[:3]],
    })

    # 2. the biggest jackpot right now
    if top:
        lead = top[0]
        lot, jp = lead["lottery"], lead["jp"]
        slides.append({
            "id": "jackpot-" + lot.slug, "theme": "rollover", "art": "ball",
            "kicker": f"{lot.name} jackpot",
            "title": "Help Stop The Rollover",
            "highlight": jp["display"],
            "text": f"Nobody has matched every number yet. Your {lot.name} lines could be the ones that do.",
            "cta_label": f"Play {lot.name}", "cta_href": f"/lottery-tickets/{lot.slug}",
            "countdown_iso": None if jp.get("closed") else jp.get("cutoff_iso"),
            "balls": [lo_ball(lot)],
        })

    # special offers from the CRM, right after the headline jackpot
    for b in sorted(crm_banners or [], key=lambda x: -(x.get("priority") or 0)):
        title = (b.get("title") or "").strip()
        if not title:
            continue
        slides.append({
            "id": f"crm-{b.get('id')}", "theme": THEMES[(len(slides) + 2) % len(THEMES)], "art": "gift",
            "kicker": "Special offer", "title": title, "text": (b.get("body") or "").strip(),
            "cta_label": (b.get("cta_label") or "Find out more").strip(), "cta_href": (b.get("cta_href") or "/").strip(),
            "small_print": "Terms and Conditions apply.", "small_href": "/terms-and-conditions",
        })

    # 3. the next big jackpot
    if len(top) > 1:
        lot, jp = top[1]["lottery"], top[1]["jp"]
        slides.append({
            "id": "jackpot-" + lot.slug, "theme": "indigo", "art": "ball",
            "kicker": f"Next big draw: {lot.name}",
            "title": f"{jp['display']} Up For Grabs",
            "text": "Buy official tickets online and receive a scan of every ticket in your account.",
            "cta_label": f"Play {lot.name}", "cta_href": f"/lottery-tickets/{lot.slug}",
            "countdown_iso": None if jp.get("closed") else jp.get("cutoff_iso"),
            "balls": [lo_ball(lot)],
        })

    # 4. lotteries available
    slides.append({
        "id": "lotteries", "theme": "night", "art": "balls",
        "kicker": "Lottos & Games",
        "title": f"{len(rows)} Of The World's Biggest Lotteries",
        "text": "From US Powerball and Mega Millions to EuroMillions and Oz Lotto. Official tickets, "
                "a scan of every ticket and no commission on winnings.",
        "cta_label": "See All Lotteries", "cta_href": "/lottery-tickets",
        "balls": [lo_ball(r["lottery"]) for r in rows[:7]],
    })

    # 5. Spin to Win (terms published at /spin-to-win and /spin-to-win-terms-and-conditions)
    slides.append({
        "id": "spin-to-win", "theme": "magenta", "art": "wheel",
        "kicker": "Spin to Win",
        "title": "Deposit, Spin And Win",
        "text": "Your first three deposits of €5 or more earn up to 30% back in rewards, plus free spins on our Prize Wheel.",
        "cta_label": "How It Works", "cta_href": "/spin-to-win",
        "small_print": "Terms and Conditions apply.", "small_href": "/spin-to-win-terms-and-conditions",
    })

    # 6. VIP Rewards (terms published at /VIP-rewards)
    slides.append({
        "id": "vip", "theme": "gold", "art": "crown",
        "kicker": "VIP Rewards",
        "title": "10% Cash Back For VIPs",
        "text": "Spend €50 or more in 30 days and get 10% cash back on everything you buy for the next 30 days.",
        "cta_label": "Join The VIP Club", "cta_href": "/VIP-rewards",
        "small_print": "Terms and Conditions apply.", "small_href": "/VIP-rewards",
    })
    return slides
