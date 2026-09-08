import csv
import re

ALL = "*"
BODY, TITLE, PRUNE = "body", "title", "prune"
COLUMNS = (BODY, TITLE, PRUNE)
SEPARATOR = "~"


def load_strips(path):
    strips = {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#"):
                    continue
                for column, mode in enumerate(COLUMNS, 1):
                    cell = row[column] if len(row) > column else ""
                    found = [p.strip() for p in cell.split(SEPARATOR) if p.strip()]
                    if found:
                        strips.setdefault((row[0].strip(), mode), []).extend(found)
    except FileNotFoundError:
        pass
    return strips


def patterns_for(strips, a_id, mode=BODY):
    return strips.get((ALL, mode), []) + strips.get((str(a_id), mode), [])


def clean_title(title, patterns):
    for pattern in patterns:
        # a space, not nothing, so a phrase cut from mid-title cannot glue words
        title = re.sub(re.escape(pattern), " ", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -–—:|")
