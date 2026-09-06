import time


def _clock(secs):
    return "%dm%02ds" % (secs // 60, secs % 60) if secs >= 60 else "%ds" % secs


class Report:
    def __init__(self, cutoff, sites):
        self.cutoff = cutoff
        self.sites = sites
        self.started = time.time()
        self.ran = self.skipped = self.errors = 0
        self.found = self.parsed = self.stored = self.dupes = 0
        self.empty = []
        self.ledeless = 0
        self.problems = []

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

    def site(self, a_id, found, parsed, stored, dupes):
        self.ran += 1
        self.found += found
        self.parsed += parsed
        self.stored += stored
        self.dupes += dupes
        if not stored and not dupes:
            self.empty.append(a_id)

    def lines(self):
        out = [
            "summary",
            "  %d site(s) in %s, articles on or after %s"
            % (self.sites, _clock(int(time.time() - self.started)), self.cutoff),
            "  sites: %d ran, %d skipped, %d errored" % (self.ran, self.skipped, self.errors),
            "  articles: %d stored, %d duplicates, %d parsed from %d links"
            % (self.stored, self.dupes, self.parsed, self.found),
        ]
        if self.ledeless:
            out.append("  %d site(s) have no lede, so those bodies open with TKTK"
                       % self.ledeless)
        if self.empty:
            out.append("  nothing found: " + ", ".join(str(a_id) for a_id in self.empty))
        if self.problems:
            out.append("  problems:")
            out += ["    %s %s" % (a_id, why) for a_id, why in self.problems]
        return out
