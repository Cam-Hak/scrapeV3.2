import csv
import re

BODY, HEADLINE = "body", "headline"
FIELDS = (BODY, HEADLINE)
SKIP = "skip"
SEPARATOR = "~"
COLUMNS = ("field", "phrase", "action", "comment", "marker", "whole", "veto")
DEFAULTS = {BODY: "CC `%s` found", HEADLINE: "CC `%s` found in headline"}

RULES = []


def load(path):
    global RULES
    RULES = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                rule = _rule(row)
                if rule:
                    RULES.append(rule)
    except FileNotFoundError:
        pass
    return RULES


def _rule(row):
    if not row or row[0].strip().startswith("#"):
        return None
    cell = dict(zip(COLUMNS, [c.strip() for c in row] + [""] * len(COLUMNS)))
    if cell["field"] not in FIELDS or not cell["phrase"]:
        return None
    cell["pattern"] = _word(cell["phrase"]) if cell["whole"].lower() == "y" else None
    cell["veto"] = [_word(v) for v in cell["veto"].split(SEPARATOR) if v.strip()]
    cell["comment"] = cell["comment"] or DEFAULTS[cell["field"]] % cell["phrase"]
    return cell


def _word(phrase):
    # \b only bites next to a word character, so a phrase edged with "(" would never match
    phrase = phrase.strip()
    start = r"\b" if phrase[:1].isalnum() else ""
    end = r"\b" if phrase[-1:].isalnum() else ""
    return re.compile(start + re.escape(phrase) + end, re.I)


def matches(rule, text):
    if not text:
        return False
    hit = rule["pattern"].search(text) if rule["pattern"] else \
        rule["phrase"].lower() in text.lower()
    # a veto word always reads as a whole word: a quoted journalist is not a journal
    return bool(hit) and not any(v.search(text) for v in rule["veto"])
