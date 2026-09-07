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


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
LLM_MODEL = os.environ.get("SCRAPER_LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_WORKSPACE_ID = os.environ.get("SCRAPER_LLM_WORKSPACE_ID")

SQLITE_PATH = "recipes.db"
SITES_CSV = "test-sites.csv"
LEDES_CSV = "ledes.csv"
REQUEST_DELAY = 2
DEFAULT_DAYS = 3
MAX_FAILURES = 3
WORKERS = 4
HEADLESS = False

STOP_AFTER_OLD = 3
STRIP_CSV = "strip.csv"
