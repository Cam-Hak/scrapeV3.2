import json
import os
import time
from datetime import datetime

# what a site did in one run, in the order the dashboard reads them
OK = "ok"
STALE = "stale"        # links found but nothing parsed -- selectors have gone off
ERROR = "error"
SKIPPED = "skipped"    # never attempted: no recipe, lede or uname, or the run was stopped


def code(state, found, parsed, stored, dupes, error):
    if state == SKIPPED:
        return "I" if error.startswith("not run") else "S"
    if state == ERROR:
        return "T" if error.startswith("timed out") else "E"
    if not found:
        return "N"
    if not parsed and not dupes:
        return "P"
    if stored:
        return "O"
    return "D" if dupes else "Q"


class History:
    """Appends what a run did to runs.jsonl and run_sites.jsonl.

    Two files rather than one: the run summaries stay small enough to read
    whole, while the per-site lines are only ever read from the tail.

    A history write must never be what kills a scrape, so every write is
    wrapped. Losing a log line costs less than losing the run that made it.
    """

    def __init__(self, directory=".", runs="runs.jsonl", sites="run_sites.jsonl",
                 status="status", keep=60):
        self.runs_path = os.path.join(directory, runs)
        self.sites_path = os.path.join(directory, sites)
        self.run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
        # one tiny "id,code" file per run, for the monitor to read without parsing json
        self.status_dir = os.path.join(directory, status)
        self.status_path = os.path.join(self.status_dir, self.run_id + ".csv")
        self.keep = keep
        self.started = time.time()
        self.write_errors = 0
        try:
            os.mkdir(self.status_dir)
        except OSError:
            pass

    def _write(self, path, line):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            self.write_errors += 1

    def _append(self, path, record):
        self._write(path, json.dumps(record, separators=(",", ":")))

    def site(self, a_id, state, found=0, parsed=0, stored=0, dupes=0, error="", problems=(),
             drops=None, routed=None):
        self._append(self.sites_path, {
            "run_id": self.run_id,
            "a_id": a_id,
            "state": state,
            "found": found,
            "parsed": parsed,
            "stored": stored,
            "dupes": dupes,
            "drops": drops or {},
            "routed": routed or {},
            "error": error or "",
            "problems": list(problems or ()),
        })
        self._write(self.status_path,
                    "%s,%s" % (a_id, code(state, found, parsed, stored, dupes, error or "")))

    def finish(self, report, days=None, workers=None):
        try:
            for old in sorted(os.listdir(self.status_dir))[:-self.keep]:
                os.remove(os.path.join(self.status_dir, old))
        except OSError:
            pass
        now = time.time()
        self._append(self.runs_path, {
            "run_id": self.run_id,
            "started": datetime.fromtimestamp(self.started).isoformat(timespec="seconds"),
            "finished": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "seconds": int(now - self.started),
            "cutoff": str(getattr(report, "cutoff", "")),
            "days": days,
            "workers": workers,
            "sites": getattr(report, "sites", 0),
            "ran": getattr(report, "ran", 0),
            "skipped": getattr(report, "skipped", 0),
            "errors": getattr(report, "errors", 0),
            "found": getattr(report, "found", 0),
            "parsed": getattr(report, "parsed", 0),
            "stored": getattr(report, "stored", 0),
            "dupes": getattr(report, "dupes", 0),
            "ledeless": getattr(report, "ledeless", 0),
            "drops": dict(getattr(report, "drops", {})),
            "routed": dict(getattr(report, "routed", {})),
            "empty": list(getattr(report, "empty", ())),
            "problems": [list(p) for p in getattr(report, "problems", ())],
        })
