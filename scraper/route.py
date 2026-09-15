from . import keywords
from .config import MIN_WORDS, SHORT_DOC

DEFAULT_STATUS = "D"
SHORT_NOTE = "short doc"
# the order legacy ran these in: the last check that matches wins the status
CHECKS = ((keywords.BODY, "E"), (keywords.BODY, "W"),
          (keywords.HEADLINE, "E"), (keywords.HEADLINE, "W"),
          (keywords.BODY, ""), (keywords.HEADLINE, ""))


def decide(headline, body, words, rules=None):
    text = {keywords.BODY: body, keywords.HEADLINE: headline}
    status, comments, markers = DEFAULT_STATUS, [], []
    for field, action in CHECKS:
        hits = _matching(field, action, text[field], rules)
        if not hits:
            continue
        comments += [rule["comment"] for rule in hits]
        if action:
            status = action
        if action == "E" and field == keywords.BODY:
            markers += [rule["marker"] for rule in hits if rule["marker"]]
    if MIN_WORDS <= words <= SHORT_DOC:
        status = "W"
        comments.append(SHORT_NOTE)
    # two rules can carry one code, and the desk should not read it twice
    return status, " ".join(c for c in comments if c), list(dict.fromkeys(markers))


def skipped(headline, body, rules=None):
    text = {keywords.BODY: body, keywords.HEADLINE: headline}
    for field in keywords.FIELDS:
        hits = _matching(field, keywords.SKIP, text[field], rules)
        if hits:
            return hits[0]["phrase"]
    return None


def _matching(field, action, text, rules=None):
    # every keyword in one check counts, so a doc names everything the desk has to look at
    return [rule for rule in (keywords.RULES if rules is None else rules)
            if rule["field"] == field and rule["action"] == action
            and keywords.matches(rule, text)]
