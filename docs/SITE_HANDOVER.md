# Everything else we had to fix, for the other site

Companion to `PAYMENTS_HANDOVER.md`, which covers wallet top-ups and is the
larger half. This one covers the rest of what we found between 2026-08-27 and
2026-09-03: country blocking, background work against the CRM, draw countdowns,
and the play page's draw days.

Worth reading even if your site looks healthy. Three of the four below were
silent — the page returned 200, the log was clean, and the feature simply did
not do its job. Two of them we shipped a fix for and it still did nothing,
because the fix ran on a code path production never took.

Some of this code carries `Winnow logic` and `Winnow-style` comments, meaning it
was written to mirror yours. Where that is true the bug may be shared, and those
places are called out.

## 1. Country blocking blocked nobody

Compliance asked for Malta to be blocked. It was, in the CRM, and Malta kept
browsing. There were four independent faults, and each one on its own was enough
to make a block look applied while doing nothing.

**The site never read the list.** This is the one that mattered. Fetching the
CRM's countries table was a step inside the general background sync, which only
runs when `CRM_SYNC_ENABLE` is set, and it is off unless somebody sets it. With
it off, `block_website` was unknown for every country and the request check
answered "not blocked" to everyone. **A compliance control was riding on a
performance switch.** Fetch the block list on its own schedule, independent of
any sync toggle.

Ours refreshes every `COUNTRY_BLOCKS_REFRESH_SECONDS` (default 300). An empty
table is fetched *inside* the request — answering from a list that was never
loaded is the one case worth making a visitor wait for — and after that
refreshes happen behind the request. Stamp the attempt *before* the call so a
CRM outage backs off instead of retrying on every page load. Use a shorter
retry (we use 30s) while the table is still empty, or a single failed attempt at
boot leaves you unprotected for the whole interval.

**The env override was dead config.** `WEBSITE_BLOCKED_COUNTRIES_ISO2` was only
consulted when a country was *missing* from the cache. The CRM's table carries
every country, so that branch never ran and setting the variable blocked nobody.
Check the env list first, on its own authority, ahead of the CRM flag. You want
both layers: the CRM flag covers every brand at once, and the env list is the
lever that needs no CRM edit and no deploy.

**The list parser only worked for one country.** The split was `[,\\s]+`, which
in a Python raw string is a character class of comma, backslash and the letter
*s* — not whitespace. `MT GB` arrived as a single token matching nothing. One
country worked, two did not. Check yours: `[,\s]+` is what was meant.

**Geo was steerable by the visitor.** Country came from the first match in a
fixed list of CDN headers beginning with `CF-IPCountry`. Those are ordinary
request headers and anyone can send them. Confirmed against production: a plain
request preselected `CA` on `/register`, and the same request with
`CF-IPCountry: MT` preselected Malta. Anyone blocked could have sent one header
and carried on.

Name the header your edge actually injects and trust only that one first. Ours
is `GEO_COUNTRY_HEADER`, defaulting to `X-Geo-Country` (Azure Front Door). The
other CDN headers are still read, but only when the trusted one is absent. If
you do not know which header your edge injects, you can find out the way we did:
send a *deliberately invalid* value in a candidate header and see whether the
real country still arrives. If it does, that candidate is not the injected one.

Two things to know before you turn it on:

- **It applies the whole list, and the list is large.** 51 of the CRM's 258
  countries carry `block_website`, including the United States, Canada,
  Australia, the Netherlands, Denmark, Greece, Poland, Romania and Singapore. A
  blocked country gets a 403 on every page. Check the list before deploying, and
  correct it in CRM Admin rather than in code.
- **Exempt your admin console and your health check.** The admin console holds
  the controls for the list, so gating it means a wrong entry can only be undone
  by someone who is not in a blocked country. And if `/health` or your static
  assets 403, the load balancer marks the site down and the 403 page renders
  unstyled.

## 2. Background work against the CRM has never run

This is the one to check first, because it is quick and it invalidates other
things you may believe are working.

Our CRM client is cached on Flask's `g`, which only exists during a request.
Every background thread that reached the CRM through the shared helper therefore
raised `Working outside of application context` on its first line. The warning
went to the log and every page carried on answering 200.

It bit us twice in one day. The country-block refresh, above, runs on a thread
when there is already a list to answer from — so on a deployed server with a
populated table it always took that path and always failed. **It passed its
tests**, because tests start from an empty cache and take the synchronous path.
It shipped, and it did nothing.

The same fault was sitting in the general `CRM_SYNC_ENABLE` background loop,
which means that loop had never worked at all. Turning the switch on — which is
what we had been told to do to fix country blocking — would have changed
nothing.

Two fixes, and you want both:

- A thread either wraps its work in an explicit application context, or builds
  its own CRM client rather than taking one off `g`.
- Any helper that reads the session must check for a request context first and
  return `None` off a request, rather than raising before it reaches the part
  that does not need one.

And a testing lesson worth taking: **if your background path and your
in-request path differ, test the background path by calling it the way the
thread does.** We now expose the sync entry point on `app.extensions` and call
it directly from a test with no request in flight.

## 3. Closed draws showed a dash instead of "Results pending"

Two lotteries showed `—` where the countdown belongs, during the window when
sales are closed and the draw has not been published. Two separate bugs, one on
each side, and either alone was enough.

**Server side: naive versus aware datetimes.** The CRM's cutoff timestamp parses
naive; `datetime.now(timezone.utc)` is aware. Comparing them raises `TypeError:
can't compare offset-naive and offset-aware datetimes`. That exception was
caught by a broad handler further up, so `sales_closed` fell back to `False` and
the server never rendered the "Results pending" state at all. Make the cutoff
aware before you compare it, in every place you derive from it — we had the same
comparison in two functions and fixed one before noticing the other.

**Client side: the ticker overwrote the finished label.** The countdown script
keeps a cached list of elements and only rebuilds it every fifth tick. When a
timer reached zero it wrote "Results pending" and removed its `data-remaining`
attribute — but the element stayed in the cached list, so the next tick read the
now-missing attribute as `NaN` and replaced the label with a dash. The guard is
one line: skip any element that no longer carries `data-remaining`.

**This one is worth checking on your side specifically.** The ticker is
commented "Winnow-style" and the closed-sales logic "Winnow logic", so if the
five-tick cache rebuild came from you, the same overwrite is likely there.

## 4. Two lotteries could not be bought at all

German Lotto (`lotto-6aus49`) and Irish Lotto (`lotto-ie`) rendered a play page
with no draw-day checkboxes. Draws are calculated as `checked days × weeks`, so
three chosen lines still read `3 Lines x 0 Draws`, the total stayed at `0.00`,
and the Play button was dead. Nothing on the page said why.

The CRM's jackpot feed carries only the next cutoff, not the draw schedule, so
the picker keeps its own map of game code to weekdays — and those two games were
never added to it. Both draw Wednesday and Saturday.

The fix is two entries, but the lesson is the failure mode. **A game missing
from a client-side map should not produce a page that silently prices at zero.**
Ours now derives a weekday from the cutoff the CRM did send and offers that one
draw: fewer days than the lottery actually holds, but a page that works and
takes money. Adding the game to the map restores the rest.

Pin the map to the catalogue with a test. Ours asserts that every game code the
CRM sells appears in both the weekday map and the timezone map, so the next game
added cannot ship this way. Get the timezone right too — a late-evening European
draw formatted in UTC names the wrong day.

## Configuration we added

| Variable | Default | What it does |
| --- | --- | --- |
| `WALLET_DIRECT_CARD_PROCESSORS` | `eltrovox,emerchant,worldpay,testing,traxx` | Processors the site will charge a card against directly. See `PAYMENTS_HANDOVER.md`; note it must not veto the `allowed`/`status` shape. |
| `WEBSITE_BLOCKED_COUNTRIES_ISO2` | empty | Site-level block, checked ahead of the CRM flag. No CRM edit, no deploy. |
| `GEO_COUNTRY_HEADER` | `X-Geo-Country` | The one geo header your edge injects and the only one trusted first. |
| `COUNTRY_BLOCKS_REFRESH_SECONDS` | `300` | How often the CRM block list is re-read, independent of any sync toggle. |

## Checklist

- [ ] Is your country block list fetched independently of your general CRM sync
      toggle, or does a compliance control depend on a performance switch?
- [ ] Does your env-level block list get checked before the CRM flag, or only
      when the CRM has no answer?
- [ ] Split a two-country list from that variable and confirm both block.
- [ ] Can a visitor change their apparent country by sending a header? Test it
      with `curl -H` against a page that reveals the detected country.
- [ ] Are your admin console, health check and static assets exempt from the
      403?
- [ ] Does any background thread reach the CRM through a request-scoped client?
      Check the log for `Working outside of application context`.
- [ ] Is there a test that calls your background sync the way the thread does,
      with no request in flight?
- [ ] Are CRM timestamps made timezone-aware everywhere you compare or subtract
      them — and is a broad `except` hiding the failure when they are not?
- [ ] Does your countdown ticker re-process elements it has already finished?
- [ ] Does every game you sell have draw weekdays and a timezone, and is that
      pinned by a test against the CRM's game list?
- [ ] Does an unknown game render a buyable page, or a silent `0.00`?
