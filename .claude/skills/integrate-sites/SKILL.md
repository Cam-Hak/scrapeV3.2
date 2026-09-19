---
name: integrate-sites
description: Use when a batch of new sites has been added to the end of test-sites.csv and they need recipes, a test run, document cleanup, and the failures dropped. Also the reference for what each build or output failure means and which tool fixes it.
---

# Integrating a batch of new sites

A batch is about 20 rows appended to `test-sites.csv`. Run all of it in one go. Do not
stop to ask between steps.

Every run uses `--headless`. Chrome windows popping up interrupt whatever is happening on
the machine.

## The loop

1. **Find the batch** — the rows with no recipe.
2. **Build the recipes** — `build_recipes.py`, then deal with what failed.
3. **Run them** — `scrape.py`, which writes to MySQL.
4. **Check and clean** — `check_output.py`, then `strip.csv` / `keywords.csv` / the recipe.
5. **Remove what cannot work**, and report the batch in one message.

---

## 1. Find the batch

```python
import csv, sqlite3
have = {r[0] for r in sqlite3.connect("recipes.db").execute("SELECT a_id FROM recipe")}
rows = [r for r in csv.reader(open("test-sites.csv")) if r]
new = [(int(r[0]), r[1].strip()) for r in rows if int(r[0]) not in have]
print(len(rows), "sites,", len(new), "new")
print(" ".join(str(a) for a, _ in new))
```

`test-sites.csv` is `a_id,url`, one site per line. The url is the listing page — one page,
no pagination, no "load more".

Sites reported for removal on an earlier batch should already be gone. If one is still
there, leave it out of the build rather than re-confirming it fails.

**Before building, check the site has a lede.** A site with no `leads` row in `agencies`
cannot build a document and will be skipped at run time:

```python
from scraper import articles
conn = articles.connect()
found = articles.load_agencies(conn, ids)
conn.close()
print("no lede:", [i for i in ids if not found.get(i, ("", ""))[1]])
```

## 2. Build the recipes

```bash
python build_recipes.py --headless --id <the new ids>
```

Twelve to fifteen minutes for twenty sites. Run it in the background and redirect to a
file — a `| tail` pipe buffers everything and hides progress until it exits.

A recipe is the `Recipe` dataclass in `scraper/recipe.py` and nothing else. The model is
asked for selectors, they are checked against seven cached articles, and the result is
saved to `recipes.db`. **Body text always comes from trafilatura — there is no body
selector.**

### What each failure means

| What it printed | What it means | What to do |
|---|---|---|
| `no article links found`, tiny skeleton (a few hundred chars) | the page rendered nothing | refetch headed; if the skeleton is the same size, the site is out of reach |
| `no article links found`, large skeleton | the model could not find the list | worth hand-writing |
| `skeleton 150000 chars -- TRUNCATED` | listing too big for the model to see the list | worth hand-writing |
| `selectors matched no sample article` | headline, date or body missing | recheck those selectors |
| `headline ... is the same on every article` | the headline selector is a site banner | point it at the article's own heading |
| `worked on only N of M` | a selector tied to one page, usually a per-post class | pick a stable class |

**Headless never clears Cloudflare.** A site that returns almost nothing under `--headless`
may only be blocked. Check before writing it off:

```python
from scraper.browser import Browser
from scraper.llm import skeleton
with Browser(headless=False) as b:
    html = b.get(url, patient=True)
print(len(html), len(skeleton(html)))
```

Same skeleton size headed means headless was not the problem.

Hand-write a recipe with the **manual-recipe** skill when the reason says the model failed
rather than the site. Do not hand-write one for a site whose listing renders nothing.

## 3. Run them

```bash
python scrape.py --headless --id <the built ids> --days 300 --max-articles 3
```

Three articles each over a wide window: enough to judge the documents, quick enough to
iterate. Read the per-site lines, not just the summary — `stored=0` and `parsed=0` mean
different things.

| Line | Meaning |
|---|---|
| `found=N parsed=0` | links found, nothing extracted — selectors have gone stale |
| `skipped on '<phrase>'` | a `keywords.csv` skip rule dropped it |
| `only N words -- dropped` | body at or under `MIN_WORDS` (100) |
| `is dated ahead -- dropped` | date more than `MAX_DAYS_AHEAD` (7) out — usually a parse error |
| `older than cutoff (N in a row)` | three in a row stops the site, so a misparsed date can cut a site short |

## 4. Check and clean

```bash
python check_output.py --id <each id>
```

**Read the actual body before acting on a flag.** Most flags are not junk:

| Flag | Usually |
|---|---|
| `mostly very short lines` | a real list — signatories, award categories, a meeting schedule, a data table |
| `one date for the whole site` | a genuine same-day cluster; confirm the listing has a spread behind it |
| `leftover: ...` | often real — check whether the phrase is a banner or part of a sentence |

A `[Category: ...]` line above the `* * *` is part of the lede template, not the body.

### Which tool fixes which problem

| Problem | Tool |
|---|---|
| a junk line in the body | `strip.csv` body column |
| a fixed phrase on every headline | `strip.csv` title column |
| a whole element — a cookie table, a sidebar, a trailing date | `strip.csv` prune column |
| an article that should not load at all | `keywords.csv` with `skip` |
| a good article being dropped by a keyword | `keywords.csv` veto column |
| wrong links, headline or date | the recipe |
| a consent widget on many sites | `parse.WIDGET_ROOTS` |

`strip.csv` is `a_id,body,title,prune`; `~` separates several patterns in a column; `*` as
the a_id applies to every site.

**Verify a rule by replaying it against the stored body**, not by rerunning the scrape,
which would only hit duplicates:

```python
from scraper import articles, config
from scraper.body import _dropped
from scraper.strip import load_strips, patterns_for
strips = load_strips(config.STRIP_CSV)
conn = articles.connect(); cur = conn.cursor()
cur.execute("SELECT pr_id,body_txt FROM press_release WHERE a_id=%s", (A_ID,))
for pr, b in cur.fetchall():
    core = b.split("* * *", 1)[1].rsplit("\n***", 1)[0]
    for line in core.split("\n"):
        if line.strip() and _dropped(line, patterns_for(strips, A_ID)):
            print(pr, "-", line[:90])
```

Check **what** it drops, not just that it drops something.

### Four traps that cost the most time

- **`_norm` strips punctuation before matching.** `@battelle.org` becomes `battelleorg`,
  which also matches any line mentioning `www.battelle.org` — including real prose.
  `Office:` becomes `office`, a common word. A pattern has to stay distinctive with every
  symbol removed. A punctuation-only pattern like `###` normalizes to nothing and is
  silently ignored.
- **Do not strip a `Media Contact` heading.** `body._split_contact` uses that heading as
  its anchor to move a trailing block into `contact_info`. Strip it and the phone numbers
  and emails stay in the body instead. Check `contact_info` first: if it is already NULL
  on every article, the splitter never fires there and stripping is safe.
- **A contact block at the top of an article stays.** `_split_contact` only takes a
  trailing block, deliberately, so a release that opens on one keeps its body. Those need
  `strip.csv`.
- **A keyword can mean something else on a given site.** `honor roll` at a children's
  hospital is the U.S. News ranking, not a school list. Add a veto rather than removing
  the site, and test both directions — the good article passes, the bad one still drops.

### Fixing a recipe rather than the output

Some problems are the listing, not the body. A listing that mixes an events rail into a
news feed gives dates that are not publication dates — a conference banner reading
`December 2 - 3, 2026` parses as **year 3**. Three of those in a row trips the stale
counter and stops the site before it reaches real news.

Scope the selector to the real feed, then validate before saving:

```python
from build_recipes import MIN_PASSES, is_banner, verify_elsewhere
passed, total, bodies, heads = verify_elsewhere(fetch, recipe, urls, link, drop, rows, dt)
```

Needs `passed >= min(MIN_PASSES, total)` and `is_banner` false. Save with
`Store.save_recipe`, and clear the site's `failure` row.

A listing with thousands of links is not automatically broken — some sites publish their
whole archive on one page. Check the urls are unique and real, and that the dates descend.
Newest-first means the stale counter stops the crawl after three old ones.

## 5. Remove what cannot work

Back the recipe JSON and the csv and strip rows up to the scratchpad first, so a site can
be restored by pasting rather than rebuilding:

```bash
python build_recipes.py --id <ids> --remove --headless
```

Never run this while a build is in flight — both write `recipes.db`, and a lock can kill
the build part way through.

`--remove` does not touch MySQL. Name any leftover `press_release` rows rather than
deleting them unasked.

### When a site cannot be made to work

Say so plainly and move on. Do not reshape the recipe or add fields to `Recipe`.

- Listing renders nothing, headed or headless.
- No article list findable, and the page is too large or too odd to hand-write.
- Articles are not press releases — link-out bulletins, or notices under the 100 word floor.
- Every release is wire copy the skip keywords drop by design, such as a newsroom where
  each item opens `/PRNewswire/`. That is the rule working, not a false positive.
- Junk no `strip.csv` rule can remove without deleting real text.
- Pagination, login, paywall, PDFs, or no date anywhere.

## 6. Report

One message: what worked, and what was removed with a reason per site.

| a_id | site | reason |
|---|---|---|

**Only this batch.** Never re-list sites from an earlier one.
