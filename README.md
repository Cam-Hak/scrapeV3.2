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
- --days n
- --id xx
- --last x (gathers last x sites in the csv)
- --force (re runs recipe creation)

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
