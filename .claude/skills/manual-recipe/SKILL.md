---
name: manual-recipe
description: Use after build_recipes.py has already run and failed - it reported no recipe for a site, or the recipe it stored makes scrape.py report found=N parsed=0, repeated headlines or wrong dates - and the selectors have to be written by hand.
---

# Writing a recipe by hand

This is the fallback for sites `build_recipes.py` could not do. It asks Haiku for
a site's selectors and checks them across several articles. When it cannot get a
set that works, or when the set it saved turns out to be wrong, you write the
selectors yourself and run the same checks.

**Do not run `build_recipes.py` from this skill.** You are here because it already
ran and failed, and running it again just re-asks Haiku for the same site: it
skips sites that already have a recipe, and re-fails the ones that do not.
Importing helpers from it, as steps 5 and 7 do, is not running it.

Nothing here changes the repo. Every snippet goes in your scratchpad and reads
cached HTML from there.

## Working a batch

`test-sites.csv` is the queue: `a_id,url`, one site per line. Add sites there,
not in chat. `load_sites` reads that file, and a url retyped into a message
produces fetch errors that look like site problems.

You get here holding what `build_recipes.py` printed at the end of its run, the
manual work list:

```
no recipe for 3 site(s):
  17823 no article links found
  39916 selectors matched no sample article (tried 3)
```

Ask for that block if it is not in the chat. The ids and their reasons are what
step 2 starts from.

To see what is left at any point:

```python
import csv, sqlite3
have = {r[0] for r in sqlite3.connect("recipes.db").execute("SELECT a_id FROM recipe")}
print([int(r[0]) for r in csv.reader(open("test-sites.csv")) if r and int(r[0]) not in have])
```

Three or four sites per chat. Each one caches a listing skeleton and seven
article skeletons, tens of thousands of characters each. Start a fresh chat
rather than let the context fill.

## 1. What a recipe is

`Recipe` (`scraper/recipe.py`) is the whole contract. Nothing else is stored.

| field | what it is | read by |
|---|---|---|
| `item_selector` | the repeating row or card, one per article | `find_items` |
| `link_selector` | the anchor to the article | `find_items` |
| `url_filter` | plain substring every article url contains | `find_items` |
| `headline_selector` | the headline | `extract`, or `find_items` in listing mode |
| `date_selector` | the date | `extract`, or `find_items` in listing mode |
| `headline_fallback` | broader headline selector, tried only when the first finds nothing | `extract` |
| `date_fallback` | same, for the date | `extract` |
| `headline_on_listing` | read the headline from the listing row, never the article | `find_items` |
| `date_on_listing` | same, for the date | `find_items` |
| `dayfirst` | the site writes `03/09` as 3 September | `_parse_date` |
| `boilerplate` | tail lines repeated across articles, stripped from the body | `body.clean` |

Both readers live in `scraper/parse.py`.

## 2. Start from the failure

Read the reason before touching a selector.

| what you saw | suspect |
|---|---|
| `no article links found` | `item_selector`, `link_selector`, `url_filter` |
| `selectors matched no sample article` | `headline_selector`, `date_selector`, or no body |
| `headline ... is the same on every article` | `headline_selector` is a site banner |
| `worked on only N of M other articles` | a selector tied to one page, usually a per-post class or id |
| `found=N parsed=0` from `scrape.py` | the site changed; recheck every selector |
| `repeated headline(s)` from `scrape.py` | `headline_selector` is a site banner |
| headlines end in `...` or `…` | the listing truncates them; read the headline from the article |
| articles skipped as older than cutoff | `date_selector` points at the wrong element |

If a recipe is already stored, start from it rather than from nothing:

```python
import json, sqlite3
print(json.dumps(json.loads(sqlite3.connect("recipes.db").execute(
    "SELECT json FROM recipe WHERE a_id = ?", (632,)).fetchone()[0]), indent=1))
```

## 3. Cache the pages first

Fetches are slow, run a real Chrome window, and are throttled by
`config.REQUEST_DELAY`. Hit the site once, then work off the files.

Every snippet below starts with the same four lines. Set them once.

```python
import json, os, sys
sys.path.insert(0, ".")            # every snippet runs from the project root
A_ID, URL = 632, "https://www.collins.senate.gov/newsroom/press-releases"
WORK = r"<your scratchpad>\632"    # anywhere outside the repo
```

`URL` is the site's row in `test-sites.csv`.

```python
from scraper.browser import Browser
from scraper.llm import skeleton

os.makedirs(WORK, exist_ok=True)
with Browser() as browser:
    html = browser.get(URL)
for name, text in (("listing.html", html), ("listing.skel.html", skeleton(html))):
    with open(os.path.join(WORK, name), "w", encoding="utf-8") as f:
        f.write(text)
    print("%s  %d chars" % (name, len(text)))
```

A Chrome window opens. Headless never clears Cloudflare, so on Windows it is
parked off-screen. Leave it alone.

Read `listing.skel.html`, not `listing.html`. `skeleton` drops scripts and
styles, keeps only `class`, `id`, `href` and `datetime`, and cuts text over 80
characters, marking where it cut with ` [cut]`. It is what the model saw. That
mark is the tool's, not the site's, so never read truncation off the skeleton.

Do not read it whole. The repeating row shows up as a class appearing about once
per article:

```python
import collections, re

skel = open(os.path.join(WORK, "listing.skel.html"), encoding="utf-8").read()
counts = collections.Counter(t for a in re.findall(r'class="([^"]+)"', skel) for t in a.split())
for cls, n in counts.most_common(20):
    print("%4d  %s" % (n, cls))
```

Split on whitespace, not on the whole attribute. On a page of 20 articles the row
wrapper, the link, the headline and the date all land on 20. A token like
`js-trigger-9` that appears once is tied to one page, and those are the classes
step 6 tells you never to use.

## 4. Find the rows and the links

Write `WORK\recipe.json`. Start with the three link fields and leave the rest.

```json
{
  "item_selector": "li.PageList__item",
  "link_selector": "a.HoverLink",
  "url_filter": "/newsroom/",
  "headline_selector": "",
  "date_selector": "",
  "headline_fallback": "",
  "date_fallback": "",
  "headline_on_listing": false,
  "date_on_listing": false,
  "dayfirst": false,
  "boilerplate": []
}
```

Then check it against the cached listing:

```python
from bs4 import BeautifulSoup
from scraper import config  # importing it makes stdout utf-8, so odd characters cannot crash the print
from scraper.parse import find_items, set_dayfirst
from scraper.recipe import Recipe

recipe = Recipe(**json.load(open(os.path.join(WORK, "recipe.json"), encoding="utf-8")))
html = open(os.path.join(WORK, "listing.html"), encoding="utf-8").read()
if recipe.date_on_listing and set_dayfirst(recipe, [BeautifulSoup(html, "html.parser")]):
    print("numeric dates on this site read day first")
rows = find_items(html, URL, recipe)
print("%d row(s)" % len(rows))
for row in rows[:8]:
    print("  %-64s | %s | %s" % (row["url"][:64], (row["headline"] or "-")[:36], row["date"]))
missing = [f for f in ("headline", "date")
           if getattr(recipe, f + "_on_listing") and not all(r[f] for r in rows)]
if missing:
    print("EMPTY ON SOME ROWS: %s -- those articles would be dropped" % ", ".join(missing))
cut = [r for r in rows if (r["headline"] or "").rstrip().endswith(("...", "…"))]
if cut:
    print("TRUNCATED ON %d ROW(S): %r" % (len(cut), cut[0]["headline"][-40:]))
```

Edit `recipe.json` and rerun until the count matches the articles on the page and
the urls are all articles. Navigation, category and pagination links mean
`link_selector` is too broad or `url_filter` is missing.

## 5. Cache a few article pages

```python
import time
from build_recipes import CANDIDATES, VERIFY
from scraper import config
from scraper.browser import Browser
from scraper.llm import skeleton
from scraper.parse import find_items
from scraper.recipe import Recipe

recipe = Recipe(**json.load(open(os.path.join(WORK, "recipe.json"), encoding="utf-8")))
listing = open(os.path.join(WORK, "listing.html"), encoding="utf-8").read()
urls = [r["url"] for r in find_items(listing, URL, recipe)][:CANDIDATES + VERIFY]
pages = {}
with Browser() as browser:
    for n, url in enumerate(urls, 1):
        time.sleep(config.REQUEST_DELAY)
        html = browser.get(url)
        pages[url] = "article%d.html" % n
        for name, text in ((pages[url], html), ("article%d.skel.html" % n, skeleton(html))):
            with open(os.path.join(WORK, name), "w", encoding="utf-8") as f:
                f.write(text)
        print("article%d  %6d chars  %s" % (n, len(html), url[:60]))
json.dump(pages, open(os.path.join(WORK, "pages.json"), "w", encoding="utf-8"), indent=1)
```

Seven pages, because that is what the checks in step 7 compare against.

## 6. Headline and date

Prefer the listing. If every row already shows the headline and the date, set
`headline_on_listing` and `date_on_listing` and point the selectors at elements
inside a row. The article page is then never parsed for them.

A headline the listing cuts short, ending in `...` or `…`, is not a headline. The
whole one exists only on the article page, so leave `headline_on_listing` false
and write `headline_selector` against the article even when every row shows a
title. The `TRUNCATED ON N ROW(S)` line in step 4 is the warning. Rows carry the
date in full, so `date_on_listing` can still stay true.

Otherwise write selectors against `article1.skel.html` and confirm they hold on
`article2` onward. The rules are the ones the model prompts already enforce
(`scraper/llm.py`):

- Never `:contains()`. Never a month, a year or any text from one article.
- Never a class or id tied to one page, such as `post-14410` or `entry-9823`.
- Avoid `nth-child` and `nth-of-type` unless nothing else identifies the element.
- Prefer a `<time>` element or one carrying a `datetime` attribute.
- A relative time such as "2 hours ago" or "Yesterday" is a date element.
  `_relative` in `scraper/parse.py` reads it.
- With no date element, press releases open with a dateline like
  `BRUNSWICK, ME - September 4, 2026`, often in `<strong>` or `<b>`. Point at it.
  Failing that, `extract` reads a date out of the url.
- A fallback is a little broader than the precise selector: the same container
  with two or three likely tags. Never `div`, `span` or `*`. A broad date
  fallback finds unrelated dates elsewhere on the page.

## 7. Run the checks the automatic path runs

This imports the real checks. Do not restate them.

```python
from dataclasses import asdict
from build_recipes import (MIN_PASSES, is_banner, learn_boilerplate, show_sample,
                           verify_elsewhere)
from scraper import config
from scraper.lede import load_ledes
from scraper.parse import extract, find_items
from scraper.recipe import Recipe
from scraper.strip import load_strips, patterns_for

recipe = Recipe(**json.load(open(os.path.join(WORK, "recipe.json"), encoding="utf-8")))
pages = json.load(open(os.path.join(WORK, "pages.json"), encoding="utf-8"))
fetch = lambda url: open(os.path.join(WORK, pages[url]), encoding="utf-8").read()

listing = open(os.path.join(WORK, "listing.html"), encoding="utf-8").read()
rows = {i["url"]: i for i in find_items(listing, URL, recipe) if i["url"] in pages}
found = list(rows)
strips = load_strips(config.STRIP_CSV)
drop = patterns_for(strips, A_ID)
drop_title = patterns_for(strips, A_ID, "title")
link = found[0]

item = extract(fetch(link), recipe, drop, link, rows[link], drop_title)
if not item:
    sys.exit("FAIL: no headline, date or body on %s" % link)
passed, total, bodies, heads = verify_elsewhere(fetch, recipe, found, link, drop, rows,
                                                drop_title)
print("matched on %d of %d other articles (need %d)" % (passed, total, min(MIN_PASSES, total)))
if is_banner(item["headline"], heads):
    sys.exit("FAIL: headline reads %r on every article -- it is a site banner"
             % item["headline"][:60])
if passed < min(MIN_PASSES, total):
    sys.exit("FAIL: selectors are tied to one page")
recipe.boilerplate = learn_boilerplate([item["body"]] + bodies)
for line in recipe.boilerplate:
    print("  boilerplate: %s" % line[:80])
item = extract(fetch(link), recipe, drop, link, rows[link], drop_title)
show_sample(item, load_ledes(config.LEDES_CSV).get(A_ID), link)
json.dump(asdict(recipe), open(os.path.join(WORK, "recipe.json"), "w", encoding="utf-8"), indent=1)
print("PASS")
```

It writes the learned `boilerplate` and `dayfirst` back into `recipe.json`, so
what you save is what passed.

Read the sample record before you believe it. The headline must be the article's
own, the date must be that article's date, and the body must start at the first
real paragraph. Boilerplate the check did not catch goes in `strip.csv`, not into
the recipe. One line per site, `<a_id>,<body>,<title>`: the body column drops any
article line containing the text, the title column cuts a fixed phrase such as
`Press Release:` off every headline, and `~` separates several patterns in either
column. Neither is guessed for you, so add the line and rerun this step.

## 8. Save

Only after PASS.

```python
from scraper import config
from scraper.recipe import Recipe
from scraper.store import Store

recipe = Recipe(**json.load(open(os.path.join(WORK, "recipe.json"), encoding="utf-8")))
store = Store(config.SQLITE_PATH, config.MAX_FAILURES)
store.save_recipe(A_ID, recipe)
store.db.execute("DELETE FROM failure WHERE a_id = ?", (A_ID,))
store.db.commit()
store.close()
print("saved", A_ID)
```

Stop here. Do not run `scrape.py` to prove it works: that inserts live rows into
`press_release`. The sample record is the verification.

## 9. Traps

All from `scraper/parse.py`. These cost the most time.

- `link_selector` is matched against the **whole page**, then intersected with the
  rows. Write it page-wide, not relative to a row.
- `headline_selector` and `date_selector` in listing mode are matched **inside a
  row**, and cannot match the row element itself. If the date sits on the `<li>`,
  a selector for that `<li>` finds nothing.
- Listing fields need an `item_selector`. Without one, every row comes back with
  `headline: None`.
- With `headline_on_listing` set, a row missing the headline drops that article.
  `extract` has no fallback in listing mode. The `EMPTY ON SOME ROWS` line in
  step 4 is the warning.
- `url_filter` is a plain substring. Not a regex, not a glob.
- `dayfirst` is re-derived from the page on every run, so hand-tuning it does
  nothing.
- A selector that throws is silently treated as matching nothing. Zero matches
  can mean bad syntax, not a bad guess.

## 10. When to stop and report

Some sites cannot be done with the current design. Say so and stop. Do not
reshape the recipe, and do not add fields to `Recipe`.

- **No body.** Body text always comes from `trafilatura` (`parse.py:_article_text`).
  There is no body selector. If trafilatura returns nothing for a site's
  articles, that site is out of reach.
- **Pagination.** One listing url per site, one page. No next-page follow, no
  "load more" click.
- **Login or paywall.**
- **No date anywhere.** Not in an element, not in the opening dateline, not in
  the url.
- **Articles that are PDFs.**

Name which limit you hit, and what you tried.

## 11. What to write in chat

The whole reply is these two sections, in this order.

**What happened.** A few plain sentences. How many sites you did, and anything a
reader would not guess: a date that had to come off the article page instead of
the listing, a `strip.csv` line and the reason for it, a listing that only holds
three articles. Common words, few selector names. Leave out the sites that went
the ordinary way.

**Sites that did not work.** One line each: the id, the site, and which limit
from step 10 you hit. Drop the whole section when every site passed.
