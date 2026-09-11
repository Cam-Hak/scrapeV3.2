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


def test_a_healthy_result_records_success_and_reports_the_site(monkeypatch, capsys):
    store, report = FakeStore(), FakeReport()
    real_print = print
    calls = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: (calls.append(a), real_print(*a, **k)))
    absorb(result(lines=["  -> line one", "  -> line two"]), store, report)
    assert store.results == [(101, True)]
    assert report.sites == [(101, 6, 5, 3, 2)]
    assert report.problems == []
    assert len(calls) == 1  # the whole block is one write, not one print per line
    assert capsys.readouterr().out == "  -> line one\n  -> line two\n"


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
    r = run_site(RaisingBrowser(), None, 101, "https://site.test", None, date(2026, 1, 1),
                 "lede", [], [], [])
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
                 date(2020, 1, 1), None, [], [], [])
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


class ListingBrowser:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, patient=False):
        self.calls.append((url, patient))
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


LISTING = '<html><body><a class="post" href="/a">One</a></body></html>'
ARTICLE = '<html><body><h1>One</h1><time>2026-09-05</time><p>Body text here.</p></body></html>'


def listing_recipe():
    return Recipe(link_selector="a.post", url_filter="", headline_selector="h1",
                  date_selector="time")


def test_an_empty_listing_is_fetched_again_patiently():
    browser = ListingBrowser(["<html><body></body></html>", LISTING, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), "lede", (), (), ())
    assert browser.calls[0] == ("https://site.test/news", False)
    assert browser.calls[1] == ("https://site.test/news", True)


def test_a_listing_that_yields_links_is_not_fetched_twice():
    browser = ListingBrowser([LISTING, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), "lede", (), (), ())
    assert browser.calls[0] == ("https://site.test/news", False)
    assert browser.calls[1][0] == "https://site.test/a"


def test_an_empty_article_is_fetched_again_patiently():
    browser = ListingBrowser([LISTING, "<html><body></body></html>", ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), "lede", (), (), ())
    assert browser.calls[1] == ("https://site.test/a", False)
    assert browser.calls[2] == ("https://site.test/a", True)


def test_an_article_that_parses_is_not_fetched_twice():
    browser = ListingBrowser([LISTING, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), "lede", (), (), ())
    assert [c for c in browser.calls if c[0] == "https://site.test/a"] == [
        ("https://site.test/a", False)]

MANY = ('<html><body><a class="post" href="/a">One</a>'
        '<a class="post" href="/b">Two</a>'
        '<a class="post" href="/c">Three</a></body></html>')


def test_every_link_is_fetched_when_no_cap_is_given():
    browser = ListingBrowser([MANY, ARTICLE])
    # a cutoff ahead of the article date keeps the run off the database
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 10), "lede", (), (), ())
    assert len(browser.calls) == 4


def test_max_articles_caps_the_links_that_are_fetched():
    browser = ListingBrowser([MANY, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 10), "lede", (), (), (), 2)
    assert len(browser.calls) == 3


def test_the_reported_link_count_is_the_full_listing_not_the_cap():
    browser = ListingBrowser([MANY, ARTICLE])
    result = run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
                      date(2026, 9, 10), "lede", (), (), (), 2)
    assert result.found == 3
