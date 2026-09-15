import re

from dateutil import parser as dateparser

CONTACT = re.compile(
    r"^(for (further|more|media|press)\b"
    r"|(media|press) (contact|enquiries|inquiries|queries)"
    r"|contact:"
    # a heading line of its own, as in "Belmont University Media Contact"
    r"|.{0,40}(media|press) contacts?:?$)", re.I)
FOOTNOTE = re.compile(r"^\[\d+\]")
HEADING = re.compile(r"^(footnotes?|notes|references?|endnotes?|citations?|sources?)$", re.I)
NOISE = re.compile(r"\s*\(Opens in a new window\)", re.I)
DATA_BLOB = re.compile(r'^\[?\s*\{\s*"')
MD_HEADING = re.compile(r"^#{1,6}\s+")
MD_QUOTE = re.compile(r"^>+\s*")
# an empty heading renders as bare hashes; exactly ### is left for ENDMARK to read
HRULE = re.compile(r"^((\*\s*){3,}|-{3,}|_{3,}|#{1,2}|#{4,})$")
ENDMARK = re.compile(r"^[-~_*\s]*(ends?|###|#\s+#(\s+#)?|-30-|\[ends\])[-~_*\s]*$", re.I)
PLATFORM = r"X|Twitter|Facebook|Instagram|LinkedIn|YouTube|Threads|TikTok|Flickr"
SOCIAL = re.compile(r"^(%s)(\s*[|/,]\s*(%s))+$" % (PLATFORM, PLATFORM), re.I)
FOLLOW = re.compile(r"^(follow|connect with|stay connected|subscribe)\b", re.I)
KICKER_LIMIT = 60
MAX_KICKERS = 2
# table cells and labels repeat for real; a repeated sentence this long never does
REPEAT_MIN = 80


def clean(text, headline, date, drop=(), boilerplate=()):
    lines = [NOISE.sub("", l).strip() for l in text.split("\n")]
    lines = [MD_QUOTE.sub("", MD_HEADING.sub("", l)) for l in lines]
    lines = [l for l in lines if l and l != "|" and not HRULE.match(l)]
    lines = [l for l in lines if not _dropped(l, drop)]
    # learned boilerplate is whole lines, so a line must equal one, not merely contain it
    known = {_norm(b) for b in boilerplate} - {""}
    lines = [l for l in lines if _norm(l) not in known]
    lines = [l for l in lines if not SOCIAL.match(l) and not FOLLOW.match(l)]
    # a page's embedded search index renders as one long line of JSON, never as prose
    lines = [l for l in lines if not DATA_BLOB.match(l)]
    lines = _drop_repeats(lines)
    lines = _drop_head(lines, headline, date)
    lines = _drop_footnotes(lines)
    lines, contact = _split_contact(lines)
    lines = _drop_after_end(lines)
    lines = _drop_bare_tail(lines)
    return "\n\n".join(lines), contact


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _dropped(line, drop):
    key = _norm(line)
    return any(_norm(p) and _norm(p) in key for p in drop)


def _drop_repeats(lines):
    # trafilatura can emit a paragraph twice when the page splits it with <br> tags
    seen, kept = set(), []
    for line in lines:
        if len(line) >= REPEAT_MIN and line in seen:
            continue
        seen.add(line)
        kept.append(line)
    return kept


def _drop_head(lines, headline, date):
    key = _norm(headline)
    for i, line in enumerate(lines[:6]):
        if _norm(line) == key:
            lines = lines[i + 1:]
            break
    # a page can print its title twice, as a heading and again as a summary line
    while lines and _norm(lines[0]) == key:
        lines = lines[1:]
    while lines and _is_date(lines[0], date):
        lines = lines[1:]
    dropped = 0
    while lines and dropped < MAX_KICKERS and _is_kicker(lines[0]):
        lines = lines[1:]
        dropped += 1
    return lines


def _is_date(line, date):
    if len(line) > 40:
        return False
    try:
        return dateparser.parse(line).date() == date
    except (ValueError, OverflowError, TypeError):
        return False


def _is_kicker(line):
    return len(line) < KICKER_LIMIT and not line.endswith((".", "!", "?", ":", '"'))


def _drop_footnotes(lines):
    marks = [i for i, l in enumerate(lines) if FOOTNOTE.match(l)]
    # three or more markers means a real footnote block, not one inline citation
    if len(marks) >= 3:
        lines = lines[:marks[0]]
    while lines and HEADING.match(lines[-1]):
        lines = lines[:-1]
    return lines


def _split_contact(lines):
    # this takes a trailing block, so a release that opens on one must keep its body
    for i in range(max(1, len(lines) - 8), len(lines)):
        if CONTACT.match(lines[i]):
            return lines[:i], "\n".join(lines[i:])
    return lines, None


def _drop_bare_tail(lines):
    # an empty heading renders as "####", and a release never ends on a line with no words
    while lines and not any(c.isalnum() for c in lines[-1]):
        lines = lines[:-1]
    return lines


def _drop_after_end(lines):
    # a wire end marker means the release is over, whatever follows it
    for i, line in enumerate(lines):
        if ENDMARK.match(line):
            return lines[:i]
    return lines
