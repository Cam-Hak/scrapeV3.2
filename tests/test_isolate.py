import json
import subprocess
import time

from scraper import isolate
from scraper.recipe import Recipe


def job(a_id=101, url="https://site.test/news", cap=3):
    from datetime import date
    return (a_id, url, Recipe(link_selector="a", url_filter="", headline_selector="h1",
                              date_selector="time"),
            date(2026, 1, 1), "lede", [], [], [], cap)


def fake_child(monkeypatch, script):
    # stands in for `python -m scraper.isolate`, so these tests never open a browser
    real = subprocess.Popen

    def popen(cmd, **kw):
        return real(["python3", "-c", script], **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return popen


def test_a_child_that_hangs_is_killed_and_reported(monkeypatch):
    fake_child(monkeypatch, "import sys, time; sys.stdin.read(); time.sleep(60)")
    began = time.time()
    r = isolate.run_site_isolated(job(), timeout=2)
    elapsed = time.time() - began
    assert elapsed < 20  # killed on the timeout, not waited out
    assert "timed out" in r["error"]
    assert r["found"] == r["parsed"] == r["stored"] == 0
    assert any("TIMED OUT" in l for l in r["lines"])


def test_a_normal_result_comes_back_intact(monkeypatch):
    payload = dict(a_id=101, found=9, parsed=4, stored=3, dupes=1,
                   problems=["something odd"], error=None, lines=["  ok"])
    fake_child(monkeypatch,
               "import sys, json; sys.stdin.read(); "
               "print('noise from run_site logging'); "
               "print(%r + json.dumps(%r))" % (isolate.MARKER, payload))
    r = isolate.run_site_isolated(job(), timeout=20)
    assert r["found"] == 9 and r["parsed"] == 4 and r["stored"] == 3 and r["dupes"] == 1
    assert r["problems"] == ["something odd"]
    assert r["error"] is None


def test_a_child_that_dies_is_reported_not_swallowed(monkeypatch):
    fake_child(monkeypatch,
               "import sys; sys.stdin.read(); "
               "sys.stderr.write('boom: chrome would not start\\n'); sys.exit(3)")
    r = isolate.run_site_isolated(job(), timeout=20)
    assert r["error"] and "boom" in r["error"]
    assert r["stored"] == 0


def test_the_result_carries_every_field_absorb_expects(monkeypatch):
    from scrape import Result
    payload = dict(a_id=7, found=1, parsed=1, stored=1, dupes=0,
                   problems=[], error=None, lines=[])
    fake_child(monkeypatch,
               "import sys, json; sys.stdin.read(); print(%r + json.dumps(%r))"
               % (isolate.MARKER, payload))
    r = isolate.run_site_isolated(job(), timeout=20)
    Result(**r)  # raises if a field is missing or extra


def test_sweep_removes_only_stale_profiles(tmp_path, monkeypatch):
    import tempfile, os, time as _t
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / "scrape_prof_old"; old.mkdir()
    new = tmp_path / "scrape_prof_new"; new.mkdir()
    keep = tmp_path / "something_else"; keep.mkdir()
    os.utime(old, (_t.time() - 5000, _t.time() - 5000))
    assert isolate.sweep_profiles(older_than=900) == 1
    assert not old.exists()
    assert new.exists() and keep.exists()


def test_a_finished_site_sweeps_stale_profiles(monkeypatch, tmp_path):
    import os, tempfile, time as _t
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    stale = tmp_path / "uc_stale"; stale.mkdir()
    fresh = tmp_path / "uc_fresh"; fresh.mkdir()
    os.utime(stale, (_t.time() - 5000, _t.time() - 5000))
    fake_child(monkeypatch, "import sys, time; sys.stdin.read(); time.sleep(60)")
    isolate.run_site_isolated(job(), timeout=2)
    assert not stale.exists()   # a killed Chrome's leftovers get cleared
    assert fresh.exists()       # a live worker's profile is left alone
