import sqlite3
import sys

import pytest

import scrape
from scraper import isolate
from scraper.history import SKIPPED
from scraper.sites import load_sites

SITES = [(1001, "https://a.test/news"), (1002, "https://b.test/news"),
         (1003, "https://c.test/news"), (1004, "https://d.test/news"),
         (1005, "https://e.test/news"), (1006, "https://f.test/news"),
         (1007, "https://www.house.test/news"), (1008, "https://senate.test/news")]
AGENCIES = {
    1001: ("P1", "LEDE1", "U1", "M-USG"),
    1002: ("P2", "LEDE2", "U2", "(AT) USG General"),
    # 1003 has no agencies row at all
    1004: ("P4", "LEDE4", "U4", ""),  # the LEFT JOIN found no url group
    1005: ("P5", "LEDE5", "U5", "m-biz"),
    1006: ("P6", "LEDE6", "U6", "New M-"),
    1007: ("P7", "LEDE7", "U7", "M-House-R"),
    1008: ("P8", "LEDE8", "U8", "(AT) 2023Congress-Senate-Rep"),
}


class FakeStore:
    def __init__(self, *a):
        pass

    def clear_failures(self):
        pass

    def get_recipe(self, a_id):
        return "recipe"

    def is_failed(self, a_id):
        return False

    def record_result(self, a_id, ok):
        pass

    def close(self):
        pass


class FakeConn:
    def close(self):
        pass


def run(monkeypatch, tmp_path, argv, mailed=None):
    listing = tmp_path / "sites.csv"
    listing.write_text("".join("%s,%s\n" % site for site in SITES))
    queued, skipped = {}, {}
    mailed = [] if mailed is None else mailed

    class FakeHistory:
        run_id = "test"

        def __init__(self, **k):
            pass

        def site(self, a_id, state, *a, error="", **k):
            if state == SKIPPED:
                skipped[a_id] = error

        def finish(self, *a, **k):
            pass

    def fake_isolated(job, timeout):
        queued[job[0]] = job[4]
        return isolate._blank(job[0], job[1], None, "faked")

    monkeypatch.setattr(scrape, "Store", FakeStore)
    monkeypatch.setattr(scrape, "History", FakeHistory)
    # the real selector code, so --id, --senate and the rest filter as they do in a run
    monkeypatch.setattr(scrape, "load_sites", lambda path, *a, **k: load_sites(str(listing), *a, **k))
    monkeypatch.setattr(scrape.articles, "connect", FakeConn)
    monkeypatch.setattr(scrape.articles, "load_agencies",
                        lambda conn, ids: {a: AGENCIES[a] for a in ids if a in AGENCIES})
    monkeypatch.setattr(scrape, "run_site_isolated", fake_isolated)
    monkeypatch.setattr(scrape, "sweep_profiles", lambda *a, **k: 0)
    # --production reads the mail settings up front and mails the summary at the end
    monkeypatch.setattr(scrape.config, "mail", lambda: {"sender": "s@x.test", "to": "t@x.test", "cc": ""})
    monkeypatch.setattr(scrape, "notify", lambda conf, report, run_id, lines: mailed.extend(lines))
    monkeypatch.setattr(sys, "argv", ["scrape.py", "--workers", "1"] + argv)
    scrape.main()
    return queued, skipped, mailed


def test_a_test_run_queues_every_site_as_test_uname(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, [])
    assert sorted(queued) == [1001, 1002, 1003, 1004, 1005, 1006]
    assert skipped == {}
    assert all(agency[2] == "test_uname" for agency in queued.values())
    assert queued[1003] == ("TEST1003", "", "test_uname")
    assert mailed == []


def test_a_production_run_queues_only_m_groups_under_their_own_uname(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--production"])
    assert sorted(queued) == [1001, 1005]
    assert queued[1001] == ("P1", "LEDE1", "U1")
    assert mailed


def test_a_site_left_out_of_production_never_reaches_the_email(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--production"])
    assert skipped == {}
    summary = "\n".join(mailed)
    assert not any(str(a_id) in summary for a_id in (1002, 1003, 1004, 1006))


def test_a_site_with_no_agencies_row_never_loads_in_production(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--production", "--id", "1003"])
    assert queued == {}


def test_naming_a_site_with_id_does_not_bypass_the_gate(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--production", "--id", "1002", "1006", "1001"])
    assert sorted(queued) == [1001]


def test_the_senate_half_is_gated_too(monkeypatch, tmp_path):
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--production", "--senate"])
    assert sorted(queued) == [1007]


def test_a_read_only_recipes_db_does_not_stop_retry_failed(monkeypatch, tmp_path):
    def refuse(self):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(FakeStore, "clear_failures", refuse)
    queued, skipped, mailed = run(monkeypatch, tmp_path, ["--retry-failed"])
    assert sorted(queued) == [1001, 1002, 1003, 1004, 1005, 1006]


def test_one_unreadable_recipe_does_not_stop_the_other_sites(monkeypatch, tmp_path):
    def recipe(self, a_id):
        if a_id == 1002:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return "recipe"

    monkeypatch.setattr(FakeStore, "get_recipe", recipe)
    queued, skipped, mailed = run(monkeypatch, tmp_path, [])
    assert skipped == {1002: "recipe unreadable"}
    assert sorted(queued) == [1001, 1003, 1004, 1005, 1006]


def test_a_crash_mid_run_still_ends_with_the_summary_and_the_email(monkeypatch, tmp_path):
    def boom(ready):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(scrape, "by_host", boom)
    mailed = []
    with pytest.raises(SystemExit) as ended:
        run(monkeypatch, tmp_path, ["--production"], mailed)
    assert ended.value.code == 1
    assert "stopped early -- RuntimeError: can't start new thread" in "\n".join(mailed)


def test_the_log_opens_with_the_version(monkeypatch, tmp_path, capsys):
    run(monkeypatch, tmp_path, [])
    assert capsys.readouterr().out.splitlines()[0] == scrape.config.VERSION_LINE


def test_a_run_that_fails_at_startup_still_says_its_version(monkeypatch, tmp_path, capsys):
    def unreadable(path):
        raise OSError("strip.csv unreadable")

    monkeypatch.setattr(scrape, "load_strips", unreadable)
    with pytest.raises(OSError):
        run(monkeypatch, tmp_path, [])
    assert capsys.readouterr().out.splitlines()[0] == scrape.config.VERSION_LINE


def test_with_streaks_off_a_benched_site_still_runs(monkeypatch, tmp_path):
    # the shipped default: an old streak in recipes.db no longer keeps a site out of a run
    monkeypatch.setattr(FakeStore, "is_failed", lambda self, a_id: a_id == 1002)
    queued, skipped, mailed = run(monkeypatch, tmp_path, [])
    assert 1002 in queued and skipped == {}
