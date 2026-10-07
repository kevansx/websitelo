"""Every LottosOnline customer email, in one place (7 October 2026).

Each email is a Handlebars template (SendGrid dynamic-template syntax, see lo_hbs.py) inside one shared layout:
purple header with the logo, white card, footer with the 18+ line and the company details. The same source is

* exported as standalone files for whoever sends them (SendGrid, the CRM): `flask --app app emails-export`
  writes emails/html/<key>.html, emails/preview/<key>.html (filled with the sample data) and emails/README.md;
* rendered by the site itself for the emails it sends (lo_mail.send_template).

Groups:
* recreated from the old site's normal emails (welcome, verify, password reset, order confirmation, deposit,
  results, winnings), with the old Spin to Win, VIP and cashback parts left out;
* refer a friend, on the Live Friends model (Lottos Online plan, 2 October 2026: "friend's first paid entry,
  both rewarded"), paid as a gift pack each;
* the site's own tools: gift packs, the home-screen free line, syndicates, withdrawals, cart reminders, jackpot
  alerts.

Wording rules carried over from the site: a gift pack is "a gift" and "a free entry", never "win", "prize" or
"lucky"; nothing promises a win; marketing emails go only to customers who allow marketing email (and never to
Denmark), and carry a preferences link.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

import lo_hbs

PROD_URL = "https://www.lottosonline.com"

# ------------------------------------------------------------------ colours (static/brands/lottosonline/css/tokens.css)
BRAND, BRAND_DEEP, PAGE, SUNKEN = "#582178", "#3e1456", "#f7f5fa", "#f1ecf5"
INK, MUTED, HAIR = "#1d1324", "#5f5468", "#e4e1ec"
CTA, GOLD, GOLD_100, OK_100, OK_700, ERR_100, ERR_600 = "#0b7a08", "#fdbc00", "#fff3d1", "#dcf5e7", "#06704a", "#fdecec", "#c81e1e"
FONT = "Arial,Helvetica,sans-serif"

# ------------------------------------------------------------------ building blocks (each returns Handlebars HTML)


def h1(text: str) -> str:
    return (f'<h1 class="lo-h1" style="margin:0 0 16px;font:700 26px/32px {FONT};color:{INK};">{text}</h1>')


def h2(text: str) -> str:
    return f'<h2 style="margin:28px 0 10px;font:700 18px/24px {FONT};color:{BRAND};">{text}</h2>'


def p(text: str) -> str:
    return f'<p style="margin:0 0 14px;font:400 16px/24px {FONT};color:{INK};">{text}</p>'


def small(text: str) -> str:
    return f'<p style="margin:0 0 10px;font:400 13px/19px {FONT};color:{MUTED};">{text}</p>'


def button(label: str, href: str, color: str = CTA) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" class="lo-btn" style="margin:22px 0 18px;">'
        f'<tr><td align="center" bgcolor="{color}" style="border-radius:999px;">'
        f'<a href="{href}" target="_blank" style="display:inline-block;padding:14px 30px;font:700 16px/20px {FONT};'
        f'color:#ffffff;text-decoration:none;border-radius:999px;">{label}</a></td></tr></table>')


def panel(inner: str, bg: str = SUNKEN, border: str = "transparent") -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;">'
        f'<tr><td style="background:{bg};border:1px solid {border};border-radius:12px;padding:18px 20px;">{inner}</td></tr></table>')


def panel_title(text: str, color: str = INK) -> str:
    return f'<p style="margin:0 0 6px;font:700 17px/23px {FONT};color:{color};">{text}</p>'


def panel_text(text: str) -> str:
    return f'<p style="margin:0;font:400 15px/22px {FONT};color:{INK};">{text}</p>'


def rows(pairs: list[tuple[str, str]]) -> str:
    """A two-column summary. A pair whose value starts with '#if ' is wrapped in that condition."""
    out = ['<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
           f'style="margin:0 0 18px;border-top:1px solid {HAIR};">']
    for label, value in pairs:
        cond = None
        if value.startswith("#if "):
            cond, value = value[4:].split(" ", 1)
        row = (f'<tr><td style="padding:10px 0;border-bottom:1px solid {HAIR};font:400 15px/21px {FONT};color:{MUTED};">{label}</td>'
               f'<td align="right" style="padding:10px 0;border-bottom:1px solid {HAIR};font:700 15px/21px {FONT};color:{INK};">{value}</td></tr>')
        out.append("{{#if " + cond + "}}" + row + "{{/if}}" if cond else row)
    out.append("</table>")
    return "".join(out)


def big(value: str, color: str = BRAND) -> str:
    return f'<p style="margin:4px 0 6px;font:800 34px/40px {FONT};color:{color};">{value}</p>'


# A ball: {n, bonus, hit}. Main numbers on lavender, bonus numbers on purple, matched numbers gold.
BALL = (
    '<span style="display:inline-block;width:32px;height:32px;margin:0 4px 6px 0;border-radius:16px;text-align:center;'
    f'font:700 14px/32px {FONT};'
    '{{#if hit}}background:' + GOLD + ';color:' + INK + ';'
    '{{else}}{{#if bonus}}background:' + BRAND + ';color:#ffffff;{{else}}background:' + SUNKEN + ';color:' + INK + ';{{/if}}{{/if}}'
    '">{{n}}</span>')


def balls(path: str) -> str:
    return "{{#each " + path + "}}" + BALL + "{{/each}}"


SET_PASSWORD = (
    "{{#if set_password_url}}" + panel(
        panel_title("Set a password for your account")
        + panel_text("You haven't set a password yet. Set one now so you can log in any time to see your tickets, "
                     "results and winnings.")
        + button("Set My Password", "{{set_password_url}}", BRAND), GOLD_100) + "{{/if}}")

REFER_A_FRIEND = (
    "{{#if referral_url}}" + panel(
        panel_title("Share LottosOnline with a friend")
        + panel_text('Send a friend your link. When they place their first order, you each get a gift pack with a free '
                     'entry inside. <a href="{{referral_url}}" style="color:' + BRAND + ';font-weight:700;">Get your link</a>'))
    + "{{/if}}")

def pack_image(gold_flag: str) -> str:
    """The pack itself (PNG copies of the site's pack art; WebP doesn't show in Outlook)."""
    return ('<p style="margin:0 0 6px;text-align:center;">'
            '<img src="{{asset_url}}/static/brands/lottosonline/img/email/{{#if ' + gold_flag + '}}pack-gold{{else}}pack{{/if}}.png" '
            'width="140" height="197" alt="{{#if ' + gold_flag + '}}Gold gift pack{{else}}Gift pack{{/if}}" '
            'style="display:inline-block;width:140px;height:197px;"></p>')


GIFT_SMALL_PRINT = small("18+. A gift is a free entry for playing: it has no cash value. Any winnings from it are yours.")

# ------------------------------------------------------------------ layout

LAYOUT = """<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>LottosOnline</title>
<style>
  body { margin:0; padding:0; -webkit-text-size-adjust:100%; }
  img { border:0; outline:none; text-decoration:none; }
  @media (max-width:620px) {
    .lo-card { padding:26px 18px !important; }
    .lo-h1 { font-size:23px !important; line-height:29px !important; }
    .lo-btn, .lo-btn td, .lo-btn a { width:100% !important; display:block !important; box-sizing:border-box; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:__PAGE__;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">__PREHEADER__&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:__PAGE__;">
<tr><td align="center" style="padding:24px 12px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;">
  <tr><td align="center" bgcolor="__BRAND__" style="background:__BRAND__;border-radius:16px 16px 0 0;padding:22px 24px;">
    <a href="{{site_url}}" target="_blank"><img src="{{asset_url}}/static/brands/lottosonline/img/logo-on-dark.png" width="184" height="28" alt="LottosOnline" style="display:block;width:184px;height:28px;color:#ffffff;font:700 22px/28px Arial,Helvetica,sans-serif;"></a>
  </td></tr>
  <tr><td class="lo-card" bgcolor="#ffffff" style="background:#ffffff;padding:34px 36px 26px;border-radius:0 0 16px 16px;">
__BODY__
  </td></tr>
  <tr><td style="padding:22px 18px 8px;font:400 12px/18px __FONT__;color:__MUTED__;text-align:center;">
__FOOTER__
    <p style="margin:0 0 8px;">Questions? Email <a href="mailto:support@lottosonline.com" style="color:__MUTED__;">support@lottosonline.com</a>.
      <strong>18+ only.</strong> Please play responsibly.</p>
    <p style="margin:0 0 8px;">www.LottosOnline.com is a trade name of Marvicap Limited, Archangelou 48, Office 207, 2nd floor,
      Engomi, 2404, Nicosia, Cyprus. Marvicap Limited operates an independent ticket messenger service and is not affiliated
      with or endorsed by official lottery organisations.</p>
    <p style="margin:0;"><a href="{{site_url}}/privacy-policy" style="color:__MUTED__;">Privacy Policy</a> &middot;
      <a href="{{site_url}}/terms-and-conditions" style="color:__MUTED__;">Terms &amp; Conditions</a></p>
  </td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
"""

FOOTERS = {
    "service": '    <p style="margin:0 0 8px;">This is a service email about your LottosOnline account.</p>',
    "marketing": ('    <p style="margin:0 0 8px;">You are receiving this because you chose to hear from LottosOnline. '
                  '<a href="{{site_url}}/account" style="color:__MUTED__;">Email preferences</a>'
                  '{{#if unsubscribe}} &middot; <a href="{{{unsubscribe}}}" style="color:__MUTED__;">Unsubscribe</a>{{/if}}</p>'),
    "invite": ('    <p style="margin:0 0 8px;">{{referrer_first_name}} asked us to send you this invitation. We have not added '
               'you to any mailing list.</p>'),
    "staff": '    <p style="margin:0 0 8px;">Internal: for the LottosOnline team only.</p>',
}

# ------------------------------------------------------------------ the emails

E: dict[str, dict[str, Any]] = {}


def email(key: str, *, group: str, name: str, subject: str, preheader: str, audience: str, trigger: str,
          sender: str, sent_by: str, body: str, sample: dict, alerts_footer: bool = False) -> None:
    E[key] = dict(key=key, group=group, name=name, subject=subject, preheader=preheader, audience=audience,
                  trigger=trigger, sender=sender, sent_by=sent_by, body=body, sample=sample, alerts_footer=alerts_footer)


CONF = "confirmation@lottosonline.com"
ALERT = "alert@lottosonline.com"

SAMPLE_BALLS = [{"n": n} for n in (4, 12, 19, 33, 45)] + [{"n": 7, "bonus": True}]

# ---------- Account
email(
    "welcome", group="Account", name="Welcome",
    subject="Welcome to LottosOnline",
    preheader="Your account is ready. Your first order comes with a gift pack.",
    audience="service", sender=CONF, sent_by="Site or CRM",
    trigger="Account created (old site: welcome2).",
    body=h1("Welcome to LottosOnline{{#if first_name}}, {{first_name}}{{/if}}")
    + p("Your account is ready. Play the world's biggest lotteries from wherever you are, with official tickets and "
        "a scan of every ticket in your account.")
    + SET_PASSWORD
    + panel(panel_title("Your first order comes with a gift pack")
            + panel_text("Place your first order and a gift pack opens on screen. Rip it open to reveal a free entry."))
    + "{{#if homescreen_offer}}" + panel(
        panel_title("Plus a free Saturday Lotto line")
        + panel_text('Add LottosOnline to your phone\'s home screen and open it from the new icon while logged in. We\'ll '
                     'add a free line in the next Australia Saturday Lotto draw. '
                     '<a href="{{site_url}}/home-screen-offer" style="color:' + BRAND + ';">How it works and terms</a>')) + "{{/if}}"
    + button("Play Now", "{{site_url}}/lottery-tickets")
    + small("You log in with {{email}}."),
    sample={"first_name": "Sam", "email": "sam@example.com", "homescreen_offer": True,
            "set_password_url": None})

email(
    "welcome_friend", group="Refer a friend", name="Welcome, joined through a friend",
    subject="Welcome to LottosOnline: {{referrer_first_name}} sent you",
    preheader="Place your first order and you each get a gift pack.",
    audience="service", sender=CONF, sent_by="Site or CRM",
    trigger="Account created through a friend's referral link (old site: welcome2referfriend).",
    body=h1("Welcome to LottosOnline{{#if first_name}}, {{first_name}}{{/if}}")
    + p("{{referrer_first_name}} invited you, and your account is ready. Play the world's biggest lotteries with "
        "official tickets and a scan of every ticket in your account.")
    + SET_PASSWORD
    + panel(panel_title("Your first order: a gift pack for you and {{referrer_first_name}}")
            + panel_text("When you place your first order, you each get a gift pack with a free entry inside. "
                         "That's on top of the gift pack every first order brings."), GOLD_100)
    + button("Play Now", "{{site_url}}/lottery-tickets")
    + GIFT_SMALL_PRINT,
    sample={"first_name": "Alex", "referrer_first_name": "Sam", "set_password_url": None})

email(
    "verify_email", group="Account", name="Confirm email address",
    subject="Confirm your email address",
    preheader="One tap to confirm your email for LottosOnline.",
    audience="service", sender=CONF, sent_by="CRM (the site calls its email-verification API)",
    trigger="Account created, or the customer asks for a new link. Not on the old site.",
    body=h1("Confirm your email address")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, please confirm that {{email}} is your email address. It keeps your account secure and "
        "makes sure your results and winnings reach you.")
    + button("Confirm My Email", "{{verify_url}}")
    + small("If you didn't create a LottosOnline account, you can ignore this email."),
    sample={"first_name": "Sam", "email": "sam@example.com", "verify_url": PROD_URL + "/verify-email?token=SAMPLE"})

email(
    "password_reset", group="Account", name="Password reset",
    subject="Reset your LottosOnline password",
    preheader="Use this link to choose a new password.",
    audience="service", sender="reminder@lottosonline.com", sent_by="CRM (the site calls its password-reset API)",
    trigger="The customer asks to reset their password (old site: reset_password2).",
    body=h1("Reset your password")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, we received a request to reset the password for {{email}}. Choose a new one here:")
    + button("Choose A New Password", "{{reset_url}}", BRAND)
    + "{{#if expires_text}}" + small("The link works for {{expires_text}}.") + "{{/if}}"
    + small("If you didn't ask for this, you can ignore this email. Your password stays the same."),
    sample={"first_name": "Sam", "email": "sam@example.com", "expires_text": "60 minutes",
            "reset_url": PROD_URL + "/reset-password?token=SAMPLE"})

# ---------- Orders and money
ORDER_ITEMS = (
    "{{#each items}}"
    + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 14px;">'
    f'<tr><td style="border:1px solid {HAIR};border-radius:12px;padding:16px 18px;">'
    f'<p style="margin:0 0 2px;font:700 16px/22px {FONT};color:{INK};">{{{{lottery_name}}}}</p>'
    f'<p style="margin:0 0 10px;font:400 14px/20px {FONT};color:{MUTED};">{{{{draws_text}}}}'
    '{{#if price}} &middot; {{price}}{{/if}}</p>'
    "{{#each lines}}<div>" + balls("balls") + "</div>{{/each}}"
    "{{#if note}}" f'<p style="margin:6px 0 0;font:400 13px/19px {FONT};color:{MUTED};">{{{{note}}}}</p>' "{{/if}}"
    "</td></tr></table>"
    "{{/each}}")

email(
    "order_confirmation", group="Orders and money", name="Order confirmation",
    subject="{{#if is_renewal}}Your renewal is confirmed{{else}}Your order confirmation{{/if}}: {{order_ref}}",
    preheader="Your entries are booked. Your ticket scans follow before the draw.",
    audience="service", sender=CONF, sent_by="Site or CRM",
    trigger="An order is paid (old site: order_confirmation2). One template covers the old variants: no password set "
            "(set_password_url), automatic renewal (is_renewal), referred customer (referral_url not passed).",
    body=h1("{{#if is_renewal}}Your renewal is confirmed{{else}}Your order is confirmed{{/if}}")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, thank you for your order. It has been processed and your entries are booked. "
        "Good luck!")
    + "{{#if pack_url}}" + panel(
        panel_title("You've unlocked a gift pack{{#if pack_is_gold}}, and it's a gold one{{/if}}!")
        + panel_text("Rip it open to reveal a free entry.")
        + pack_image("pack_is_gold")
        + button("Open My Gift Pack", "{{pack_url}}", BRAND), GOLD_100) + "{{/if}}"
    + h2("Order summary")
    + rows([("Order number", "{{order_ref}}"), ("Date", "{{order_date}}"), ("Paid by", "#if payment_method {{payment_method}}"),
            ("Account balance used", "#if balance_used {{balance_used}}"), ("Total", "{{total}}")])
    + "{{#if descriptor}}" + small("The payment shows on your card statement as <strong>{{descriptor}}</strong>.") + "{{/if}}"
    + h2("Your tickets")
    + ORDER_ITEMS
    + h2("What's next")
    + p("A scan of each ticket appears in your account once it's bought, before the draw. We'll email your results "
        "as soon as the draw has been checked, including any winnings.")
    + button("See My Tickets", "{{site_url}}/orders")
    + "{{#if is_renewal}}" + small('This order renews automatically. To change or stop it, go to '
                                   '<a href="{{site_url}}/account" style="color:' + MUTED + ';">your account</a>.') + "{{/if}}"
    + SET_PASSWORD + REFER_A_FRIEND,
    sample={"first_name": "Sam", "order_ref": "LO-1048213", "order_date": "Wed 7 Oct 2026", "total": "€17.50",
            "payment_method": "Visa ending 4242", "balance_used": None, "descriptor": "LOTTOSONLINE.COM",
            "is_renewal": False, "pack_url": PROD_URL + "/account/packs/SAMPLE", "pack_is_gold": False,
            "set_password_url": None, "referral_url": PROD_URL + "/account/refer",
            "items": [
                {"lottery_name": "US Powerball", "draws_text": "1 draw: Sat 10 Oct 2026", "price": "€7.00",
                 "lines": [{"balls": SAMPLE_BALLS}, {"balls": [{"n": n} for n in (2, 8, 21, 40, 61)] + [{"n": 14, "bonus": True}]}]},
                {"lottery_name": "EuroMillions", "draws_text": "4 draws from Fri 9 Oct 2026", "price": "€10.50",
                 "note": "Multi-draw: same lines in every draw, 10% off each line.",
                 "lines": [{"balls": [{"n": n} for n in (3, 17, 22, 38, 49)] + [{"n": 2, "bonus": True}, {"n": 11, "bonus": True}]}]},
            ]})

email(
    "deposit_confirmation", group="Orders and money", name="Funds added",
    subject="LottosOnline deposit confirmation: {{deposit_ref}}",
    preheader="Your funds are in your account and ready to play.",
    audience="service", sender=CONF, sent_by="Site or CRM",
    trigger="A top-up to the account balance succeeds (old site: deposit_confirmation2).",
    body=h1("Your funds are in your account")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your deposit has gone through and is ready to use on any of our lotteries.")
    + panel(small("Amount added") + big("{{amount}}"))
    + rows([("Reference", "{{deposit_ref}}"), ("Date", "{{deposit_date}}"), ("Paid by", "#if payment_method {{payment_method}}"),
            ("Account balance now", "#if balance {{balance}}")])
    + "{{#if descriptor}}" + small("The payment shows on your card statement as <strong>{{descriptor}}</strong>.") + "{{/if}}"
    + "{{#if continue_url}}" + button("Finish My Order", "{{continue_url}}") + "{{else}}"
    + button("Play Now", "{{site_url}}/lottery-tickets") + "{{/if}}",
    sample={"first_name": "Sam", "amount": "€25.00", "deposit_ref": "D-55120", "deposit_date": "Wed 7 Oct 2026",
            "payment_method": "Visa ending 4242", "balance": "€31.40", "descriptor": "LOTTOSONLINE.COM", "continue_url": None})

RESULT_LINES = (
    "{{#each lines}}"
    f'<tr><td style="padding:10px 0;border-bottom:1px solid {HAIR};">' + balls("balls") + "</td>"
    f'<td align="right" style="padding:10px 0;border-bottom:1px solid {HAIR};font:700 14px/20px {FONT};'
    'color:{{#if prize}}' + OK_700 + '{{else}}' + MUTED + '{{/if}};white-space:nowrap;">'
    "{{#if prize}}{{prize}}{{else}}{{matched}}{{/if}}</td></tr>"
    "{{/each}}")

email(
    "results", group="Orders and money", name="Draw results",
    subject="Your {{lottery_name}} results for {{draw_date}}",
    preheader="{{#if won}}You've won {{total_won}}. See your results.{{else}}Your numbers checked against the draw.{{/if}}",
    audience="service", sender=CONF, sent_by="Site (needs draw results from the CRM) or CRM",
    trigger="After each draw, to every customer with an entry in it (old site: result_email2, and result_email2lead "
            "when no password is set).",
    body=h1("Your {{lottery_name}} results")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, here are your results for the {{draw_date}} draw.")
    + "{{#if won}}" + panel(panel_title("Congratulations, you've won {{total_won}}!", OK_700)
                           + panel_text("We've added {{total_won}} to your winnings balance. Your breakdown is below."), OK_100)
    + "{{else}}" + panel(panel_title("Not this time")
                         + panel_text("Your numbers didn't come up in this draw. Your breakdown is below.")) + "{{/if}}"
    + h2("Winning numbers")
    + "<div>" + balls("winning_balls") + "</div>"
    + "{{#if bonus_label}}" + small("{{bonus_label}}") + "{{/if}}"
    + "{{#if jackpot_status}}" + small("{{jackpot_status}}") + "{{/if}}"
    + h2("Your lines")
    + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 6px;'
      f'border-top:1px solid {HAIR};">' + RESULT_LINES + "</table>"
    + small("Numbers in gold matched the draw.")
    + "{{#if won}}" + button("See My Winnings", "{{site_url}}/account") + "{{/if}}"
    + "{{#if next_jackpot}}" + panel(
        panel_title("Next draw: {{next_draw_date}}")
        + panel_text("The {{lottery_name}} jackpot is <strong>{{next_jackpot}}</strong>.")
        + button("Play {{lottery_name}}", "{{play_url}}")) + "{{/if}}"
    + SET_PASSWORD + REFER_A_FRIEND,
    sample={"first_name": "Sam", "lottery_name": "US Powerball", "draw_date": "Sat 10 Oct 2026", "won": True,
            "total_won": "€4.00",
            "winning_balls": [{"n": n} for n in (4, 9, 19, 50, 66)] + [{"n": 7, "bonus": True}],
            "bonus_label": "Purple: the Powerball.", "jackpot_status": "Nobody matched every number, so the jackpot rolls over.",
            "lines": [{"balls": [{"n": 4, "hit": True}, {"n": 12}, {"n": 19, "hit": True}, {"n": 33}, {"n": 45},
                                 {"n": 7, "bonus": True, "hit": True}], "prize": "€4.00"},
                      {"balls": [{"n": n} for n in (2, 8, 21, 40, 61)] + [{"n": 14, "bonus": True}], "matched": "No match"}],
            "next_draw_date": "Mon 12 Oct 2026", "next_jackpot": "€312 Million",
            "play_url": PROD_URL + "/lottery-tickets/us-powerball", "set_password_url": None, "referral_url": None})

email(
    "winnings_paid", group="Orders and money", name="Winnings added",
    subject="LottosOnline winnings: {{amount}} added to your account",
    preheader="Your winnings are in your account.",
    audience="service", sender=CONF, sent_by="Site (checks ticket statuses after each draw) or CRM",
    trigger="Winnings are credited to the customer's winnings balance (old site: deposit_winnings_confirmation).",
    body=h1("Congratulations{{#if first_name}}, {{first_name}}{{/if}}!")
    + p("Your winnings from the {{lottery_name}} draw on {{draw_date}} are in your account.")
    + panel(small("Added to your winnings balance") + big("{{amount}}", OK_700), OK_100)
    + rows([("Reference", "{{reference}}"), ("Winnings balance now", "#if winnings_balance {{winnings_balance}}")])
    + p("Withdraw your winnings or use them for your next entries. It's up to you.")
    + button("Go To My Account", "{{site_url}}/account")
    + "{{#if claim_note}}" + small("{{claim_note}}") + "{{/if}}",
    sample={"first_name": "Sam", "lottery_name": "US Powerball", "draw_date": "Sat 10 Oct 2026", "amount": "€4.00",
            "reference": "WIN-88213", "winnings_balance": "€4.00", "claim_note": None})

email(
    "withdrawal_received", group="Orders and money", name="Withdrawal request received",
    subject="We've received your withdrawal request for {{amount}}",
    preheader="Reference {{reference}}. We'll pay it within {{days}} working days.",
    audience="service", sender=CONF, sent_by="Site (lo_withdraw.py), sent today",
    trigger="The customer asks to withdraw winnings at /account/withdraw.",
    body=h1("Withdrawal request received")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, we've received your request to withdraw {{amount}} from your winnings.")
    + rows([("Reference", "{{reference}}"), ("Amount", "{{amount}}"), ("Paid by", "#if method {{method}}")])
    + p("We'll pay it within {{days}} working days and contact you if we need anything else."),
    sample={"first_name": "Sam", "amount": "€120.00", "reference": "W17", "method": "Bank transfer", "days": 5})

email(
    "withdrawal_paid", group="Orders and money", name="Withdrawal paid",
    subject="Your withdrawal of {{amount}} has been paid",
    preheader="Reference {{reference}}.",
    audience="service", sender=CONF, sent_by="Team (send by hand when the payment is made) or CRM",
    trigger="The team pays a withdrawal. Nothing sends this automatically yet: payouts are made by hand.",
    body=h1("Your withdrawal has been paid")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, we've paid {{amount}} from your winnings.")
    + rows([("Reference", "{{reference}}"), ("Amount", "{{amount}}"), ("Paid by", "#if method {{method}}"),
            ("Paid on", "{{paid_date}}")])
    + p("Depending on your bank it can take a few working days to arrive. If it hasn't arrived after five working "
        "days, reply to this email with the reference."),
    sample={"first_name": "Sam", "amount": "€120.00", "reference": "W17", "method": "Bank transfer", "paid_date": "Mon 12 Oct 2026"})

email(
    "withdrawal_request_staff", group="Orders and money", name="Withdrawal request (to the team)",
    subject="Withdrawal request {{reference}}: customer {{customer_id}}, {{amount}}",
    preheader="Nothing has been paid or debited yet.",
    audience="staff", sender=CONF, sent_by="Site (lo_withdraw.py), sent today",
    trigger="A customer asks to withdraw winnings. Goes to the support address.",
    body=h1("Withdrawal request {{reference}}")
    + p("A customer has asked to withdraw winnings. Nothing has been paid or debited yet.")
    + rows([("Customer id", "{{customer_id}}"), ("Name", "{{customer_name}}"), ("Email", "{{customer_email}}"),
            ("Amount", "{{amount}}"), ("Winnings balance at request", "{{balance}}"), ("Pay by", "{{method}}")])
    + h2("Payment details") + panel(panel_text("{{details}}"))
    + p("When paid: debit the Winnings bucket on the customer's wallet page in the CRM, with a reason quoting "
        "{{reference}}."),
    sample={"reference": "W17", "customer_id": 50123, "customer_name": "Sam Example", "customer_email": "sam@example.com",
            "amount": "€120.00", "balance": "€140.00", "method": "Bank transfer", "details": "IBAN CY00 0000 0000 0000"})

# ---------- Gift packs and offers
email(
    "pack_waiting", group="Gift packs and offers", name="Gift pack waiting",
    subject="{{#if is_gold}}Your gold gift pack is waiting{{else}}Your gift pack is waiting{{/if}}",
    preheader="Rip it open to reveal a free entry.",
    audience="marketing", sender=CONF, sent_by="Site",
    trigger="A gift pack has been sealed for 3 days (packs open themselves after 14).",
    body=h1("{{#if is_gold}}You've got a gold gift pack{{else}}You've got a gift pack{{/if}} to open")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, a gift pack is waiting in your account. Rip it open to reveal a free entry.")
    + pack_image("is_gold")
    + button("Open My Gift Pack", "{{pack_url}}", BRAND)
    + small("Not opened by {{opens_on}}? It opens itself, and the free entry is still yours.")
    + GIFT_SMALL_PRINT,
    sample={"first_name": "Sam", "is_gold": True, "pack_url": PROD_URL + "/account/packs/SAMPLE", "opens_on": "Wed 21 Oct 2026"})

email(
    "pack_opened", group="Gift packs and offers", name="Gift pack opened for you",
    subject="We opened your gift pack: {{gift_title}}",
    preheader="Your free entry is in your account.",
    audience="service", sender=CONF, sent_by="Site (nightly packs-auto-open job)",
    trigger="A gift pack left sealed for 14 days opens itself.",
    body=h1("We opened your gift pack")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your gift pack was waiting for 14 days, so we opened it for you.")
    + panel(panel_title("Inside: {{gift_title}}") + "{{#if gift_detail}}" + panel_text("{{gift_detail}}") + "{{/if}}", GOLD_100)
    + p("It's already in your account. You'll find it with your tickets.")
    + button("See My Tickets", "{{site_url}}/orders")
    + GIFT_SMALL_PRINT,
    sample={"first_name": "Sam", "gift_title": "A free US Powerball line", "gift_detail": "Quick pick, in the Sat 24 Oct 2026 draw."})

email(
    "homescreen_free_line", group="Gift packs and offers", name="Free Saturday Lotto line added",
    subject="Your free Saturday Lotto line is in",
    preheader="Thanks for adding LottosOnline to your home screen.",
    audience="service", sender=CONF, sent_by="Site (lo_homescreen.py, when the line is granted)",
    trigger="The customer opens LottosOnline from their home screen while logged in, and the free line is granted.",
    body=h1("Your free line is in")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, thanks for adding LottosOnline to your home screen. Your free quick-pick line is in the "
        "<strong>Australia Saturday Lotto</strong> draw{{#if draw_date}} on {{draw_date}}{{/if}}.")
    + "{{#if jackpot}}" + panel(small("Jackpot") + big("{{jackpot}}")) + "{{/if}}"
    + button("See My Tickets", "{{site_url}}/orders")
    + small('One free line per customer. <a href="{{site_url}}/home-screen-offer" style="color:' + MUTED + ';">Offer terms</a>.'),
    sample={"first_name": "Sam", "draw_date": "Sat 10 Oct 2026", "jackpot": "A$20 Million"})

# ---------- Refer a friend (Live Friends model)
email(
    "refer_friend_invite", group="Refer a friend", name="Invitation from a friend",
    subject="{{referrer_first_name}} is thinking of you",
    preheader="Open your free LottosOnline account. You both get a gift pack.",
    audience="invite", sender=CONF, sent_by="Site, when a customer enters a friend's email",
    trigger="A customer sends their referral link to a friend by email (old site: refer_friend_invite).",
    body=h1("{{referrer_first_name}} has invited you to LottosOnline")
    + p("{{referrer_first_name}} plays the world's biggest lotteries with LottosOnline: official tickets, a scan of "
        "every ticket, and no commission on winnings.")
    + "{{#if message}}" + panel(panel_text('"{{message}}"') + small("{{referrer_first_name}}")) + "{{/if}}"
    + panel(panel_title("A gift pack each")
            + panel_text("Open your free account with this link. When you place your first order, you and "
                         "{{referrer_first_name}} each get a gift pack with a free entry inside."), GOLD_100)
    + button("Open My Free Account", "{{invite_url}}")
    + small("18+ only. A gift is a free entry for playing: it has no cash value. "
            '<a href="{{site_url}}/terms-and-conditions" style="color:' + MUTED + ';">Terms apply</a>.'),
    sample={"referrer_first_name": "Sam", "message": "Fancy a go at the Powerball with me?",
            "invite_url": PROD_URL + "/create-account?ref=SAM123"})

email(
    "referral_reward", group="Refer a friend", name="Friend reward",
    subject="{{#if is_referrer}}{{friend_first_name}} played: your gift pack is here{{else}}Your friend gift pack is here{{/if}}",
    preheader="Rip it open to reveal a free entry.",
    audience="service", sender=CONF, sent_by="Site",
    trigger="A referred friend's first paid order. Sent to both: the referrer (is_referrer) and the friend.",
    body="{{#if is_referrer}}"
    + h1("Thanks for sharing{{#if first_name}}, {{first_name}}{{/if}}!")
    + p("{{friend_first_name}} joined through your link and placed their first order, so you each get a gift pack.")
    + "{{else}}"
    + h1("A gift pack from you and {{referrer_first_name}}")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, thanks for joining through {{referrer_first_name}}'s link. Your first order means you "
        "each get a gift pack.")
    + "{{/if}}"
    + pack_image("pack_is_gold")
    + button("Open My Gift Pack", "{{pack_url}}", BRAND)
    + "{{#if referral_url}}" + panel(panel_title("Share again")
                                     + panel_text('Every friend who joins and plays brings you both another gift pack, up to '
                                                  'ten friends a year. <a href="{{referral_url}}" style="color:' + BRAND
                                                  + ';font-weight:700;">Your link</a>')) + "{{/if}}"
    + GIFT_SMALL_PRINT,
    sample={"is_referrer": True, "first_name": "Sam", "friend_first_name": "Alex", "referrer_first_name": "Sam",
            "pack_url": PROD_URL + "/account/packs/SAMPLE", "referral_url": PROD_URL + "/account/refer"})

# ---------- Syndicates (lo_members.py)
MEMBERSHIPS = "{{site_url}}/account/memberships"

email(
    "syndicate_joined", group="Syndicates", name="Syndicate joined",
    subject="You're in: {{syndicate_name}} syndicate, {{weekly_price}} a week",
    preheader="10 lines in every draw. Pause or cancel any time.",
    audience="service", sender=CONF, sent_by="Site (lo_members.py), sent today",
    trigger="The customer joins a weekly syndicate.",
    body=h1("You're in the {{syndicate_name}} syndicate")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your membership is confirmed.")
    + rows([("Your share", "{{lines}} lines in every draw, 1 of {{shares}} shares"), ("Price", "{{weekly_price}} a week"),
            ("Next payment", "#if next_payment {{next_payment}}")])
    + p("Each share receives 1/{{shares}}th of any prize the syndicate's lines win. It's taken from your saved card "
        "and renews every week until you cancel.")
    + button("Manage My Membership", MEMBERSHIPS, BRAND)
    + small("To pause for a few weeks or cancel, go to your memberships. Cancelling is one tap, free and instant."),
    sample={"first_name": "Sam", "syndicate_name": "US Powerball", "weekly_price": "€3.90", "lines": 10, "shares": 40,
            "next_payment": "Wed 14 Oct 2026 at 09:00 (UTC)"})

email(
    "syndicate_renewal_due", group="Syndicates", name="Syndicate renews tomorrow",
    subject="Your {{syndicate_name}} syndicate renews tomorrow: {{weekly_price}}",
    preheader="Nothing to do if you're happy to carry on.",
    audience="service", sender=CONF, sent_by="Site (lo_members.py), sent today",
    trigger="The day before each weekly payment.",
    body=h1("Your syndicate renews tomorrow")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your {{syndicate_name}} syndicate membership renews on {{renews_at}}. We'll take "
        "{{weekly_price}} from your saved card.")
    + p("Nothing to do if you're happy to carry on: you stay in every draw.")
    + button("Pause Or Cancel", MEMBERSHIPS, BRAND)
    + small('To cancel before then, log in and tap once: <a href="{{cancel_url}}" style="color:' + MUTED + ';">cancel this membership</a>.'),
    sample={"first_name": "Sam", "syndicate_name": "US Powerball", "weekly_price": "€3.90",
            "renews_at": "Wed 14 Oct 2026 at 09:00 (UTC)", "cancel_url": PROD_URL + "/account/memberships?cancel=12"})

email(
    "syndicate_payment_received", group="Syndicates", name="Syndicate payment received",
    subject="Payment received: {{weekly_price}} for your {{syndicate_name}} syndicate",
    preheader="You're in this week's draws.",
    audience="service", sender=CONF, sent_by="Site (lo_members.py), sent today",
    trigger="A weekly syndicate payment succeeds.",
    body=h1("Payment received")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, we've taken {{weekly_price}} for your {{syndicate_name}} syndicate. You're in this week's "
        "draws, and your lines appear in your account before each draw.")
    + rows([("Amount", "{{weekly_price}}"), ("Next payment", "#if next_payment {{next_payment}}")])
    + button("See My Tickets", "{{site_url}}/orders"),
    sample={"first_name": "Sam", "syndicate_name": "US Powerball", "weekly_price": "€3.90",
            "next_payment": "Wed 21 Oct 2026 at 09:00 (UTC)"})

email(
    "syndicate_payment_failed", group="Syndicates", name="Syndicate payment failed",
    subject="We could not take your {{syndicate_name}} syndicate payment",
    preheader="You're not in this week's draws until a payment goes through.",
    audience="service", sender=CONF, sent_by="Site (lo_members.py), sent today (day 0 and day 3)",
    trigger="A weekly syndicate payment fails.",
    body=h1("We couldn't take your payment")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your weekly payment of {{weekly_price}} for your {{syndicate_name}} syndicate didn't go through."
        "{{#if reason}} The bank's message was: {{reason}}.{{/if}}")
    + panel(panel_text("You're not in this week's draws until a payment succeeds."), ERR_100)
    + button("Update My Card", "{{site_url}}/wallet/add-funds")
    + small('If you meant to stop, you don\'t need to do anything: no further payment is taken without a working card. '
            'You can also <a href="' + MEMBERSHIPS + '" style="color:' + MUTED + ';">cancel here</a>.'),
    sample={"first_name": "Sam", "syndicate_name": "US Powerball", "weekly_price": "€3.90", "reason": "Insufficient funds"})

email(
    "syndicate_cancelled", group="Syndicates", name="Syndicate cancelled",
    subject="Your {{syndicate_name}} syndicate membership is cancelled",
    preheader="Nothing more will be taken.",
    audience="service", sender=CONF, sent_by="Site (lo_members.py), sent today",
    trigger="The customer cancels, or the membership ends.",
    body=h1("Your membership is cancelled")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your {{syndicate_name}} syndicate membership is cancelled. Nothing more will be taken.")
    + p("Any draws you've already paid for still count, and any winnings go to your account as usual.")
    + button("Rejoin Any Time", "{{site_url}}/syndicates", BRAND),
    sample={"first_name": "Sam", "syndicate_name": "US Powerball"})

# ---------- Reminders and alerts (marketing consent only)
CART_LINES = ("{{#each lines}}" f'<p style="margin:0 0 6px;font:400 15px/22px {FONT};color:{INK};">{{{{this}}}}</p>' "{{/each}}")

email(
    "cart_reminder", group="Reminders and alerts", name="Lines left in the cart",
    subject="Your {{lottery_name}} lines are still in your cart",
    preheader="Finish your order before the draw closes.",
    audience="marketing", sender=CONF, sent_by="Site (lo_recover.py), sent today",
    trigger="30 minutes after a logged-in customer leaves lines in the cart (no push device).",
    body=h1("Your lines are still in your cart")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, you picked these lines but didn't finish your order:")
    + panel(CART_LINES)
    + "{{#if closes_at}}" + p("The next draw closes on <strong>{{closes_at}}</strong>.") + "{{/if}}"
    + button("Finish My Order", "{{resume_url}}"),
    sample={"first_name": "Sam", "lottery_name": "EuroMillions", "lines": ["EuroMillions: 3 17 22 38 49 + 2 11"],
            "closes_at": "Fri 9 Oct 2026 at 18:30 (UTC)", "resume_url": PROD_URL + "/cart/resume/SAMPLE"})

email(
    "cart_last_call", group="Reminders and alerts", name="Last call for the cart",
    subject="{{lottery_name}} closes {{closes_at}}",
    preheader="Your lines are still waiting.",
    audience="marketing", sender=CONF, sent_by="Site (lo_recover.py), sent today",
    trigger="24 hours after the first reminder, if the draw is still open. The last one for that cart.",
    body=h1("{{lottery_name}} closes soon")
    + p("Hi {{#if first_name}}{{first_name}}{{else}}there{{/if}}, your {{lottery_name}} lines are still waiting in your cart. Ticket sales for the next "
        "draw close on <strong>{{closes_at}}</strong>.")
    + "{{#if jackpot}}" + panel(small("Jackpot") + big("{{jackpot}}")) + "{{/if}}"
    + button("Finish My Order", "{{resume_url}}")
    + small("This is the last reminder we'll send about this cart."),
    sample={"first_name": "Sam", "lottery_name": "EuroMillions", "closes_at": "Fri 9 Oct 2026 at 18:30 (UTC)",
            "jackpot": "€97 Million", "resume_url": PROD_URL + "/cart/resume/SAMPLE"})

email(
    "jackpot_alert", group="Reminders and alerts", name="Jackpot alert",
    subject="{{lottery_name}}: {{jackpot}}",
    preheader="The jackpot you follow has passed {{threshold}}.",
    audience="marketing", sender=ALERT, sent_by="Site (lo_alerts.py, every 30 minutes), sent today",
    trigger="A jackpot the customer follows passes their chosen amount (push first; email if no push device).",
    alerts_footer=True,
    body=h1("{{lottery_name}} has passed {{threshold}}")
    + panel(small("Jackpot now") + big("{{jackpot}}")
            + "{{#if closes_at}}" + panel_text("Sales close on {{closes_at}}.") + "{{/if}}")
    + button("Play {{lottery_name}}", "{{play_url}}")
    + small('You asked us to tell you about this jackpot. <a href="{{site_url}}/account/alerts" style="color:' + MUTED
            + ';">Change or stop these alerts</a>.'),
    sample={"lottery_name": "EuroMillions", "jackpot": "€150 Million", "threshold": "€100 Million",
            "closes_at": "Fri 9 Oct 2026 at 18:30 (UTC)", "play_url": PROD_URL + "/lottery-tickets/euromillions"})

GROUPS = ("Account", "Orders and money", "Gift packs and offers", "Refer a friend", "Syndicates", "Reminders and alerts")

# ------------------------------------------------------------------ building and rendering


def source(key: str, site_url: str | None = None) -> str:
    """The complete Handlebars file for one email. site_url bakes the address in (for the handover files)."""
    e = E[key]
    footer = FOOTERS["staff" if e["audience"] == "staff" else e["audience"]]
    out = (LAYOUT.replace("__BODY__", e["body"]).replace("__FOOTER__", footer).replace("__PREHEADER__", e["preheader"])
           .replace("__PAGE__", PAGE).replace("__BRAND__", BRAND).replace("__FONT__", FONT).replace("__MUTED__", MUTED))
    out = out.replace("<title>LottosOnline</title>", "<title>" + e["subject"] + "</title>")
    if site_url:
        out = out.replace("{{site_url}}", site_url.rstrip("/")).replace("{{asset_url}}", site_url.rstrip("/"))
    return out


def subject(key: str, data: dict) -> str:
    return _html.unescape(lo_hbs.render(E[key]["subject"], data)).strip()


def render(key: str, data: dict, site_url: str, asset_url: str | None = None) -> tuple[str, str, str]:
    """-> (subject, html, text). asset_url: where the logo is served (defaults to site_url)."""
    d = {"site_url": site_url.rstrip("/"), "asset_url": (asset_url or site_url).rstrip("/"), **(data or {})}
    page = lo_hbs.render(source(key), d)
    return subject(key, d), page, html_to_text(page)


def html_to_text(page: str) -> str:
    """A readable plain-text part: links as 'label: url', one paragraph per block."""
    body = re.sub(r"(?is)<(head|style|title)[^>]*>.*?</\1>", "", page)
    body = re.sub(r'(?is)<div style="display:none.*?</div>', "", body)
    body = re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                  lambda m: (re.sub(r"<[^>]+>", "", m.group(2)).strip() + ": " + m.group(1)) if not m.group(1).startswith("mailto:")
                  else re.sub(r"<[^>]+>", "", m.group(2)), body)
    body = re.sub(r"(?is)<img[^>]*>", "", body)
    body = re.sub(r"(?i)</(p|h1|h2|tr|div|table)>", "\n", body)
    body = re.sub(r"(?i)</td>", "  ", body)
    body = re.sub(r"(?i)</span>", " ", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = _html.unescape(body)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in body.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip() + "\n"


def variables(key: str) -> list[str]:
    return sorted((lo_hbs.variables(source(key)) | lo_hbs.variables(E[key]["subject"])) - {"site_url", "asset_url"})


# ------------------------------------------------------------------ handover files and the local preview


def _sample(key: str, site_url: str) -> dict:
    return {"site_url": site_url, **E[key]["sample"]}


AUDIENCE_TEXT = {"service": "Service (every customer)", "marketing": "Marketing consent only",
                 "invite": "Sent to a friend at a customer's request", "staff": "Internal (team)"}


def readme() -> str:
    out = ["# LottosOnline emails", "",
           "Built 7 October 2026 from the site's `lo_emails.py`. One file per email, in one shared LottosOnline layout.",
           "", "## The files", "",
           "- `html/<key>.html`: the template to load wherever the email is sent. Handlebars, the syntax SendGrid "
           "dynamic templates use (`{{name}}`, `{{#if}}`, `{{#each}}`). Links point at https://www.lottosonline.com.",
           "- `preview/<key>.html`: the same email filled with sample data, to look at in a browser.",
           "- `index.html`: every preview on one page.", "",
           "The logo loads from https://www.lottosonline.com/static/brands/lottosonline/img/logo-on-dark.png, which "
           "exists once the new site is live on www. Until then it shows as the word LottosOnline; to use the "
           "files before the switch, change that one address to https://www1.lottosonline.com.", "",
           "The site sends the ones marked \"sent today\" itself, from the same source. When the subject has `{{...}}` "
           "in it, paste it into the template's subject field as it is.", "",
           "## Rules for every sender", "",
           "- Never email customers in Denmark.",
           "- \"Marketing consent only\" emails go only to customers who allow marketing email, and carry the "
           "preferences link (plus SendGrid's `{{{unsubscribe}}}` when a suppression group is used).",
           "- `first_name` may be left out: greetings fall back to \"Hi there\".",
           "- A list of balls is `[{\"n\": 7, \"bonus\": true, \"hit\": true}]`: `bonus` for the extra number "
           "(Powerball, Lucky Stars), `hit` for a number that matched the draw.", ""]
    for g in GROUPS:
        out += [f"## {g}", ""]
        for key, e in E.items():
            if e["group"] != g:
                continue
            out += [f"### {e['name']} (`{key}`)", "",
                    f"- **Subject:** `{e['subject']}`",
                    f"- **Preheader:** {e['preheader']}",
                    f"- **From:** {e['sender']}",
                    f"- **Who gets it:** {AUDIENCE_TEXT[e['audience']]}",
                    f"- **When:** {e['trigger']}",
                    f"- **Sent by:** {e['sent_by']}",
                    "- **Data:** " + ", ".join(f"`{v}`" for v in variables(key)), ""]
    return "\n".join(out)


def index_page(prefix: str = "preview/") -> str:
    cards = []
    for g in GROUPS:
        cards.append(f'<h2>{_html.escape(g)}</h2><div class="grid">')
        for key, e in E.items():
            if e["group"] == g:
                cards.append(
                    f'<figure><figcaption><strong>{_html.escape(e["name"])}</strong> <code>{key}</code><br>'
                    f'<span>{_html.escape(subject(key, _sample(key, PROD_URL)))}</span></figcaption>'
                    f'<iframe src="{prefix}{key}.html" loading="lazy" title="{_html.escape(e["name"])}"></iframe></figure>')
        cards.append("</div>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>LottosOnline emails</title><style>body{margin:0;padding:24px 16px;font:15px/1.5 Arial,sans-serif;background:#f7f5fa;color:#1d1324}"
            "h1{margin:0 0 4px}h2{margin:32px 0 12px;color:#582178}.grid{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}"
            "figure{margin:0;background:#fff;border:1px solid #e4e1ec;border-radius:12px;overflow:hidden}figcaption{padding:10px 12px;font-size:13px}"
            "figcaption span{color:#5f5468}iframe{display:block;width:100%;height:640px;border:0;border-top:1px solid #e4e1ec}</style></head><body>"
            f"<h1>LottosOnline emails</h1><p>{len(E)} emails, shown with sample data.</p>" + "".join(cards) + "</body></html>")


def export(out_dir, preview_asset_url: str | None = None) -> list[str]:
    """preview_asset_url: where the previews load images from (www1 until the new site is live on www)."""
    from pathlib import Path
    out = Path(out_dir)
    (out / "html").mkdir(parents=True, exist_ok=True)
    (out / "preview").mkdir(parents=True, exist_ok=True)
    for key in E:
        (out / "html" / f"{key}.html").write_text(source(key, PROD_URL), encoding="utf-8")
        _, page, _ = render(key, E[key]["sample"], PROD_URL, preview_asset_url)
        (out / "preview" / f"{key}.html").write_text(page, encoding="utf-8")
    (out / "index.html").write_text(index_page(), encoding="utf-8")
    (out / "README.md").write_text(readme(), encoding="utf-8")
    return sorted(E)


def register(app) -> None:
    import os

    import click
    from flask import abort

    @app.cli.command("emails-export")
    @click.argument("out_dir", default="emails")
    @click.option("--preview-images", default=None, help="Image host for the previews, e.g. https://www1.lottosonline.com")
    def emails_export_cmd(out_dir: str, preview_images: str | None):
        """Write every email template (html/), a filled-in preview of each (preview/), index.html and README.md."""
        keys = export(out_dir, preview_images)
        print(f"{len(keys)} emails written to {out_dir}")

    def _local() -> bool:
        return (os.getenv("WEBSITE_ENV") or "").strip().lower() == "local"

    @app.get("/dev/emails")
    def dev_emails():
        if not _local():
            abort(404)
        return index_page("/dev/emails/")

    @app.get("/dev/emails/<key>.html")
    def dev_email(key: str):
        if not _local() or key not in E:
            abort(404)
        import lo_mail
        return render(key, E[key]["sample"], lo_mail.SITE_URL if os.getenv("LO_SITE_URL") else "", "")[1]
