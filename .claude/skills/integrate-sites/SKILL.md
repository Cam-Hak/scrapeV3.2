---
name: integrate-sites
description: Use when a batch of new sites has been added to the end of test-sites.csv and they need recipes, a test run, document cleanup, and a list of the ones to drop. Runs the whole batch end to end without checking in between steps.
---

# Integrating a batch of new sites

A batch is about 20 rows appended to `test-sites.csv`. Run all of it in one go. Do not
stop to ask between steps.

Every run uses `--headless`. Chrome windows popping up interrupt whatever is happening on
the machine.

## 1. Find the batch

The new rows are the ones with no recipe.

```python
import csv, sqlite3
have = {r[0] for r in sqlite3.connect("recipes.db").execute("SELECT a_id FROM recipe")}
rows = [r for r in csv.reader(open("test-sites.csv")) if r]
new = [(int(r[0]), r[1].strip()) for r in rows if int(r[0]) not in have]
print(len(rows), "sites,", len(new), "new")
print(" ".join(str(a) for a, _ in new))
```

Every site reported for removal on an earlier batch has already been removed. If one is
still in the file, it is a new site that happens to share the problem, not a leftover.

## 2. Build the recipes

```bash
python build_recipes.py --headless --id <the new ids>
```

Twelve minutes for twenty sites. Run it in the background and redirect to a file — a
`| tail` pipe buffers everything and hides progress until it exits.

It prints its failures at the end. Read the reason before deciding anything.

**A site that comes back with a tiny skeleton may just be blocked.** Headless never clears
Cloudflare. Before calling such a site broken, refetch it with `Browser(headless=False)` and
compare the skeleton size. Same size means headless was not the problem.

Hand-write a recipe with the **manual-recipe** skill when the reason says the model failed
rather than the site: a listing over the 150k skeleton limit, or a page whose article list is
there but was not found. Do not hand-write one for a site whose listing renders nothing.

## 3. Run them

```bash
python scrape.py --headless --id <the built ids> --days 300 --max-articles 3
```

Three articles each over a wide window: enough to see whether the documents are right,
small enough to be quick. This writes to MySQL.

## 4. Clean the documents

```bash
python check_output.py --id <each id>
```

It flags leftovers, short bodies and dates that disagree with the url. **Read the actual
body before acting on a flag** — a signatory list reads as "mostly very short lines" and is
not junk, and a `[Category: ...]` line above the `* * *` is part of the lede template, not
the body.

Fix what is fixable in `strip.csv`, then verify the rule by replaying it against the stored
body rather than rerunning the scrape, which would only hit duplicates:

```python
from scraper import articles, config
from scraper.body import _dropped
from scraper.strip import load_strips, patterns_for
strips = load_strips(config.STRIP_CSV)
conn = articles.connect(); cur = conn.cursor()
cur.execute("SELECT pr_id,body_txt FROM press_release WHERE a_id=%s", (A_ID,))
for pr, b in cur.fetchall():
    core = b.split("* * *", 1)[1].rsplit("\n***", 1)[0]
    drop = patterns_for(strips, A_ID)
    for line in core.split("\n"):
        if line.strip() and _dropped(line, drop):
            print(pr, "-", line[:90])
```

Check what it drops, not just that it drops something. The stored document includes the
`Original text here:` footer, which the strip never sees in the real pipeline, so ignore
matches on that line.

### Three traps

- **`_norm` strips punctuation before matching.** `@battelle.org` becomes `battelleorg` and
  matches any line mentioning `www.battelle.org`, including real paragraphs. `Office:`
  becomes `office`, a common word. Write patterns that still read as distinctive with every
  symbol removed.
- **Do not strip a `Media Contact` heading.** `body._split_contact` uses that heading as its
  anchor to move a trailing block into `contact_info`. Strip it and the phone numbers and
  emails stay in the body instead.
- **A contact block at the top of an article stays.** `_split_contact` only takes a trailing
  block, on purpose. Use `strip.csv` for those.

When text cannot do it safely, look for a class to `prune` instead: fetch one article, find
the element wrapping the junk, and add it to the fourth column.

## 5. Remove what did not work, then report

Remove them yourself. Back the recipe JSON and the csv and strip rows up to the scratchpad
first, so a site can be restored by pasting rather than rebuilding:

```bash
python build_recipes.py --id <ids> --remove --headless
```

Never run this while a build is in flight — both write `recipes.db`, and a lock can kill
the build part way through.

`--remove` does not touch MySQL. Name any leftover `press_release` rows rather than
deleting them unasked.

Then one message: what worked, and what was removed with a reason per site.

| a_id | site | reason |
|---|---|---|

**Only this batch.** Never re-list sites from an earlier one.

## When a site cannot be made to work

Say so plainly and move on. Do not reshape the recipe or add fields to `Recipe`.

- Listing renders nothing, headed or headless.
- No article list the builder can find, and the page is too large or too odd to hand-write.
- Articles are not press releases — link-out bulletins or notices under the 100 word floor.
- Junk that no `strip.csv` rule can remove without deleting real text.
