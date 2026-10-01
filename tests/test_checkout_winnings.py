"""
Winnings are money, and being unable to spend them without asking is not the
same as having none.

Production, 2026-09-14, customer A1009227. She held USD 14.86 - USD 5.07 she
had deposited and USD 9.79 she had won - and tried to buy one Powerball line
for USD 5.80. Checkout spends deposits and will not touch winnings unless the
request carries `use_wins: true`, which the customer has to authorise, so the
CRM correctly returned 402 four times: 15:17:00, 15:19:51, 15:22:02, 17:12:47.
The website read that as "insufficient funds" and sent her to add money she
already had, while the header showed her the combined USD 14.86.

Nobody was wrong except the website, and it was wrong twice: it never asked
the one question that would have completed the sale, and it showed a total
next to a pay button that could only spend part of it.

An earlier fix here read `available_balance_cents` as "what she can spend".
It is not - it is deposits plus winnings after reservations, another total,
and that misreading is pinned shut below.
"""

from __future__ import annotations

import json
import logging

import pytest

from crm_api import CRMClient, CRMError

from test_offers import _bundle, catalog, serve_bundle  # noqa: F401 - fixtures


SLUG = "PB_Wins"
ONE_LINE = json.dumps([{"main": "1,2,3,4,5", "power": 6}])
TWO_LINES = json.dumps([{"main": "1,2,3,4,5", "power": 6}, {"main": "6,7,8,9,10", "power": 1}])

# Her wallet and her cart, to the cent.
ADDED = 507
WINS = 979
CART = 580
# What the winnings have to cover once the deposits are spent.
FROM_WINS = CART - ADDED  # 73


@pytest.fixture
def offer(serve_bundle):  # noqa: F811
    serve_bundle(
        _bundle(SLUG, [{"product_code": "PSX-W", "quantity": 1}],
                locked_price_base_cents=CART, base_currency="USD")
    )


@pytest.fixture
def offer_two_lines(serve_bundle):  # noqa: F811
    """The second cart from the report: two Powerball lines at USD 11.60."""
    serve_bundle(
        _bundle(SLUG, [{"product_code": "PSX-W", "quantity": 2}],
                locked_price_base_cents=1160, base_currency="USD")
    )


@pytest.fixture
def wallet(monkeypatch):
    """The wallet in the shape the CRM returns it: a total made of two pots."""
    state = {
        "currency": "USD",
        "added_cents": ADDED,
        "wins_cents": WINS,
        "reserved_added_cents": 0,
        "reserved_wins_cents": 0,
        "split": True,
    }

    def fake_wallet(self, token, *a, **kw):
        total = state["added_cents"] + state["wins_cents"]
        available = total - state["reserved_added_cents"] - state["reserved_wins_cents"]
        w = {
            "currency": state["currency"],
            "balance_cents": total,
            # Both totals, and the trap: neither is "what checkout will spend".
            "available_balance_cents": available,
            "withdrawable_cents": total,
        }
        if state["split"]:
            w.update({
                "added_funds_balance_cents": state["added_cents"],
                "wins_balance_cents": state["wins_cents"],
                "reserved_added_funds_cents": state["reserved_added_cents"],
                "reserved_wins_cents": state["reserved_wins_cents"],
            })
        return {"wallet": w}

    monkeypatch.setattr(CRMClient, "wallet", fake_wallet)
    return state


@pytest.fixture
def quote(monkeypatch, wallet):
    """
    The CRM's price for the cart, carrying the funding object it works out
    against this quote: both shortfalls, reservations already taken off.
    """
    state = {"total_cents": CART, "funding": True}

    def fake_quote(self, payload, *a, **kw):
        total = state["total_cents"]
        added = max(0, wallet["added_cents"] - wallet["reserved_added_cents"])
        wins = max(0, wallet["wins_cents"] - wallet["reserved_wins_cents"])
        q = {
            "currency": "USD",
            "total_cents": total,
            "total_base_cents": total,
            "items": [{"product_code": "PSX-W", "item_total_in_customer_cents": total,
                       "draws_count": 1}],
        }
        if state["funding"]:
            q["funding"] = {
                "added_funds_balance_cents": added,
                "wins_balance_cents": wins,
                "shortfall_without_wins_cents": max(0, total - added),
                "shortfall_with_wins_cents": max(0, total - (added + wins)),
            }
        return {"quote_id": 4471, "quote": q}

    monkeypatch.setattr(CRMClient, "checkout_quote", fake_quote)
    return state


@pytest.fixture
def submits(monkeypatch, wallet):
    """
    Records every submit, and refuses exactly as the CRM does: deposits only,
    unless the request authorised winnings.
    """
    calls: list[dict] = []

    def fake_submit(self, token, *, quote_id, use_wins=False):
        calls.append({"quote_id": quote_id, "use_wins": use_wins})
        added = max(0, wallet["added_cents"] - wallet["reserved_added_cents"])
        wins = max(0, wallet["wins_cents"] - wallet["reserved_wins_cents"])
        spendable = added + wins if use_wins else added
        if spendable < CART:
            raise CRMError(
                "Insufficient wallet balance",
                status_code=402,
                payload={
                    "error": "Insufficient wallet balance",
                    # The total, deposits and winnings together, exactly as
                    # the CRM sends it.
                    "balance_cents": added + wins,
                    "added_funds_balance_cents": added,
                    "wins_balance_cents": wins,
                    "use_wins": use_wins,
                    "shortfall_cents": CART - spendable,
                    "required_cents": CART,
                    "currency": "USD",
                },
            )
        return {"order_id": 4762, "quote_id": quote_id, "currency": "USD", "total_cents": CART}

    monkeypatch.setattr(CRMClient, "checkout_submit", fake_submit)
    monkeypatch.setattr(
        CRMClient, "checkout",
        lambda self, token, payload: (_ for _ in ()).throw(AssertionError("must use the quote path")),
    )
    return calls


def _cart(client, lines=ONE_LINE):
    client.get(f"/offer/{SLUG}")
    client.post(f"/offer/{SLUG}/start", data={"lines_json": lines})
    return client.get("/cart")


def _says_broke(body: str) -> bool:
    """
    The words she was shown. Any of these, over a wallet that covers the cart,
    is the bug.
    """
    lowered = body.lower()
    return "insufficient" in lowered or "add funds to continue" in lowered


# --- A1009227, reproduced ---


def test_her_cart_does_not_tell_her_she_has_insufficient_funds(
    client, offer, quote, wallet, submits
):
    """added 507, wins 979, cart 580. She is not short of money."""
    body = _cart(client).data.decode("utf-8")
    assert not _says_broke(body)


def test_her_cart_offers_to_use_the_winnings_for_the_remainder(
    client, offer, quote, wallet, submits
):
    """The question nobody asked her, and the amount it would take."""
    body = _cart(client).data.decode("utf-8")
    assert "Added funds do not cover this cart" in body
    assert "Use Winnings and Confirm Order" in body
    assert f"USD {FROM_WINS / 100:.2f}" in body, "the 73c the winnings would cover"


def test_her_cart_also_offers_to_add_funds_instead(client, offer, quote, wallet, submits):
    """
    Authorising winnings is a choice and choices need an alternative. Some
    customers are saving a win and would rather pay.
    """
    body = _cart(client).data.decode("utf-8")
    assert "Add Funds Instead" in body
    assert "add-funds" in body


def test_choosing_to_use_winnings_places_the_order(client, offer, quote, wallet, submits):
    """The sale that four 402s failed to make."""
    _cart(client)
    resp = client.post("/checkout", data={"use_wins": "1"})
    assert submits, "checkout must have been submitted"
    assert submits[-1]["use_wins"] is True
    assert resp.status_code in (301, 302)
    assert "/orders/" in resp.headers.get("Location", "")


def test_the_order_is_not_placed_until_she_asks_for_it(client, offer, quote, wallet, submits):
    """
    Her winnings are hers. Arriving at a cart must never spend them, and the
    cart must not quietly send the authorisation on her behalf.
    """
    _cart(client)
    assert not submits, "loading a cart must not submit anything"
    body = _cart(client).data.decode("utf-8")
    assert 'name="use_wins" value="1"' in body, "the flag rides on the button she presses"


def test_a_plain_confirm_never_authorises_winnings(client, offer, quote, wallet, submits):
    """
    The default is preserve winnings, and it has to survive a submit that says
    nothing about them.
    """
    _cart(client)
    client.post("/checkout", data={})
    assert submits[-1]["use_wins"] is False


# --- the second cart from the report ---


def test_two_lines_at_1160_still_offers_winnings_rather_than_calling_her_broke(
    client, offer_two_lines, quote, wallet, submits
):
    """
    A USD 11.60 cart against added 507 + wins 979 = 1486. Still covered, still
    not a reason to tell her she has no money.
    """
    quote["total_cents"] = 1160
    body = _cart(client, TWO_LINES).data.decode("utf-8")
    assert not _says_broke(body)
    assert "Use Winnings and Confirm Order" in body
    assert "USD 6.53" in body, "1160 less the 507 of added funds"


# --- a real shortfall is still a real shortfall ---


def test_a_cart_beyond_both_pots_says_insufficient_and_offers_add_funds(
    client, offer, quote, wallet, submits
):
    """
    added 507 + wins 979 against a 2000 cart. Nothing she authorises fixes
    this, so this is the one case that gets to say insufficient funds.
    """
    quote["total_cents"] = 2000
    body = _cart(client).data.decode("utf-8")
    assert "Add Funds to Continue" in body
    assert "Use Winnings and Confirm Order" not in body


def test_a_real_shortfall_is_measured_against_both_pots_not_just_deposits(
    client, offer, quote, wallet, submits
):
    """
    Telling her she is USD 14.93 short of a USD 20.00 cart ignores the
    winnings she holds. The real gap, once everything is counted, is 5.14.
    """
    quote["total_cents"] = 2000
    body = _cart(client).data.decode("utf-8")
    assert "USD 5.14 short" in body


def test_an_empty_wallet_is_told_plainly_and_without_mentioning_winnings(
    client, offer, quote, wallet, submits
):
    """
    No winnings, no wording about winnings in the notice. The wallet panel
    still lists all three amounts - a zero is an answer - but the message
    must not offer her something she does not have.
    """
    wallet["added_cents"] = 0
    wallet["wins_cents"] = 0
    body = _cart(client).data.decode("utf-8")
    assert "Add Funds to Continue" in body
    assert "This order needs USD 5.80 and your added funds are USD 0.00" in body
    assert "and winnings" not in body


def test_deposits_that_cover_the_cart_leave_the_winnings_alone(
    client, offer, quote, wallet, submits
):
    """
    The common case, and the one most easily broken by a fix for the others:
    enough in deposits means no question and no prompt.
    """
    wallet["added_cents"] = CART + 100
    body = _cart(client).data.decode("utf-8")
    assert "Confirm Order" in body
    assert "Use Winnings" not in body
    assert not _says_broke(body)


# --- the three amounts, never the total alone ---


def test_the_cart_shows_added_funds_and_winnings_separately(
    client, offer, quote, wallet, submits
):
    """
    A total beside the pay button is a promise the button cannot keep, because
    it can only spend one half of it without being asked.
    """
    body = _cart(client).data.decode("utf-8")
    assert "Wallet total" in body
    assert "Added funds" in body
    assert "Winnings" in body
    assert "USD 14.86" in body
    assert "USD 5.07" in body
    assert "USD 9.79" in body


def test_the_header_shows_the_split_not_just_the_total(client, wallet):
    """
    USD 14.86 on its own in the top bar is what made the refusal look like a
    malfunction. The total stays - it is her money - with the split beside it.
    """
    with client.session_transaction() as s:
        s["wallet"] = CRMClient.wallet(CRMClient.__new__(CRMClient), "t")["wallet"]
    body = client.get("/").data.decode("utf-8")
    assert "Balance USD 14.86" in body
    assert "Funds 5.07" in body
    assert "Wins 9.79" in body


def test_a_customer_with_no_winnings_sees_the_plain_balance(client, wallet):
    """Nothing to distinguish, nothing to clutter the header with."""
    wallet["wins_cents"] = 0
    with client.session_transaction() as s:
        s["wallet"] = CRMClient.wallet(CRMClient.__new__(CRMClient), "t")["wallet"]
    body = client.get("/").data.decode("utf-8")
    assert "Balance USD 5.07" in body
    # Scoped to the top bar: the footer has a "Results & Winnings" link.
    assert 'class="balanceSplit"' not in body


# --- the misreading that produced the first, wrong fix ---


def test_available_balance_cents_is_not_treated_as_spendable(
    client, offer, quote, wallet, submits
):
    """
    `available_balance_cents` is deposits plus winnings after reservations -
    a total. Reading it as "spendable without authorising winnings" makes a
    covered cart look fundable and puts the refusal back at submit.

    Here it reads 1486 while checkout can spend 507, and the cart has to side
    with checkout.
    """
    body = _cart(client).data.decode("utf-8")
    assert "Use Winnings and Confirm Order" in body, "the cart believed the total again"


def test_reservations_come_off_the_pot_they_are_held_against(
    client, offer, quote, wallet, submits
):
    """
    Deposits of 507 with 500 of them reserved leaves 7 to spend, so the
    winnings have to cover 573 rather than 73.
    """
    wallet["reserved_added_cents"] = 500
    body = _cart(client).data.decode("utf-8")
    assert "Use Winnings and Confirm Order" in body
    assert "USD 5.73" in body


# --- the 402, for tenants whose quotes carry no funding object ---


def test_a_402_over_unauthorised_winnings_is_not_reported_as_being_broke(
    client, offer, quote, wallet, submits
):
    """
    Rule 5. Without `quote.funding` the cart cannot see the split, so the
    refusal at submit is the first sight of it - and it says plainly that the
    winnings would cover the rest.
    """
    quote["funding"] = False
    wallet["split"] = False
    _cart(client)
    resp = client.post("/checkout", data={})
    assert resp.status_code in (301, 302)
    body = client.get("/cart").data.decode("utf-8")
    assert not _says_broke(body)
    assert "Use Winnings and Confirm Order" in body


def test_the_402_prompt_leads_to_a_completed_order(client, offer, quote, wallet, submits):
    """The recovery the CRM documents, carried through to the sale."""
    quote["funding"] = False
    wallet["split"] = False
    _cart(client)
    client.post("/checkout", data={})
    client.get("/cart")
    resp = client.post("/checkout", data={"use_wins": "1"})
    assert submits[-1]["use_wins"] is True
    assert "/orders/" in resp.headers.get("Location", "")


def test_a_402_that_winnings_cannot_fix_still_says_insufficient(
    client, offer, quote, wallet, submits
):
    """The distinction has to hold at the 402 as well as at the quote."""
    quote["funding"] = False
    quote["total_cents"] = 2000
    wallet["split"] = False
    _cart(client)
    client.post("/checkout", data={})
    body = client.get("/cart").data.decode("utf-8")
    assert "Add Funds to Continue" in body


def test_the_402_is_logged_with_both_pots_and_the_flag_that_was_sent(
    client, offer, quote, wallet, submits, caplog
):
    """
    Four refusals were investigated by hand because the log recorded a total
    and a requirement and nothing about why the two did not meet.
    """
    quote["funding"] = False
    wallet["split"] = False
    _cart(client)
    with caplog.at_level(logging.INFO):
        client.post("/checkout", data={})
    line = next((r.getMessage() for r in caplog.records if "checkout 402" in r.getMessage()), "")
    assert line, "a 402 must be logged"
    assert f"added={ADDED}" in line
    assert f"wins={WINS}" in line
    assert "use_wins=False" in line


def test_authorising_winnings_does_not_outlive_the_order_it_was_given_for(
    client, offer, quote, wallet, submits
):
    """
    Permission is per purchase. A flag that stuck would spend a later win on a
    later cart she never agreed to.
    """
    quote["funding"] = False
    wallet["split"] = False
    _cart(client)
    client.post("/checkout", data={"use_wins": "1"})
    _cart(client)
    client.post("/checkout", data={})
    assert submits[-1]["use_wins"] is False
