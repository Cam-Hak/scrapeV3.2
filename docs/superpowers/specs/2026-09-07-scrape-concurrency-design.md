# Speeding up the gathering run

Date: 2026-09-07

## Problem

`scrape.py` walks sites one at a time and each page pays a fixed sleep budget.
At 89 sites a run takes roughly two hours. At the thousands of sites the project
is aiming for, a run would not finish inside a day.

Per page, `Browser.get` spends:

- `SETTLE` sleep, 2s (`scraper/browser.py`)
- `grown()` probe, 2s minimum and up to 10s (`scraper/browser.py`)
- `REQUEST_DELAY` before each article, 2s (`scrape.py`)

That is six seconds of unconditional sleeping on top of one to three seconds of
real page load. The sleeps do not adapt: a page that is ready immediately pays
the same as one that is still building itself.

## Why not coroutines

`sb_cdp.Chrome` is synchronous, and SeleniumBase does not expose its async CDP
layer as a supported API. Async would not help even if it did. One browser tab
loads one page at a time, and the waiting happens inside Chrome, not inside
Python. The unit worth parallelising is the browser, not the call.

A thread pool gets everything async would and works with the synchronous library
already in use. Every blocking call here, `time.sleep` and CDP socket reads,
releases the GIL.

## Phase 1 - remove the fixed sleeps

Cuts the per-page floor. Ships and is verified before phase 2 starts.

### Adaptive settle

`SETTLE` and `grown()` collapse into one poll loop:

- poll roughly every 0.3s
- settle after three consecutive readings with no growth
- hard ceiling around 12s

A page that is ready immediately costs about 0.9s instead of 4s. A genuinely
slow page gets more patience than it has now, because a higher ceiling no longer
costs anything on fast pages.

Poll `document.documentElement.outerHTML.length`, an integer, rather than
`get_html()`. Polling `get_html()` drags the whole document across the wire
every 300ms. Pull the full HTML once, after the size has settled.

### Challenge wait

`_past_challenge()` itself is unchanged. It is already conditional, so it only
costs time on sites that actually challenge.

Its ordering does change, and getting this wrong silently breaks Cloudflare
sites. Today `SETTLE` runs first so there is a rendered page for the challenge
check to look at. With the fixed sleep gone, a challenge check running
immediately after `open()` could read a still-blank page, miss the marker and
return, leaving the settle poll to settle happily on the interstitial.

The order becomes: open, settle poll, challenge check, and if the check actually
cleared a challenge, settle poll a second time on the real page. Challenged
sites pay two poll passes, everything else pays one. The alternative, teaching
the poll loop to treat the challenge marker as unsettled, needs the full HTML on
every poll and gives back the saving the integer poll was there to get.

### Request delay

Changes from "sleep 2, then fetch" to "ensure 2s has elapsed since the previous
request began". Same politeness, but it usually costs nothing because the fetch
already took longer than two seconds.

The timestamp lives on the `Browser` instance. That makes it per-host for free
once phase 2 lands, because a worker owns one browser and handles one site at a
time, so consecutive requests through a given browser always go to the same
host. No shared clock and no cross-worker coordination.

### Verification

The existing report is the regression detector. Run the current 89 sites and
record `found`, `parsed` and `stored` per site. Make the change. Run again and
diff. Any site that moves from parsing to `parsed=0` means the settle check is
too eager. That comparison gates the phase.

### Expected

About 9s per page down to about 4s.

## Phase 2 - parallel sites

### Unit of work

One site per task. Articles within a site stay sequential behind the request
delay, so no single host ever sees concurrent requests. Parallelism spreads
across different hosts, which is the safe direction.

### What a worker owns

A `Browser` and a MySQL connection, both held in `threading.local()` so they
survive across sites. Chrome startup costs several seconds and must not be paid
per site. Four to eight MySQL connections is a trivial load on the server.

### What stays in the main thread

SQLite. `Store` is only touched at the edges of a task: read the recipe and the
failure flag before dispatch, write the pass or fail after the future returns.
Hoisting both into the main loop avoids a per-thread connection, WAL mode and
lock contention. The "no recipe" and "marked failed" skips then happen exactly
where they do today.

`Report` likewise. Each task returns a plain result tuple, the main thread
consumes completed futures and calls the existing `Report` methods unchanged.
No locks anywhere in the design.

### Logging

Several workers printing at once shuffles the per-site narrative into noise.
`scrape_site` collects its lines into a list and returns them; the main thread
prints each block whole when the site finishes. Sites appear in completion order
rather than list order.

Live progress inside a site is lost. A one-line "started <a_id>" and
"done <a_id>" heartbeat from the main thread covers it.

### Worker count

A `--workers` flag, default 4. The right value differs between a development
machine and the server, and tuning it should not mean editing code.

Rough sizing, bounded by Chrome rather than by Python. Each headed Chrome under
Xvfb runs around 300-500MB and bursts a core while rendering.

| Server | Workers |
|---|---|
| 4 vCPU / 8GB | 4 |
| 8 vCPU / 16GB | 8 |

### Host grouping

The current 89 sites have no duplicate hostnames. As the list grows, two entries
will eventually share a host and could then run concurrently. Group tasks by
hostname so same-host sites never overlap.

## Prerequisite - Xvfb on Linux

`Browser` has no Xvfb path. `OFFSCREEN` is Windows-only and `None` elsewhere, so
a headless Linux server has no display on which to park a headed Chrome, and
headless mode is detectable (`research/webdriver-choice.md`).

The intended fix is deployment rather than code: run the process under
`xvfb-run python scrape.py --workers 6`. One virtual display, every browser on
it, no change to `browser.py`.

This is untested against `sb_cdp` and must be confirmed on the actual server
before any worker count is meaningful.

## Expected result

Estimates read from the sleep budget in the code, not measured.

| | per page | 1000 sites |
|---|---|---|
| now | ~9s | ~22h |
| phase 1 | ~4s | ~10h |
| phase 1 + 6 workers | ~4s | ~1.7h |

## To verify before implementing

- Whether `sb_cdp.Chrome` exposes an `evaluate()` for the size poll. If it does
  not, the fallback is polling `get_html()` on a longer interval, which still
  wins but by less.
- Whether `xvfb-run` works with `sb_cdp` on the target server.

## Not in scope

- **HTTP-first article fetching.** Listing pages need JavaScript, but many
  article bodies are server-rendered. Fetching those over plain HTTP with a
  browser fallback is likely the single largest remaining win. It also changes
  the anti-bot posture and needs per-site verification that bodies still parse.
  A separate piece of work.
- **Per-site learned settle times.** Storing an observed settle time in the
  recipe adds state and a failure mode when a site changes. The adaptive poll
  gets most of the win without either.
- **Multiprocessing.** Chrome is already out of process, so the GIL was never
  the constraint. Processes would add IPC for the report and separate
  connections per worker for no gain over threads.
