import csv
from urllib.parse import urlparse


def load_sites(path, only=None, start=None, limit=None, last=None):
    with open(path) as f:
        rows = [(int(row[0]), row[1].strip()) for row in csv.reader(f) if row]
    if only:
        return [r for r in rows if r[0] in only]
    if start is not None:
        at = [i for i, r in enumerate(rows) if r[0] == start]
        rows = rows[at[0]:] if at else []
    if last:
        rows = rows[-last:]
    if limit:
        rows = rows[:limit]
    return rows


def by_host(sites):
    groups = {}
    for site in sites:
        groups.setdefault(urlparse(site[1]).netloc, []).append(site)
    return list(groups.values())
