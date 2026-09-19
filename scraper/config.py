import os
import sys

from dotenv import load_dotenv

load_dotenv()
# a character the console cannot encode must not be able to kill a run
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def mysql():
    return dict(
        host=os.environ["SCRAPER_DB_HOST"],
        port=int(os.environ.get("SCRAPER_DB_PORT", 3306)),
        user=os.environ["SCRAPER_DB_USER"],
        password=os.environ["SCRAPER_DB_PASSWORD"],
        database=os.environ["SCRAPER_TNS_DB"],
    )


def mail():
    return dict(
        host=os.environ["SCRAPER_MAIL_HOST"],
        port=int(os.environ.get("SCRAPER_MAIL_PORT", 587)),
        user=os.environ["SCRAPER_MAIL_USER"],
        password=os.environ["SCRAPER_MAIL_PASSWORD"],
        sender=os.environ["SCRAPER_MAIL_FROM"],
        to=os.environ["SCRAPER_MAIL_TO"],
        cc=os.environ.get("SCRAPER_MAIL_CC", ""),
    )


def headless():
    # read per call, so --headless reaches the isolated children through the environment
    return os.environ.get("SCRAPER_HEADLESS", "") == "1"


# the agencies column holding the lede template, named differently on some servers
LEDE_COLUMN = os.environ.get("SCRAPER_LEDE_COLUMN") or "lead"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
LLM_MODEL = os.environ.get("SCRAPER_LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_WORKSPACE_ID = os.environ.get("SCRAPER_LLM_WORKSPACE_ID")

# bump both when the desk should see a new version on the run summary
VERSION = "3.2.0"
VERSION_DATE = "09/15/2026"

SQLITE_PATH = "recipes.db"
SITES_CSV = "test-sites.csv"
REQUEST_DELAY = 2
DEFAULT_DAYS = 3
MAX_FAILURES = 3
WORKERS = 4

STOP_AFTER_OLD = 3
STRIP_CSV = "strip.csv"
KEYWORDS_CSV = "keywords.csv"

# a date further ahead than this is a parse error, not a scheduled release
MAX_DAYS_AHEAD = 7
# legacy reads "this many words or fewer: don't load", so the short band starts one above
MIN_WORDS = 100
SHORT_DOC = 150

# run history, written next to recipes.db -- see scraper/history.py
RUNS_LOG = "runs.jsonl"
RUN_SITES_LOG = "run_sites.jsonl"

# give up when no worker has finished a site in this long -- a page load has
# no timeout of its own, so one unresponsive site can otherwise hang the run
STALL_LIMIT = 600

# hard ceiling on one site when each runs in its own process (scraper/isolate.py)
SITE_TIMEOUT = 180
