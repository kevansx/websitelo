"""Customer emails (lo_emails.py), the Handlebars subset they use (lo_hbs.py) and the HTML part lo_mail sends."""
from __future__ import annotations

import re

import pytest

import lo_emails
import lo_hbs
import lo_mail


# ------------------------------------------------------------------ the renderer
def test_handlebars_subset_matches_handlebars():
    src = ("{{#if a}}A{{else}}not A{{/if}}|{{#unless b}}no B{{/unless}}|"
           "{{#each xs}}[{{@index}}:{{n}}{{#if hit}}*{{/if}}{{../tag}}{{@root.tag}}]{{else}}none{{/each}}|{{{raw}}}|{{esc}}")
    out = lo_hbs.render(src, {"a": 0, "b": [], "tag": "t", "xs": [{"n": 1, "hit": True}, {"n": 2}],
                              "raw": "<b>x</b>", "esc": "<b>&"})
    assert out == "not A|no B|[0:1*tt][1:2tt]|<b>x</b>|&lt;b&gt;&amp;"
    assert lo_hbs.render("{{#each xs}}x{{else}}none{{/each}}", {"xs": []}) == "none"
    assert lo_hbs.render("{{#each xs}}{{this}},{{/each}}", {"xs": ["a", "b"]}) == "a,b,"


def test_names_inside_each_do_not_leak_from_the_outer_scope():
    # Handlebars only looks at the current item; the site must render exactly what SendGrid would.
    assert lo_hbs.render("{{#each xs}}{{tag}}{{/each}}", {"tag": "t", "xs": [{}]}) == ""


@pytest.mark.parametrize("src", ["{{#if a}}x", "{{/if}}", "{{#with a}}x{{/with}}", "{{else}}"])
def test_bad_templates_are_refused(src):
    with pytest.raises(lo_hbs.TemplateError):
        lo_hbs.render(src, {})


# ------------------------------------------------------------------ every email
@pytest.mark.parametrize("key", sorted(lo_emails.E))
def test_every_email_renders_its_sample_completely(key):
    subject, page, text = lo_emails.render(key, lo_emails.E[key]["sample"], "https://www.lottosonline.com")
    assert subject and "{{" not in subject
    assert "{{" not in page and "}}" not in page and "__" not in page
    assert "18+ only" in page and "Marvicap Limited" in page and "support@lottosonline.com" in page
    assert 'src="https://www.lottosonline.com/static/brands/lottosonline/img/logo-on-dark.png"' in page
    assert "18+ only" in text and "<" not in re.sub(r"<[^>]*@", "", text)
    assert "Hi ," not in page and ", ," not in page


@pytest.mark.parametrize("key", sorted(lo_emails.E))
def test_handover_files_have_the_production_address_baked_in(key):
    src = lo_emails.source(key, lo_emails.PROD_URL)
    assert "{{site_url}}" not in src and src.startswith("<!doctype html>")
    lo_hbs.render(src, {})          # parses


def test_greetings_fall_back_without_a_first_name():
    _, page, _ = lo_emails.render("syndicate_cancelled", {"syndicate_name": "EuroMillions"}, "https://x")
    assert "Hi there," in page


def test_marketing_emails_carry_the_preferences_link_and_service_emails_do_not():
    for key, e in lo_emails.E.items():
        page = lo_emails.render(key, e["sample"], "https://x")[1]
        if e["audience"] == "marketing":
            assert "https://x/account" in page and "chose to hear from LottosOnline" in page, key
        else:
            assert "chose to hear from LottosOnline" not in page, key


def test_gift_pack_emails_follow_the_wording_rules():
    for key in ("pack_waiting", "pack_opened", "referral_reward", "refer_friend_invite"):
        body = lo_emails.E[key]["body"] + lo_emails.E[key]["subject"]
        assert not re.search(r"\b(win|won|prize|jackpot|lucky)\b", body, re.I), key
        assert "no cash value" in body, key


def test_old_site_promotions_are_not_carried_over():
    every = " ".join(e["body"] + e["subject"] for e in lo_emails.E.values()).lower()
    for gone in ("spin", "wheel", "vip", "cashback", "rewards points"):
        assert gone not in every


def test_results_show_matches_and_the_bonus_ball():
    page = lo_emails.render("results", lo_emails.E["results"]["sample"], "https://x")[1]
    assert "Congratulations, you&#x27;ve won €4.00!" in page or "Congratulations, you've won €4.00!" in page
    assert page.count("background:#fdbc00") == 3            # three matched numbers in gold
    assert "background:#582178;color:#ffffff" in page        # the Powerball


def test_order_confirmation_variants():
    base = dict(lo_emails.E["order_confirmation"]["sample"])
    subject, page, _ = lo_emails.render("order_confirmation", {**base, "is_renewal": True, "pack_url": None,
                                                              "set_password_url": "https://x/set"}, "https://x")
    assert subject == "Your renewal is confirmed: LO-1048213"
    assert "renews automatically" in page and "Set My Password" in page and "Open My Gift Pack" not in page


def test_readme_lists_every_email_and_its_data():
    text = lo_emails.readme()
    for key in lo_emails.E:
        assert f"(`{key}`)" in text
    assert "`resume_url`" in text and "Never email customers in Denmark." in text


# ------------------------------------------------------------------ sending
def test_send_template_writes_text_and_html_to_the_outbox(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(lo_mail, "outbox", lambda: tmp_path)
    assert lo_mail.send_template("a@example.com", "syndicate_cancelled", {"syndicate_name": "EuroMillions"},
                                 text="Plain words.") == "outbox"
    txt, = tmp_path.glob("*.txt")
    html, = tmp_path.glob("*.html")
    assert "Subject: Your EuroMillions syndicate membership is cancelled" in txt.read_text(encoding="utf-8")
    assert "Plain words." in txt.read_text(encoding="utf-8")
    assert "Your membership is cancelled" in html.read_text(encoding="utf-8")


def test_send_template_makes_plain_text_from_the_html_when_none_is_given(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(lo_mail, "outbox", lambda: tmp_path)
    lo_mail.send_template("a@example.com", "password_reset", lo_emails.E["password_reset"]["sample"])
    txt = next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")
    assert "Choose A New Password: https://www.lottosonline.com/reset-password?token=SAMPLE" in txt
    assert txt.count("18+ only") == 1


def test_smtp_message_has_both_parts(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(lo_mail.smtplib, "SMTP", FakeSMTP)
    assert lo_mail.send_template("a@example.com", "syndicate_cancelled", {"syndicate_name": "EuroMillions"}) == "sent"
    types = [p.get_content_type() for p in sent[0].walk()]
    assert "text/plain" in types and "text/html" in types


def test_preview_pages_are_local_only(client, monkeypatch):
    monkeypatch.setenv("WEBSITE_ENV", "production")
    assert client.get("/dev/emails").status_code == 404
    monkeypatch.setenv("WEBSITE_ENV", "local")
    assert b"LottosOnline emails" in client.get("/dev/emails").data
    assert client.get("/dev/emails/results.html").status_code == 200
    assert client.get("/dev/emails/nope.html").status_code == 404
