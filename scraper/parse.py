from datetime import date as date_type, datetime, timedelta
from urllib.parse import urljoin

import re

import html2text
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta

from .body import clean as clean_body
from .strip import clean_title

SENTINELS = (datetime(2000, 1, 1), datetime(2001, 2, 2))
DATE_TEXT = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}")
DATELINE_BLOCKS = 4
YEAR_FIRST = re.compile(r"\s*\d{4}[-/]")
NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?!\d)")
AGO = re.compile(r"(?<![-\w])(?:(\d+)|an?)\s*"
                 r"(second|sec|minute|min|hour|hr|day|week|month|year)s?\.?\s+ago\b"
                 r"[\s.,|·-]*$")
AGO_UNITS = {"second": "seconds", "sec": "seconds", "minute": "minutes",
             "min": "minutes", "hour": "hours", "hr": "hours", "day": "days",
             "week": "weeks", "month": "months", "year": "years"}
CLOCK = re.compile(r"[\s,|·-]*(?:at\s+)?\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?"
                   r"(?:\s+[a-z]{2,5})?$")
DAY_WORD = re.compile(r"\b(today|yesterday|just now)\b[\s.,|·-]*$")
URL_DATE = re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|-|_|$)")
MD_ESCAPE = re.compile(r"\\([^\w\s])")


def find_links(html, base_url, recipe):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for tag in _select(soup, recipe.link_selector):
        href = tag.get("href")
        if not href:
            continue
        url = urljoin(base_url, href).split("#")[0]
        if not url.startswith(("http://", "https://")):
            continue
        if recipe.url_filter and recipe.url_filter not in url:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def find_items(html, base_url, recipe):
    # listing rows, carrying whichever fields the recipe reads from the listing
    if not recipe.item_selector:
        return [{"url": u, "headline": None, "date": None}
                for u in find_links(html, base_url, recipe)]
    soup = BeautifulSoup(html, "html.parser")
    # the model writes link_selector against the whole page, not one row
    wanted = {id(a) for a in _select(soup, recipe.link_selector)}
    items, seen = [], set()
    for node in _select(soup, recipe.item_selector):
        link = (next((a for a in node.find_all("a", href=True) if id(a) in wanted), None)
                or _one(node, recipe.link_selector) or node.find("a", href=True))
        href = link.get("href") if link else None
        if not href:
            continue
        url = urljoin(base_url, href).split("#")[0]
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        if recipe.url_filter and recipe.url_filter not in url:
            continue
        seen.add(url)
        items.append({
            "url": url,
            "headline": _text(node, recipe.headline_selector)
            if recipe.headline_on_listing else None,
            "date": _date(node, recipe.date_selector, recipe.dayfirst)
            if recipe.date_on_listing else None,
        })
    return items


def extract(html, recipe, drop=(), url=None, listing=None, drop_title=()):
    soup = BeautifulSoup(html, "html.parser")
    # the fallback is only consulted when the precise selector finds nothing
    known = listing or {}
    # a field the recipe reads from the listing is already settled
    headline = known.get("headline") or (
        None if recipe.headline_on_listing else
        _text(soup, recipe.headline_selector) or _text(soup, recipe.headline_fallback))
    date = known.get("date") or (
        None if recipe.date_on_listing else
        _date(soup, recipe.date_selector, recipe.dayfirst)
        or _date(soup, recipe.date_fallback, recipe.dayfirst))
    raw = _article_text(html)
    if raw and not date:
        date = _dateline(raw, recipe.dayfirst)
    if not date:
        date = _url_date(url)
    if not headline or not date or not raw:
        return None
    body, contact = clean_body(raw, headline, date,
                               list(recipe.boilerplate) + list(drop))
    if not body:
        return None
    # the title is cut last: clean_body drops the page's own title line by
    # matching it against the headline as the page wrote it
    return {"headline": clean_title(headline, drop_title), "date": date,
            "body": body, "contact": contact}


def date_texts(soup, selector):
    return [t.get("datetime") or t.get_text(" ", strip=True) for t in _select(soup, selector)]


def detect_dayfirst(texts):
    # a number above 12 can only be the day, and that settles how the site writes them
    first = second = 0
    for raw in texts:
        if not raw or YEAR_FIRST.match(raw):
            continue
        found = NUMERIC_DATE.search(raw)
        if found:
            first += int(found.group(1)) > 12
            second += int(found.group(2)) > 12
    if second:
        return False
    # reading a day-first site as month-first is the cheaper mistake, so this way
    # round needs corroboration: one odd-looking date is not enough to flip a site
    return True if first > 1 else None


def set_dayfirst(recipe, soups):
    """Take the site's date habit from its own digits. True when it changed."""
    settled = detect_dayfirst([t for s in soups for t in date_texts(s, recipe.date_selector)])
    if settled is None or settled == recipe.dayfirst:
        return False
    recipe.dayfirst = settled
    return True


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _article_text(html):
    # trafilatura picks the article out; html2text keeps its paragraph structure
    inner = trafilatura.extract(html, output_format="html")
    if not inner:
        return None
    reader = html2text.HTML2Text()
    reader.ignore_links = True
    reader.ignore_images = True
    reader.ignore_emphasis = True
    reader.body_width = 0
    # these pages wrap releases in a table, and cells render inline unless ignored
    reader.ignore_tables = True
    return MD_ESCAPE.sub(r"\1", reader.handle(inner))


def _select(soup, selector):
    try:
        return soup.select(selector)
    except Exception:
        return []


def _one(soup, selector):
    try:
        return soup.select_one(selector)
    except Exception:
        return None


def _text(soup, selector):
    tag = _one(soup, selector)
    return tag.get_text(" ", strip=True) if tag else None


def _date(soup, selector, dayfirst=False):
    tags = _select(soup, selector)
    for tag in tags:
        attr = tag.get("datetime")
        # inline markup can split a date, so retry with the separators stripped out
        for raw in ([attr] if attr else []) + [tag.get_text(" ", strip=True),
                                               tag.get_text("", strip=True)]:
            parsed = _parse_date(raw, dayfirst)
            if parsed:
                return parsed
    # "2 hours ago" is the weaker signal, so read it only if no tag held a real date
    for tag in tags:
        relative = _relative(tag.get_text(" ", strip=True))
        if relative:
            return relative
    return None


def _relative(text, now=None):
    # listings often print "2 hours ago" or "Yesterday" where a date would go
    now = now or datetime.now()
    # a trailing clock time is noise around the day word, not part of it
    words = CLOCK.sub("", (text or "").strip().lower()).strip()
    day = DAY_WORD.search(words)
    if day:
        return (now - timedelta(days=1 if day.group(1) == "yesterday" else 0)).date()
    found = AGO.search(words)
    if not found:
        return None
    count = int(found.group(1)) if found.group(1) else 1
    try:
        return (now - relativedelta(**{AGO_UNITS[found.group(2)]: count})).date()
    except (OverflowError, ValueError):
        return None


def _dateline(text, dayfirst=False):
    # press releases open with a dateline, so only the first blocks are trustworthy
    blocks = [b for b in text.split("\n") if b.strip()][:DATELINE_BLOCKS]
    for block in blocks:
        found = DATE_TEXT.search(block)
        if found:
            parsed = _parse_date(found.group(0), dayfirst)
            if parsed:
                return parsed
    return None


def _url_date(url):
    # many publishing systems put the publish date straight in the permalink
    found = URL_DATE.search(url or "")
    if not found:
        return None
    try:
        return date_type(*(int(g) for g in found.groups()))
    except ValueError:
        return None


def _parse_date(raw, dayfirst=False):
    # a leading 4-digit year always means year-month-day, whatever the site's habit is
    dayfirst = dayfirst and not YEAR_FIRST.match(raw or "")
    try:
        parsed = [dateparser.parse(raw, fuzzy=True, default=s, dayfirst=dayfirst)
                  for s in SENTINELS]
    except (ValueError, OverflowError, TypeError):
        return None
    # differing results mean the text never supplied those parts
    return parsed[0].date() if parsed[0] == parsed[1] else None
