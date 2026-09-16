"""Run one site in its own process.

A page load has no timeout of its own, and a call blocked inside one raises
nothing -- so a thread stuck there can be neither interrupted nor killed, and it
holds its worker for the rest of the run. A child process can be killed. This
costs a Chrome start per site and buys a hard upper bound on what one bad site
can take from you.

The child is started in its own session so killing the process group takes
Chrome down with it; killing only the direct child would leave the browser
orphaned and the memory with it.
"""

import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date

# the child's stdout also carries run_site's own log lines, so the result is
# marked rather than assumed to be the last thing printed
MARKER = "@@RESULT@@"

FIELDS = ("a_id", "found", "parsed", "stored", "dupes", "drops", "routed", "problems",
          "error", "lines")


def _blank(a_id, url, error, note):
    return dict(a_id=a_id, found=0, parsed=0, stored=0, dupes=0, drops={}, routed={},
                problems=[], error=error,
                lines=["", "%s %s" % (a_id, url), "  " + note])


def _kill_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def sweep_profiles(older_than=900):
    """Remove Chrome profiles no live run can still be using.

    A killed browser never cleans up after itself, and these run to hundreds of
    MB each -- enough to fill a disk over a few hundred sites.
    """
    cutoff = time.time() - older_than
    freed = 0
    for pattern in ("scrape_prof_*", "uc_*"):
        for path in glob.glob(os.path.join(tempfile.gettempdir(), pattern)):
            try:
                if os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    freed += 1
            except OSError:
                pass
    return freed


def run_site_isolated(job, timeout, cwd=None):
    """Returns the same dict shape run_site's Result carries."""
    a_id, url, recipe, cutoff, agency, _drop, _title, _prune, cap = job
    payload = json.dumps({"a_id": a_id, "url": url, "recipe": recipe.to_json(),
                          "cutoff": cutoff.isoformat(), "agency": list(agency), "cap": cap})
    proc = subprocess.Popen(
        [sys.executable, "-m", "scraper.isolate"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=cwd, start_new_session=True)
    try:
        try:
            out, err = proc.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return _blank(a_id, url, "timed out after %ds" % timeout,
                          "TIMED OUT after %ds -- process killed" % timeout)

        for line in reversed((out or "").splitlines()):
            if line.startswith(MARKER):
                found = json.loads(line[len(MARKER):])
                return {k: found.get(k) for k in FIELDS}
        tail = (err or "").strip().splitlines()
        why = tail[-1][:160] if tail else "child produced no result (exit %s)" % proc.returncode
        return _blank(a_id, url, why, "CHILD FAILED: " + why)
    finally:
        # Chrome picks its own profile dir and a killed one never removes it --
        # hundreds of MB each, which filled the disk mid-run once already.
        # Anything older than one site's ceiling cannot belong to a live child.
        sweep_profiles(older_than=timeout + 60)


def _child():
    # imported here: scrape imports this module, so importing it at the top
    # would be circular
    from scrape import run_site
    from scraper import articles, config, keywords
    from scraper.browser import Browser
    from scraper.recipe import Recipe
    from scraper.strip import load_strips, patterns_for

    data = json.loads(sys.stdin.read())
    a_id = data["a_id"]
    # rebuilt from the csv rather than passed in, so nothing here depends on
    # the parent serialising compiled patterns correctly
    strips = load_strips(config.STRIP_CSV)
    keywords.load(config.KEYWORDS_CSV)

    with Browser() as browser:
        conn = articles.connect()
        try:
            result = run_site(
                browser, conn, a_id, data["url"], Recipe.from_json(data["recipe"]),
                date.fromisoformat(data["cutoff"]), tuple(data["agency"]),
                patterns_for(strips, a_id), patterns_for(strips, a_id, "title"),
                patterns_for(strips, a_id, "prune"), data["cap"])
        finally:
            conn.close()
    print(MARKER + json.dumps(result._asdict()), flush=True)


if __name__ == "__main__":
    _child()
