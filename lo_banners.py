"""Home-page banner carousel (after theLotter's top banner, reviewed 2 Oct 2026).

Each slide is text set straight on its own background (no card), with one illustration, a pill button and
small print. Slides come from two places:

* built-in slides below: the brand promise (the old home banner's own words), the biggest jackpots right now
  (live from the CRM jackpot feed), the lotteries available, and the two standing offers whose terms are
  published on the site;
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


def _rollover_text(name: str, rise_pct) -> str:
    """Dynamic, never a promise (no "likely", no "you could win"): how far the jackpot has climbed."""
    rise = int(rise_pct or 0)
    if rise >= 25:
        return f"{name} is up {rise}% on its starting jackpot and still climbing. Get your lines in before sales close."
    return f"The {name} jackpot rolls on until someone takes it. Get your lines in before sales close."


def home_slides(rows: list[dict], featured: list[dict], crm_banners: list[dict] | None, *, logged_in: bool,
                lo_ball, extras: dict | None = None) -> list[dict]:
    """extras: what LottosOnline actually offers today (plans of 2 Oct 2026): pack_img (gift packs), share_offers
    (weekly syndicates, from lo_members.offers_for), homescreen (the free Saturday Lotto line is switched on),
    app_icon, max_saving_pct (the deepest multi-draw tier). Each slide shows only while its offer is on."""
    extras = extras or {}
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
            "title": "Be The One To Stop The Rollover",
            "highlight": jp["display"],
            # dynamic, never a promise: no "likely", no "you could win" (wording rules)
            "text": _rollover_text(lot.name, jp.get("rise_pct")),
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

    # gift packs: the pack rip. Wording rules: a gift, never "win", "prize", "jackpot" or "lucky"; random within a
    # set, and said so; for playing, no cash value.
    if extras.get("pack_img"):
        slides.append({
            "id": "gift-packs", "theme": "magenta", "art": "pack", "image": extras["pack_img"],
            "kicker": "Gift packs",
            "title": "Regular Free Gifts With Your Orders",
            "text": "Keep playing and the gift packs keep coming. Tear one open for a free entry in one lottery, "
                    "chosen at random from a set.",
            "cta_label": "Play Now", "cta_href": "/lottery-tickets",
            "small_print": "18+. A gift is a free entry for playing: no cash value.", "small_href": None,
        })

    # weekly syndicate: the cheapest way into the big US draws
    for o in (extras.get("share_offers") or [])[:1]:
        slides.append({
            "id": "syndicate-" + o["slug"], "theme": "gold", "art": "ball", "balls": [o["ball"]] if o.get("ball") else [],
            "kicker": f"{o['name']} syndicate",
            "title": f"10 Lines Every Draw For €{o['cents'] / 100:.2f} A Week",
            "text": f"Join the {o['name']} syndicate: one of 40 shares, 10 lines in every draw. Pause or cancel any time.",
            "cta_label": "How It Works", "cta_href": o["url"],
            "small_print": "Each share receives 1/40th of any prize the syndicate's lines win. Renews weekly until cancelled.",
            "small_href": None,
        })

    # the free home-screen ticket (under its own approved terms)
    if extras.get("homescreen") and extras.get("app_icon"):
        slides.append({
            "id": "homescreen", "theme": "brand", "art": "phone", "image": extras["app_icon"],
            "kicker": "Free ticket",
            "title": "A Free Saturday Lotto Line",
            "text": "Add LottosOnline to your phone's home screen, open it from the new icon and we'll add a free line "
                    "in the next Australia Saturday Lotto draw.",
            "cta_label": "Add To Home Screen", "cta_href": "/home-screen-offer", "cta_install": True,
            "small_print": "One per customer. Terms apply.", "small_href": "/home-screen-offer",
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

    # multi-draw: the tier products, discount locked in the price
    if extras.get("max_saving_pct"):
        slides.append({
            "id": "multi-draw", "theme": "indigo", "art": "balls",
            "balls": [lo_ball(r["lottery"]) for r in rows[:3]],
            "kicker": "Play more draws",
            "title": f"Save Up To {extras['max_saving_pct']}% A Line",
            "text": "Play the same lines in 4, 8 or 16 draws (or 1, 3 or 5 weeks) and pay less for every draw.",
            "cta_label": "Choose Your Lottery", "cta_href": "/lottery-tickets",
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

    # The old site's Spin to Win and VIP Rewards banners are gone: neither promotion is offered any more (Joey,
    # 2 Oct 2026). Live offers arrive as CRM "home" marketing banners (inserted above).
    return slides
