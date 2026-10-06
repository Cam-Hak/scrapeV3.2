import sys

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


def run(monkeypatch, tmp_path, argv):
    listing = tmp_path / "sites.csv"
    listing.write_text("".join("%s,%s\n" % site for site in SITES))
    queued, skipped, mailed = {}, {}, []

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
