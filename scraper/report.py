import time
from datetime import datetime

from .config import MIN_WORDS, SHORT_DOC, VERSION, VERSION_DATE

INDENT = "       "


def _elapsed(secs):
    return "%d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60)


def _stamp(when):
    return datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S")


class Report:
    def __init__(self, cutoff, sites, days=None, senate=False):
        self.cutoff = cutoff
        self.sites = sites
        self.days = days
        self.senate = senate
        self.started = time.time()
        self.ran = self.skipped = self.errors = 0
        self.found = self.parsed = self.stored = self.dupes = 0
        self.empty = []
        self.ledeless = 0
        self.problems = []
        self.drops = {"future": 0, "short": 0, "skipped": 0}
        self.routed = {"E": 0, "W": 0, "short_doc": 0}

    def skip(self, a_id, why):
        self.skipped += 1
        self.problem(a_id, why)

    def error(self, a_id, why):
        self.errors += 1
        self.problem(a_id, why)

    def no_lede(self):
        self.ledeless += 1

    def problem(self, a_id, why):
        # one broken column repeats per article, and that would bury everything else
        if (a_id, why) not in self.problems:
            self.problems.append((a_id, why))

    def dropped(self, counts):
        for name, n in (counts or {}).items():
            self.drops[name] = self.drops.get(name, 0) + n

    def sent(self, counts):
        for name, n in (counts or {}).items():
            self.routed[name] = self.routed.get(name, 0) + n

    def site(self, a_id, found, parsed, stored, dupes):
        self.ran += 1
        self.found += found
        self.parsed += parsed
        self.stored += stored
        self.dupes += dupes
        if not stored and not dupes:
            self.empty.append(a_id)

    def lines(self):
        out = ["Load Version %s %s" % (VERSION, VERSION_DATE)]
        out += self._indent(self._loaded())
        out += ["", "Passed Parameters:"] + self._indent(self._parameters())
        out += ["", "Sites:"] + self._indent(self._ran())
        if self.problems:
            out += ["", "Problems:"]
            out += self._indent("%s %s" % (a_id, why) for a_id, why in self.problems)
        return out

    def _indent(self, lines):
        return [INDENT + line for line in lines]

    def _loaded(self):
        return (
            "Docs Loaded: %d" % self.stored,
            "URLS processed: %d" % self.found,
            "Articles read: %d" % self.parsed,
            "DUPS skipped: %d" % self.dupes,
            "No Ledes found: %d" % self.ledeless,
            "Docs Sent To Box 4 Editor Box For Phrase: %d" % self.routed["E"],
            "Docs Sent To Box 7 Repairs: %d" % self.routed["W"],
            "Short Docs Sent To Box 7 Repairs: %d" % self.routed["short_doc"],
            "Article Description Too Short: %d" % self.drops["short"],
            "Article Skipped Due to Keyword: %d" % self.drops["skipped"],
            "Article Dated Ahead: %d" % self.drops["future"],
        )

    def _parameters(self):
        now = time.time()
        return (
            "Pull House and Senate: %s" % self.senate,
            "Number of days back: %s" % self.days,
            "Start Time: %s" % _stamp(self.started),
            "End Time: %s" % _stamp(now),
            "Elapsed Time: %s" % _elapsed(int(now - self.started)),
            "Words Needed To Load: more than %d" % MIN_WORDS,
            "Short Doc Range: %d-%d words" % (MIN_WORDS, SHORT_DOC),
            "Articles On Or After: %s" % self.cutoff,
        )

    def _ran(self):
        lines = [
            "Selected: %d" % self.sites,
            "Ran: %d" % self.ran,
            "Skipped: %d" % self.skipped,
            "Errored: %d" % self.errors,
        ]
        if self.empty:
            lines.append("Nothing found: " + ", ".join(str(a_id) for a_id in self.empty))
        return lines
