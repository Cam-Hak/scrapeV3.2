import queue
import threading
import time
from datetime import date

from scrape import Result, absorb, drain, run_site
from scraper.recipe import Recipe


class FakeStore:
    def __init__(self):
        self.results = []

    def record_result(self, a_id, ok):
        self.results.append((a_id, ok))


class FakeReport:
    def __init__(self):
        self.errors = []
        self.sites = []
        self.problems = []

    def error(self, a_id, why):
        self.errors.append((a_id, why))

    def site(self, a_id, found, parsed, stored, dupes):
        self.sites.append((a_id, found, parsed, stored, dupes))

    def problem(self, a_id, why):
        self.problems.append((a_id, why))


def result(**over):
    fields = dict(a_id=101, found=6, parsed=5, stored=3, dupes=2, problems=[], error=None, lines=[])
    fields.update(over)
    return Result(**fields)


def test_an_errored_result_records_failure_and_reports_the_error():
    store, report = FakeStore(), FakeReport()
    absorb(result(error="RuntimeError: boom", found=0, parsed=0, stored=0, dupes=0), store, report)
    assert store.results == [(101, False)]
    assert report.errors == [(101, "RuntimeError: boom")]
    assert report.sites == []


def test_a_healthy_result_records_success_and_reports_the_site():
    store, report = FakeStore(), FakeReport()
    absorb(result(), store, report)
    assert store.results == [(101, True)]
    assert report.sites == [(101, 6, 5, 3, 2)]
    assert report.problems == []


def test_links_found_but_nothing_parsed_records_failure_and_reports_the_problem():
    store, report = FakeStore(), FakeReport()
    absorb(result(found=8, parsed=0, stored=0, dupes=0), store, report)
    assert store.results == [(101, False)]
    assert report.sites == [(101, 8, 0, 0, 0)]
    assert report.problems == [(101, "found=8 parsed=0")]


def test_per_site_problems_reach_the_report():
    store, report = FakeStore(), FakeReport()
    absorb(result(problems=["1406 (22001): Data too long"]), store, report)
    assert report.problems == [(101, "1406 (22001): Data too long")]


class RaisingBrowser:
    def get(self, url):
        raise RuntimeError("page timed out")


def test_run_site_reports_the_exception_with_zero_counts():
    r = run_site(RaisingBrowser(), None, 101, "https://site.test", None, date(2026, 1, 1), "lede", [], [])
    assert r.a_id == 101
    assert r.found == r.parsed == r.stored == r.dupes == 0
    assert r.problems == []
    assert r.error == "RuntimeError: page timed out"
    assert any("ERROR" in line and "page timed out" in line for line in r.lines)


class RaisesOnSecondGet:
    # listing fetch succeeds, article fetch raises -- mid-site failure
    def __init__(self, listing_html):
        self.listing_html = listing_html
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if self.calls == 1:
            return self.listing_html
        raise RuntimeError("connection reset")


def test_run_site_keeps_lines_from_before_a_mid_site_exception():
    listing_html = '<html><body><a href="https://site.test/a1">Article</a></body></html>'
    recipe = Recipe(link_selector="a", url_filter="", headline_selector="h1", date_selector="time")
    r = run_site(RaisesOnSecondGet(listing_html), None, 101, "https://site.test", recipe,
                 date(2020, 1, 1), None, [], [])
    assert r.error is not None
    assert any("no lede" in line for line in r.lines)
    assert any("listing -> 1 links" in line for line in r.lines)
    assert any("ERROR" in line for line in r.lines)


def test_drain_absorbs_every_result_and_returns_without_hanging():
    results = queue.Queue()

    def puts_immediately():
        results.put(result(a_id=1))

    def puts_after_a_delay():
        time.sleep(0.2)
        results.put(result(a_id=2))

    def puts_nothing():
        pass

    threads = [threading.Thread(target=puts_immediately),
               threading.Thread(target=puts_after_a_delay),
               threading.Thread(target=puts_nothing)]
    for t in threads:
        t.start()

    store, report = FakeStore(), FakeReport()
    drainer = threading.Thread(target=drain, args=(threads, results, store, report), daemon=True)
    drainer.start()
    drainer.join(timeout=5)

    assert not drainer.is_alive()  # a hang would leave the drainer thread still running
    assert sorted(store.results) == [(1, True), (2, True)]
