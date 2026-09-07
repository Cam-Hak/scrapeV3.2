# Gathering Speedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut a full gathering run from roughly 9s per page and one site at a time down to roughly 4s per page across several sites at once.

**Architecture:** Two phases with a verification gate between them. Phase 1 replaces the fixed sleeps in `scraper/browser.py` with an adaptive poll on page size, and turns the request delay into a floor rather than an addition. Phase 2 makes one site the unit of work and runs N worker threads, each owning its own browser and MySQL connection, while SQLite, the report and all block printing stay in the main thread.

**Tech Stack:** Python 3.13, SeleniumBase 4.53.7 (`sb_cdp`), stdlib `threading` and `queue`, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-09-07-scrape-concurrency-design.md`

## Global Constraints

- Keep code elementary; shortest working solution. No new dependencies — `threading` and `queue` are stdlib.
- Comments only on non-obvious code, one line maximum, no docstrings, no TODOs.
- Delete dead code rather than commenting it out. `grown` and `GROW_TRIES` go away entirely.
- Do not reformat lines you did not change.
- Articles within one site stay sequential. Only different hosts run concurrently.
- `--workers 1` must behave exactly like today: one browser, list order, same output.
- Phase 2 does not start until the Task 5 gate passes.

**Deviation from the spec, deliberate:** the spec named `ThreadPoolExecutor` plus `threading.local()`. This plan uses plain `threading.Thread` workers pulling from a `queue.Queue` instead. Same semantics — one browser and one connection per worker, alive for the whole run — but each worker creates its resources as ordinary locals at the top of its function, so there is no thread-local storage, no registry of created browsers and no hand-written lock. Fewer moving parts for an identical result.

---

### Task 1: Put the site id on the done line, then capture a baseline

The done line is the only per-site record of `found` and `parsed`, and it needs the site id on it for two reasons: the baseline diff in Task 5 depends on it, and once blocks arrive out of order in Phase 2 a bare "done in 5s" says nothing.

Capture the baseline in this same task, because every later task changes the numbers it is supposed to measure against.

**Files:**
- Modify: `scrape.py:136-137`

**Interfaces:**
- Consumes: nothing.
- Produces: a done line of the exact form `  <a_id> done in <n>s -- found=<n> parsed=<n> stored=<n> dupes=<n>`, which Task 5 parses.

- [ ] **Step 1: Add the site id to the done line**

In `scrape.py`, replace:

```python
            log("  done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                % (time.time() - begun, found, extracted, stored, dupes))
```

with:

```python
            log("  %s done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                % (a_id, time.time() - begun, found, extracted, stored, dupes))
```

- [ ] **Step 2: Run the existing suite to confirm nothing broke**

Run: `python -m pytest -q`
Expected: PASS, same count as before the change.

- [ ] **Step 3: Capture the baseline run**

This is the slow step. It takes roughly two hours and must run to completion.

```bash
python scrape.py > baseline.txt 2>&1
```

- [ ] **Step 4: Reduce the baseline to comparable numbers**

`stored` and `dupes` legitimately change between runs — the first run stores an article, the second finds it is already there. Only `found` and `parsed` say whether the selectors still work, so the gate compares only those.

```bash
sed -nE 's/^  ([0-9]+) done in [0-9]+s -- (found=[0-9]+ parsed=[0-9]+).*$/\1 \2/p' baseline.txt | sort > before.txt
wc -l before.txt
```

Expected: one line per site that ran, of the form `18092 found=12 parsed=10`. If this file is empty the sed did not match — fix it before going further, because Task 5 has no gate without it.

- [ ] **Step 5: Commit**

`baseline.txt` is a large run log and should not be committed. `before.txt` is small and is the artifact Task 5 needs.

```bash
echo "baseline.txt" >> .gitignore
echo "after.txt" >> .gitignore
git add scrape.py .gitignore before.txt
git commit -m "Put the site id on the done line and record a pre-change baseline"
```

---

### Task 2: Adaptive settle poll

Replaces the 2s `SETTLE` sleep and the 2s-minimum `grown()` probe with one loop that polls an integer size until it holds still. A page that is ready immediately costs about 0.9s instead of 4s, and a slow page gets a 12s ceiling that costs nothing on fast pages.

Poll `document.documentElement.outerHTML.length`, an integer, rather than `get_html()`. Polling the full document every 300ms would drag the whole page across the wire repeatedly and give back the saving.

**Files:**
- Modify: `scraper/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `settled(size, sleep)` in `scraper/browser.py`, where `size` is a zero-argument callable returning an int and `sleep` is a one-argument callable taking a float. Returns `None`. Also the module constants `POLL = 0.3`, `STABLE_READS = 3`, `SETTLE_POLLS = 40` and `SIZE`. Task 3 calls `settled` and `SIZE`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_browser.py`, delete the `pages` helper and the three `grown` tests (`test_waits_while_the_page_is_still_rendering`, `test_returns_as_soon_as_the_page_stops_growing`, `test_gives_up_once_the_page_keeps_growing`). Replace the import line and add these tests:

```python
from scraper.browser import Browser, SETTLE_POLLS, settled


def test_returns_once_the_size_holds_still():
    reads = iter([100, 100, 100, 100])
    naps = []
    settled(lambda: next(reads), naps.append)
    assert len(naps) == 3


def test_keeps_waiting_while_the_page_is_still_growing():
    reads = iter([76, 244, 248, 255, 255, 255, 255])
    naps = []
    settled(lambda: next(reads), naps.append)
    assert len(naps) == 6


def test_gives_up_once_the_page_never_stops_growing():
    sizes = iter(range(100, 500))
    naps = []
    settled(lambda: next(sizes), naps.append)
    assert len(naps) == SETTLE_POLLS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_browser.py -q`
Expected: FAIL with `ImportError: cannot import name 'SETTLE_POLLS'`.

- [ ] **Step 3: Write the implementation**

In `scraper/browser.py`, delete `GROW_TRIES`, delete the whole `grown` function, and add:

```python
POLL = 0.3
STABLE_READS = 3
SETTLE_POLLS = 40
SIZE = "document.documentElement.outerHTML.length"


def settled(size, sleep):
    # js-built listings land after the page loads, so poll until the size holds still
    last = size()
    stable = 0
    for _ in range(SETTLE_POLLS):
        sleep(POLL)
        now = size()
        stable = stable + 1 if now == last else 0
        last = now
        if stable >= STABLE_READS:
            return
```

Keep `SETTLE = 2`. Task 3 still uses it as the polling interval inside the Cloudflare challenge loop, which is a different and much slower wait.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_browser.py -q`
Expected: the three new tests PASS. The two `FlakySb` tests still fail, because `_fetch` has not been rewritten yet — that is Task 3.

- [ ] **Step 5: Commit**

```bash
git add scraper/browser.py tests/test_browser.py
git commit -m "Replace the fixed settle sleeps with an adaptive size poll"
```

---

### Task 3: Challenge ordering and the request-delay clock

Two changes to `_fetch`, both load-bearing.

**Challenge ordering.** Today `SETTLE` runs first, so there is a rendered page for the challenge check to look at. With that sleep gone, a check running straight after `open()` could read a still-blank page, miss the marker and return, leaving the settle poll to settle contentedly on the Cloudflare interstitial. The order becomes open, settle, check, and settle again only if the check actually cleared something.

**Delay clock.** The delay moves off `scrape.py` and onto the `Browser`, and becomes a floor rather than an addition: wait only for whatever is left of the two seconds since the previous request began, which is usually nothing. Putting the timestamp on the browser makes it per-host for free in Phase 2, because a worker owns one browser and handles one site at a time.

**Files:**
- Modify: `scraper/browser.py`
- Modify: `scrape.py` (remove the article-loop sleep)
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: `settled` and `SIZE` from Task 2.
- Produces: `wait_for(last, now, delay)` in `scraper/browser.py`, returning a float. `Browser._past_challenge()` now returns a bool — `True` when it actually cleared a challenge. `Browser` gains a `self.last` attribute, initially `None`.

- [ ] **Step 1: Write the failing tests**

Extend the import in `tests/test_browser.py` to include `wait_for`, and add:

```python
def test_no_wait_before_the_first_request():
    assert wait_for(None, 1000.0, 2) == 0


def test_a_slow_fetch_pays_no_extra_delay():
    assert wait_for(1000.0, 1009.0, 2) == 0


def test_a_fast_fetch_waits_out_the_remainder():
    assert wait_for(1000.0, 1000.5, 2) == 1.5
```

The two `FlakySb` tests also need updating, because `_fetch` now calls `sb.evaluate`. Add this method to `FlakySb`:

```python
    def evaluate(self, script):
        return 12
```

A constant size means `settled` returns after `STABLE_READS` naps, and `FlakySb.sleep` is already a no-op.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_browser.py -q`
Expected: FAIL with `ImportError: cannot import name 'wait_for'`.

- [ ] **Step 3: Write the implementation**

In `scraper/browser.py`, extend the config import:

```python
from .config import HEADLESS, REQUEST_DELAY
```

Add the helper next to `settled`:

```python
def wait_for(last, now, delay):
    return max(0.0, delay - (now - last)) if last else 0.0
```

Add `self.last = None` to `Browser.__init__`. Replace `_fetch` and `_past_challenge` with:

```python
    def _fetch(self, url):
        pause = wait_for(self.last, time.time(), REQUEST_DELAY)
        if pause:
            time.sleep(pause)
        self.last = time.time()
        if self.sb is None:
            self.sb = sb_cdp.Chrome(url, headless=self.headless, browser_args=OFFSCREEN)
        else:
            self.sb.open(url)
        self._settle()
        if self._past_challenge():
            self._settle()  # the interstitial settled, the real page has not
        return self.sb.get_html()

    def _settle(self):
        settled(lambda: self.sb.evaluate(SIZE), self.sb.sleep)

    def _past_challenge(self):
        # a Cloudflare interstitial can outlast the settle poll, so wait for the real page
        if CHALLENGE not in self.sb.get_html():
            return False
        deadline = time.time() + CHALLENGE_WAIT
        while CHALLENGE in self.sb.get_html() and time.time() < deadline:
            if self.sb.is_element_visible(TURNSTILE):
                self.sb.solve_captcha()
            self.sb.sleep(SETTLE)
        return True
```

In `scrape.py`, delete the line `time.sleep(config.REQUEST_DELAY)` inside the `for i, row in enumerate(rows, 1)` loop. Leave `import time` alone; `time.time()` is still used for `begun`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, including both `FlakySb` tests.

- [ ] **Step 5: Commit**

```bash
git add scraper/browser.py scrape.py tests/test_browser.py
git commit -m "Settle before the challenge check and make the request delay a floor"
```

---

### Task 4: Smoke-test the new waits against real sites

The unit tests prove the loops count correctly. They cannot prove a real page has finished rendering when the poll says it has. Run a handful of sites before committing two hours to the full comparison.

**Files:** none modified.

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: nothing in code; a go/no-go for Task 5.

- [ ] **Step 1: Run five sites and watch the timing**

```bash
python scrape.py --limit 5
```

Expected: each site's done line shows `parsed` greater than zero, and the per-site seconds are visibly lower than the same five sites in `before.txt`.

- [ ] **Step 2: Check a site that challenges**

Cloudflare sites are the ones this task exists to protect, and they identify
themselves in the baseline: the challenge wait is up to 30s per page, so they sit
at the top of the timings. Pick the three slowest and run each alone.

```bash
sed -nE 's/^  ([0-9]+) done in ([0-9]+)s.*$/\2 \1/p' baseline.txt | sort -rn | head -3
python scrape.py --id <a_id>
```

Expected: `parsed` greater than zero. `found=N parsed=0` here means the settle poll is landing on the interstitial and the Task 3 ordering is wrong — stop and fix it rather than continuing to Task 5.

- [ ] **Step 3: No commit**

Nothing changed. If either step failed, fix it in `scraper/browser.py` and commit that fix before moving on.

---

### Task 5: The Phase 1 gate

Compare `found` and `parsed` per site against the Task 1 baseline. Phase 2 does not begin until this passes.

**Files:** none modified.

**Interfaces:**
- Consumes: `before.txt` from Task 1.
- Produces: a rewritten `before.txt` holding post-phase-1 counts, which Task 9 diffs against.

- [ ] **Step 1: Run the full site list again**

```bash
python scrape.py > after.txt 2>&1
```

- [ ] **Step 2: Reduce it the same way and diff**

```bash
sed -nE 's/^  ([0-9]+) done in [0-9]+s -- (found=[0-9]+ parsed=[0-9]+).*$/\1 \2/p' after.txt | sort > after-counts.txt
diff before.txt after-counts.txt
```

Expected: no output, or only small `found` movements from sites that genuinely published in between.

Any site that moves to `parsed=0` is a regression: the settle poll is too eager for that site. Do not proceed. Raise `STABLE_READS` or `POLL` in `scraper/browser.py`, re-run, and diff again.

- [ ] **Step 3: Record the wall-clock improvement**

```bash
grep "site(s) in" after.txt
```

Compare against the same line in `baseline.txt`. The spec predicts roughly half.

- [ ] **Step 4: Commit the new baseline**

`after-counts.txt` becomes the reference for Phase 2, which must not change these numbers at all — parallelism changes when sites run, never what they parse.

```bash
mv after-counts.txt before.txt
git add before.txt
git commit -m "Record post-phase-1 per-site counts as the phase 2 reference"
```

---

### Task 6: Group sites by host

Two entries sharing a host must never run at once. Grouping them into a single unit of work makes that true by construction rather than by a lock. The current 89 sites have no duplicate hosts, so this changes nothing today and prevents a mystery block later.

**Files:**
- Modify: `scraper/sites.py`
- Test: `tests/test_sites.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `by_host(sites)` in `scraper/sites.py`, taking a list of tuples whose second element is a url, and returning a list of lists of those same tuples, preserving first-seen order. Task 8 submits one queue job per returned group.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sites.py`:

```python
from scraper.sites import by_host


def test_sites_on_different_hosts_become_separate_groups():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y")]
    assert by_host(sites) == [[(1, "https://a.test/x")], [(2, "https://b.test/y")]]


def test_sites_sharing_a_host_stay_in_one_group():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y"), (3, "https://a.test/z")]
    assert by_host(sites) == [[(1, "https://a.test/x"), (3, "https://a.test/z")],
                              [(2, "https://b.test/y")]]


def test_every_site_survives_the_grouping():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y"), (3, "https://a.test/z")]
    assert sorted(s for g in by_host(sites) for s in g) == sorted(sites)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sites.py -q`
Expected: FAIL with `ImportError: cannot import name 'by_host'`.

- [ ] **Step 3: Write the implementation**

In `scraper/sites.py`, add the import and the function:

```python
from urllib.parse import urlparse


def by_host(sites):
    groups = {}
    for site in sites:
        groups.setdefault(urlparse(site[1]).netloc, []).append(site)
    return list(groups.values())
```

Python dicts keep insertion order, so first-seen order is preserved without extra work.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sites.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/sites.py tests/test_sites.py
git commit -m "Group sites by host so same-host entries never overlap"
```

---

### Task 7: One site end-to-end, returning a result instead of printing

A worker thread cannot print as it goes — six of them interleaved turns the per-site narrative into noise. This task pulls all printing and all shared-state use out of the site work and into a value the caller handles, while everything still runs sequentially. Behaviour and output are identical after this task; only the shape changes.

**Files:**
- Modify: `scrape.py`

**Interfaces:**
- Consumes: nothing from Task 6.
- Produces: `Result`, a `namedtuple` with fields `a_id found parsed stored dupes problems error lines`, and `run_site(browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title)` returning one. On success `error` is `None`; on failure `error` is a string and the count fields are all `0`. `lines` is a list of strings for the caller to print. Also `absorb(r, store, report)`, returning `None`. Task 8 calls `run_site` from worker threads and `absorb` from the main thread.

- [ ] **Step 1: Make `scrape_site` collect its lines instead of printing**

In `scrape.py`, inside `scrape_site`, replace every `log(...)` call with `lines.append(...)`, keeping the format strings exactly as they are. Add the accumulator as the first statement of the function body, seeded with the lede warning so it stays with its site's block:

```python
    lines = [] if lede else ["  no lede -- the body will open with TKTK placeholders"]
```

Change the return to:

```python
    return len(rows), extracted, stored, duplicates, problems, lines
```

Leave the module-level `log` function alone — the main loop still uses it.

- [ ] **Step 2: Add the result type and the wrapper**

Add `from collections import namedtuple` to the imports, and above `main`:

```python
Result = namedtuple("Result", "a_id found parsed stored dupes problems error lines")


def run_site(browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title):
    log("  -> %s %s" % (a_id, url))  # one interleaved line so a long run shows what is in flight
    begun = time.time()
    head = ["", "%s %s" % (a_id, url)]
    try:
        found, parsed, stored, dupes, problems, lines = scrape_site(
            browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title)
    except Exception as e:
        why = "%s: %s" % (type(e).__name__, e)
        return Result(a_id, 0, 0, 0, 0, [], why, head + ["  ERROR " + why])
    lines.append("  %s done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                 % (a_id, time.time() - begun, found, parsed, stored, dupes))
    return Result(a_id, found, parsed, stored, dupes, problems, None, head + lines)
```

- [ ] **Step 3: Add the main-thread absorber**

Everything that touches SQLite, the report or stdout lives here and nowhere else. Add above `main`:

```python
def absorb(r, store, report):
    if r.error:
        store.record_result(r.a_id, False)
        report.error(r.a_id, r.error)
    else:
        # links but nothing parsed means the selectors have gone stale
        healthy = r.found > 0 and r.parsed > 0
        store.record_result(r.a_id, healthy)
        report.site(r.a_id, r.found, r.parsed, r.stored, r.dupes)
        if not healthy:
            report.problem(r.a_id, "found=%s parsed=0" % r.found)
        for problem in r.problems:
            report.problem(r.a_id, problem)
    for line in r.lines:
        log(line)
```

- [ ] **Step 4: Rewrite the site loop to use them**

Replace the body of the `with Browser() as browser:` block in `main` with:

```python
    with Browser() as browser:
        for a_id, url in sites:
            recipe = store.get_recipe(a_id)
            if not recipe:
                log("")
                log("%s %s" % (a_id, url))
                log("  no recipe -- run build_recipes.py --id %s" % a_id)
                report.skip(a_id, "no recipe")
                continue
            if store.is_failed(a_id):
                log("")
                log("%s %s" % (a_id, url))
                log("  marked failed, skipping -- use --retry-failed")
                report.skip(a_id, "marked failed, skipped")
                continue
            lede = ledes.get(a_id)
            if not lede:
                report.no_lede()
            absorb(run_site(browser, conn, a_id, url, recipe, cutoff, lede,
                            patterns_for(strips, a_id), patterns_for(strips, a_id, "title")),
                   store, report)
```

- [ ] **Step 5: Run the suite and a short live run**

Run: `python -m pytest -q`
Expected: PASS.

```bash
python scrape.py --limit 3
```

Expected: output reads as it did before, one block per site in list order, each block now preceded by its own `  -> <a_id> <url>` line.

- [ ] **Step 6: Commit**

```bash
git add scrape.py
git commit -m "Return a per-site result instead of printing from the site work"
```

---

### Task 8: Run host groups across worker threads

Each worker owns a browser and a MySQL connection for its whole life, because Chrome startup costs several seconds and must not be paid per site. The main thread keeps SQLite, the report and all block printing, so nothing needs a lock.

**Files:**
- Modify: `scrape.py`
- Modify: `scraper/config.py`

**Interfaces:**
- Consumes: `by_host` from Task 6; `Result`, `run_site` and `absorb` from Task 7.
- Produces: `worker(jobs, results)` in `scrape.py`, and a `--workers` flag defaulting to `config.WORKERS`.

- [ ] **Step 1: Add the default**

In `scraper/config.py`, next to `MAX_FAILURES`:

```python
WORKERS = 4
```

- [ ] **Step 2: Add the flag and the imports**

In `scrape.py`, add to the imports:

```python
import queue
import threading
```

Change `from scraper.sites import load_sites` to `from scraper.sites import by_host, load_sites`. Add the argument next to the others in `main`:

```python
    ap.add_argument("--workers", type=int, default=config.WORKERS)
```

- [ ] **Step 3: Add the worker**

Above `main`:

```python
def worker(jobs, results):
    try:
        with Browser() as browser:
            conn = articles.connect()
            try:
                while True:
                    try:
                        group = jobs.get_nowait()
                    except queue.Empty:
                        return
                    for job in group:
                        results.put(run_site(browser, conn, *job))
            finally:
                conn.close()
    except Exception as e:
        log("worker stopped: %s: %s" % (type(e).__name__, e))
```

- [ ] **Step 4: Replace the site loop with a queue and threads**

`main` no longer opens a `Browser` or a MySQL connection of its own — the workers do. Delete `conn = articles.connect()` and its matching `conn.close()` from `main`, and replace the whole `with Browser() as browser:` block with:

```python
    jobs = queue.Queue()
    ready = []
    for a_id, url in sites:
        recipe = store.get_recipe(a_id)
        if not recipe:
            log("")
            log("%s %s" % (a_id, url))
            log("  no recipe -- run build_recipes.py --id %s" % a_id)
            report.skip(a_id, "no recipe")
            continue
        if store.is_failed(a_id):
            log("")
            log("%s %s" % (a_id, url))
            log("  marked failed, skipping -- use --retry-failed")
            report.skip(a_id, "marked failed, skipped")
            continue
        lede = ledes.get(a_id)
        if not lede:
            report.no_lede()
        ready.append((a_id, url, recipe, cutoff, lede,
                      patterns_for(strips, a_id), patterns_for(strips, a_id, "title")))
    for group in by_host(ready):
        jobs.put(group)

    results = queue.Queue()
    threads = [threading.Thread(target=worker, args=(jobs, results))
               for _ in range(args.workers)]
    for t in threads:
        t.start()
    # a worker that dies must not hang the drain, so watch the threads rather than a count
    while any(t.is_alive() for t in threads) or not results.empty():
        try:
            r = results.get(timeout=0.5)
        except queue.Empty:
            continue
        absorb(r, store, report)
    for t in threads:
        t.join()
```

`by_host` reads `site[1]` as the url, and these tuples keep the url in position 1, so it groups correctly without change.

- [ ] **Step 5: Verify one worker still behaves like before**

Run: `python -m pytest -q`
Expected: PASS.

```bash
python scrape.py --limit 3 --workers 1
```

Expected: identical output to Task 7 Step 5 — one browser, list order, same blocks.

- [ ] **Step 6: Verify several workers**

```bash
python scrape.py --limit 6 --workers 3
```

Expected: three Chrome processes, blocks arriving in completion order rather than list order, each block internally intact, and a total wall clock near a third of the `--workers 1` time for the same six sites.

- [ ] **Step 7: Commit**

```bash
git add scrape.py scraper/config.py
git commit -m "Run host groups across worker threads"
```

---

### Task 9: The Phase 2 gate

Parallelism changes when sites run, never what they parse. The per-site numbers must match Task 5's.

**Files:** none modified.

**Interfaces:**
- Consumes: `before.txt` as rewritten at the end of Task 5.
- Produces: a go/no-go for Task 10.

- [ ] **Step 1: Run the full list under workers**

```bash
python scrape.py --workers 4 > after.txt 2>&1
```

- [ ] **Step 2: Diff the counts**

```bash
sed -nE 's/^  ([0-9]+) done in [0-9]+s -- (found=[0-9]+ parsed=[0-9]+).*$/\1 \2/p' after.txt | sort > after-counts.txt
diff before.txt after-counts.txt
```

Expected: no output. A site that parses fine at `--workers 1` and fails at `--workers 4` points at contention rather than selectors — most likely two entries on one host that `by_host` did not group, so check `urlparse(...).netloc` for those two urls.

- [ ] **Step 3: Confirm the report totals still add up**

```bash
grep -A4 "^summary" after.txt
```

Expected: `ran + skipped + errored` equals the site count on the first line. A shortfall means a worker died and its sites produced no result — look for a `worker stopped:` line.

- [ ] **Step 4: No commit**

Nothing changed.

---

### Task 10: Document the flag and the Linux display

`Browser` has no Xvfb path — `OFFSCREEN` is Windows-only and `None` elsewhere — so a headless Linux server has no display on which to park a headed Chrome, and headless mode is detectable per `research/webdriver-choice.md`. The fix is deployment rather than code.

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the `--workers` flag from Task 8.
- Produces: nothing in code.

- [ ] **Step 1: Confirm xvfb-run actually works on the server**

This is untested. Run it on the target machine before documenting it as the answer:

```bash
xvfb-run python scrape.py --limit 2 --workers 2
```

Expected: `parsed` greater than zero on both sites. If Chrome fails to start, do not document this — report back instead, because the alternative is adding an `xvfb=True` path to `Browser`, and that is a code change outside this plan.

- [ ] **Step 2: Document the flag**

In `README.md`, add to the list of run flags under "Run Commands":

    - --workers n (sites in parallel, default 4; use 1 to run one at a time)

- [ ] **Step 3: Document the Linux display and the sizing**

Add a section to `README.md` after "Run Commands". Its literal text, with the fenced block written as a real fenced block:

    ## Running on a Linux server
    Chrome has to run headed -- headless is detectable -- so a server with no
    display needs a virtual one. There is no code change for this:

    (fenced bash block containing: xvfb-run python scrape.py --workers 6)

    Worker count is bounded by Chrome, not by Python. Each browser is roughly
    300-500MB and bursts a core while rendering.

    | Server | Workers |
    |---|---|
    | 4 vCPU / 8GB | 4 |
    | 8 vCPU / 16GB | 8 |

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document the workers flag and running under xvfb"
```
