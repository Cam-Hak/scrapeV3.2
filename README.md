# ***Automated Scraper***

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate         # Windows -- source .venv/bin/activate on macOS
pip install -r requirements.txt
cp .env.example .env           # then fill it in
```
`.env` holds the MySQL credentials and the Anthropic API key. It is gitignored, as
is `.venv`. Activate the venv in every new shell before running anything below.

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

Sites are grouped by host, so two entries on one host never run at the same time
no matter how many workers you give it.

Ctrl-C stops a run. Workers finish the site they are on rather than abandoning it
half-written, so it can take a minute; you still get the summary.

### build_recipes.py only

| Flag | Effect |
|---|---|
| `--force` | Rebuild recipes that already exist, instead of skipping them |

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
