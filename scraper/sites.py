import csv
import re
from urllib.parse import urlparse

# whole words, so lighthouse.mq.edu.au is not a chamber -- "_" separates too
CONGRESS = re.compile(r"(?<![a-z0-9])(house|senate)(?![a-z0-9])", re.I)


def congress(url):
    return bool(CONGRESS.search(url))


def load_sites(path, only=None, start=None, limit=None, last=None, senate=None):
    with open(path) as f:
        rows = [(int(row[0]), row[1].strip()) for row in csv.reader(f) if row]
    if only:
        return [r for r in rows if r[0] in only]
    # the two halves run on their own schedules, so a run takes one side or the other
    if senate is not None:
        rows = [r for r in rows if congress(r[1]) == senate]
    if start is not None:
        at = [i for i, r in enumerate(rows) if r[0] == start]
        rows = rows[at[0]:] if at else []
    if last:
        rows = rows[-last:]
    if limit:
        rows = rows[:limit]
    return rows


def _host(url):
    netloc = urlparse(url).netloc.lower().split(":")[0]
    return netloc[4:] if netloc.startswith("www.") else netloc


def by_host(sites):
    groups = {}
    for site in sites:
        groups.setdefault(_host(site[1]), []).append(site)
    return list(groups.values())
