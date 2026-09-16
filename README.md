# ***Automated Scraper***

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate         # Windows -- source .venv/bin/activate on macOS
pip install -r requirements.txt
cp .env.example .env           # then fill it in
```
`.env` holds the MySQL credentials, the Anthropic API key and the mail settings. It is
gitignored, as is `.venv`. Activate the venv in every new shell before running anything
below.

Only the MySQL block is needed to scrape. `ANTHROPIC_API_KEY` is read by
`build_recipes.py` alone, and the `SCRAPER_MAIL_*` block by `--production` alone.

```bash
python -m pytest -q            # the test suite
```

## Run Commands
```bash
# to run standard scrape
python scrape.py

# to run site implementation agent
python build_recipes.py
```

### Picking sites
Both scripts take the same four selectors, read against `test-sites.csv`.

| Flag | Effect |
|---|---|
| `--id 18092 20260` | Only those site ids. Space-separated, any number of them. |
| `--from 20260` | Start at that id, run to the end of the file |
| `--last 10` | The last 10 rows |
| `--limit 5` | The first 5 rows |

`--from`, `--last` and `--limit` combine, applied in that order, so
`--from 20260 --limit 3` means three sites starting at 20260.

`--id` does not combine. It returns its matches immediately and ignores the other
three, so `--id 18092 --limit 5` silently runs one site.

### scrape.py only

| Flag | Effect |
|---|---|
| `--days n` | Keep articles from the last n days (default 3) |
| `--workers n` | Sites in parallel (default 4). Use 1 to run one at a time. |
| `--retry-failed` | Clear the failure streaks first, so sites benched after 3 bad runs are tried again |
| `--senate` | Run only the sites whose url carries `house` or `senate` |
| `--production` | Email the run summary when the run finishes |

`--senate` splits the file in two. With it you get the congressional sites and nothing
else; without it you get everything else and none of them, so the two runs together
cover the file exactly once. The words have to stand on their own, which is why
`lighthouse.mq.edu.au` is not a chamber. `--id` overrides the split the same way it
overrides the other selectors, so a site you name by id always runs.

`--production` reads the seven `SCRAPER_MAIL_*` settings in `.env`. They are read at
startup, so a missing one stops the run before it scrapes rather than after. The mail
itself is the last thing a run does, and a refused send is logged and nothing more —
the articles are already stored by then. `SCRAPER_MAIL_TO` and `SCRAPER_MAIL_CC` take
several addresses, separated by a comma or a semicolon.

### The run summary

Every run ends with the same block, printed to the console and sent as the body of the
`--production` email:

```
Load Version 3.2.0 09/15/2026
       Docs Loaded: 667
       URLS processed: 1869
       Articles read: 1026
       DUPS skipped: 843
       No Ledes found: 0
       Docs Sent To Box 4 Editor Box For Phrase: 9
       Docs Sent To Box 7 Repairs: 5
       Short Docs Sent To Box 7 Repairs: 3
       Article Description Too Short: 12
       Article Skipped Due to Keyword: 4
       Article Dated Ahead: 1

Passed Parameters:
       ...
```

`URLS processed` counts every link the listings offered; `Articles read` counts the ones
actually fetched and parsed, so the gap is what the duplicate pre-check saved. Counts
show even at zero, so a section going quiet is visible.

`VERSION` and `VERSION_DATE` live in `scraper/config.py` — bump both when the desk
should see a new version on the summary.

Sites are grouped by host, so two entries on one host never run at the same time
no matter how many workers you give it.

Ctrl-C stops a run. Workers finish the site they are on rather than abandoning it
half-written, so it can take a minute; you still get the summary.

### build_recipes.py only

| Flag | Effect |
|---|---|
| `--force` | Rebuild recipes that already exist, instead of skipping them |
| `--remove` | Drop the selected sites everywhere and exit, building nothing: their recipe and failure streak in `recipes.db`, their row in `test-sites.csv`, and their rows in `strip.csv`. Needs one of the four selectors above; it refuses to run against the whole file. `ledes.csv` is left alone, because its entries span several lines. |

## Keyword routing -- `keywords.csv`

Every stored doc starts at status `D`. `keywords.csv` can drop it instead, or route it to an
editor box and leave a note in the `headline2` column.

| Column | Meaning |
|---|---|
| `field` | `body` or `headline` -- which text is searched |
| `phrase` | literal text, never a regex |
| `action` | `skip` drops the whole article, `E` and `W` set the status, blank only adds a comment |
| `comment` | blank uses the standard wording, otherwise this exact text |
| `marker` | routing code appended after the doc's url, read only on `body` + `E` rows |
| `whole` | `y` when the phrase must stand as its own word |
| `veto` | words that cancel the match, split on `~`, always matched whole-word |

Checks run body `E`, body `W`, headline `E`, headline `W`, then the comment-only rows. The last
check that matches wins the status and the comments accumulate, so a doc can carry several. A
body under `MIN_WORDS` is dropped before any of this; one between `MIN_WORDS` and `SHORT_DOC` is
stored as `W` with a `short doc` note.

`honor roll` appears twice on purpose: in the body it drops the article, in the headline it only
routes to `W`. That is why `field` is a column.

Date-field keywords are **not** supported. The legacy scraper searched the raw scraped date
string for section labels like `Commentary`; this one never keeps that string, because a date
selector that returns a label parses as nothing and the date is taken from the dateline or the
url instead.

## Running on a Linux server

Chrome has to run headed — headless is detectable — so a server with no display needs a virtual one. There is no code change for this:

```bash
xvfb-run python scrape.py --workers 6
```

Worker count is bounded by Chrome, not by Python. Each browser is roughly 300-500MB and bursts a core while rendering. **This section is untested; a human will verify it on the target server.**

| Server | Workers |
|---|---|
| 4 vCPU / 8GB | 4 |
| 8 vCPU / 16GB | 8 |

### On a schedule

Two runs a day, the congressional sites and the rest, an hour apart so they never start
Chrome at the same time:

```
0 4 * * *  cd /www/coder.tns/scrapeV3.2 && xvfb-run .venv/bin/python scrape.py --senate --days 2 --production
0 5 * * *  cd /www/coder.tns/scrapeV3.2 && xvfb-run .venv/bin/python scrape.py --days 2 --production
```

Repeating a day is harmless: the `filename` column is unique, so an article already
loaded is counted as a duplicate rather than stored again, and a site whose articles
were all duplicates is not treated as broken.

**`recipes.db` is committed, and a run writes to it** — every site's pass/fail streak
lands there. A deploy that pulls has to overwrite rather than merge:

```bash
git fetch origin && git reset --hard origin/main
```

That discards the streaks, which rebuild over three runs. Nothing else a run writes is
tracked: `runs.jsonl`, `run_sites.jsonl` and `*.log` are all gitignored.

## DB Commands
*If sqlite3 isn't installed run one of these commands*

**powershell**
```bash
winget install SQLite.Viewer
```
**MacOS w/ Homebrew**
```bash
brew install sqlite
```

*Ex. to look at recipes.db*
```bash
sqlite3 recipes.db
```
- .tables (to view tables)
- .schema table_name (look at col names)
- .mode --charlimit 0 (allow longer data dumps)
- .mode --linelimit 0 (allow longer data dumps)
*Ex. to check recipe for a particular id*
```bash
select * from recipe where a_id = 29288;
```
