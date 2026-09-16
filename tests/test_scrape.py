import queue
import threading
import time
from datetime import date, timedelta

import scrape
from scrape import Result, absorb, drain, notify, run_site
from scraper import config, keywords
from scraper.recipe import Recipe
from scraper.report import Report


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
        self.drops = {"future": 0, "short": 0, "skipped": 0}

    def error(self, a_id, why):
        self.errors.append((a_id, why))

    def site(self, a_id, found, parsed, stored, dupes):
        self.sites.append((a_id, found, parsed, stored, dupes))

    def problem(self, a_id, why):
        self.problems.append((a_id, why))

    def dropped(self, counts):
        for name, n in (counts or {}).items():
            self.drops[name] = self.drops.get(name, 0) + n


def result(**over):
    fields = dict(a_id=101, found=6, parsed=5, stored=3, dupes=2, drops={}, problems=[],
                  error=None, lines=[])
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
                 ("ABC", "lede"), [], [], [])
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
                 date(2020, 1, 1), ("ABC", ""), [], [], [])
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
             date(2026, 9, 1), ("ABC", "lede"), (), (), ())
    assert browser.calls[0] == ("https://site.test/news", False)
    assert browser.calls[1] == ("https://site.test/news", True)


def test_a_listing_that_yields_links_is_not_fetched_twice():
    browser = ListingBrowser([LISTING, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), ("ABC", "lede"), (), (), ())
    assert browser.calls[0] == ("https://site.test/news", False)
    assert browser.calls[1][0] == "https://site.test/a"


def test_an_empty_article_is_fetched_again_patiently():
    browser = ListingBrowser([LISTING, "<html><body></body></html>", ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), ("ABC", "lede"), (), (), ())
    assert browser.calls[1] == ("https://site.test/a", False)
    assert browser.calls[2] == ("https://site.test/a", True)


def test_an_article_that_parses_is_not_fetched_twice():
    browser = ListingBrowser([LISTING, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 1), ("ABC", "lede"), (), (), ())
    assert [c for c in browser.calls if c[0] == "https://site.test/a"] == [
        ("https://site.test/a", False)]

MANY = ('<html><body><a class="post" href="/a">One</a>'
        '<a class="post" href="/b">Two</a>'
        '<a class="post" href="/c">Three</a></body></html>')


def test_every_link_is_fetched_when_no_cap_is_given():
    browser = ListingBrowser([MANY, ARTICLE])
    # a cutoff ahead of the article date keeps the run off the database
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 10), ("ABC", "lede"), (), (), ())
    assert len(browser.calls) == 4


def test_max_articles_caps_the_links_that_are_fetched():
    browser = ListingBrowser([MANY, ARTICLE])
    run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
             date(2026, 9, 10), ("ABC", "lede"), (), (), (), 2)
    assert len(browser.calls) == 3


def test_the_reported_link_count_is_the_full_listing_not_the_cap():
    browser = ListingBrowser([MANY, ARTICLE])
    result = run_site(browser, None, 101, "https://site.test/news", listing_recipe(),
                      date(2026, 9, 10), ("ABC", "lede"), (), (), (), 2)
    assert result.found == 3


def test_drain_gives_up_on_a_worker_that_never_finishes():
    # a page load can block with no timeout of its own, so the drain has to be
    # able to walk away from a worker that will never report
    results = queue.Queue()
    stop_it = threading.Event()

    def never_finishes():
        stop_it.wait(30)  # stands in for a wedged sb.open()

    threads = [threading.Thread(target=never_finishes, daemon=True)]
    for t in threads:
        t.start()

    store, report = FakeStore(), FakeReport()
    began = time.time()
    drain(threads, results, store, report, None, stall_limit=1)
    elapsed = time.time() - began
    stop_it.set()

    assert elapsed < 10  # returned on the stall limit, not when the worker ended
    assert store.results == []


def test_drain_still_waits_while_results_keep_arriving():
    # the stall guard must not cut off a slow but healthy run
    results = queue.Queue()

    def trickles():
        for a_id in (1, 2, 3):
            time.sleep(0.4)
            results.put(result(a_id=a_id))

    threads = [threading.Thread(target=trickles, daemon=True)]
    for t in threads:
        t.start()

    store, report = FakeStore(), FakeReport()
    drain(threads, results, store, report, None, stall_limit=2)
    assert sorted(store.results) == [(1, True), (2, True), (3, True)]


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.inserts = []

    def execute(self, sql, args=None):
        if sql.startswith("INSERT"):
            self.inserts.append(args)

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, known=()):
        self.cur = FakeCursor([(n,) for n in known])

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass


WORDS = " ".join(["policy"] * 200) + "."


def article(when, body=WORDS):
    return '<html><body><h1>One</h1><time>%s</time><p>%s</p></body></html>' % (when, body)


ROW_LISTING = ('<html><body><div class="row"><h2><a class="post" href="/a">One</a></h2>'
               '<time>2026-09-05</time></div></body></html>')


def row_recipe():
    return Recipe(link_selector="a.post", url_filter="", headline_selector="h2",
                  date_selector="time", item_selector="div.row",
                  headline_on_listing=True, date_on_listing=True)


def run(browser, conn, recipe=None, cutoff=date(2026, 9, 1)):
    return run_site(browser, conn, 101, "https://site.test/news", recipe or listing_recipe(),
                    cutoff, ("ABC", "lede"), (), (), ())


def test_a_future_dated_article_is_not_stored():
    conn = FakeConn()
    browser = ListingBrowser([LISTING, article("2099-01-01")])
    result = run(browser, conn)
    assert conn.cur.inserts == []
    assert result.drops["future"] == 1


def test_a_future_dated_article_does_not_reset_the_stale_count():
    # three old ones after a future-dated one must still stop the site
    listing = ('<html><body><a class="post" href="/a">A</a><a class="post" href="/b">B</a>'
               '<a class="post" href="/c">C</a><a class="post" href="/d">D</a>'
               '<a class="post" href="/e">E</a></body></html>')
    pages = [listing, article("2099-01-01"), article("2020-01-01"), article("2020-01-02"),
             article("2020-01-03"), article("2026-09-05")]
    browser = ListingBrowser(pages)
    run(browser, FakeConn())
    # the fifth article is never reached: the run breaks on three old ones in a row
    assert [c[0] for c in browser.calls].count("https://site.test/e") == 0


def test_a_date_inside_the_grace_window_is_still_accepted():
    when = date.today() + timedelta(days=config.MAX_DAYS_AHEAD - 1)
    conn = FakeConn()
    browser = ListingBrowser([LISTING, article(when.isoformat())])
    result = run(browser, conn, cutoff=date(2020, 1, 1))
    assert result.drops["future"] == 0
    assert len(conn.cur.inserts) == 1


def test_a_body_under_the_word_floor_is_never_stored():
    conn = FakeConn()
    browser = ListingBrowser([LISTING, article("2026-09-05", "Only a handful of words here.")])
    result = run(browser, conn)
    assert conn.cur.inserts == []
    assert result.drops["short"] == 1


def test_an_article_carrying_a_skip_keyword_is_never_stored():
    keywords.load(config.KEYWORDS_CSV)
    conn = FakeConn()
    browser = ListingBrowser([LISTING, article("2026-09-05", "Issued via PRNewswire. " + WORDS)])
    result = run(browser, conn)
    assert conn.cur.inserts == []
    assert result.drops["skipped"] == 1


def test_an_article_the_database_already_has_is_not_fetched():
    conn = FakeConn(known=["$H ABC260905One"])
    browser = ListingBrowser([ROW_LISTING, article("2026-09-05")])
    result = run(browser, conn, row_recipe())
    assert [c[0] for c in browser.calls] == ["https://site.test/news"]
    assert result.dupes == 1


def test_an_article_the_database_does_not_have_is_still_fetched():
    conn = FakeConn(known=["$H ABC260905Other"])
    browser = ListingBrowser([ROW_LISTING, article("2026-09-05")])
    run(browser, conn, row_recipe())
    assert "https://site.test/a" in [c[0] for c in browser.calls]


def test_a_site_that_reads_its_fields_from_the_article_page_is_still_fetched():
    # without both listing flags the filename cannot be known before the fetch
    conn = FakeConn(known=["$H ABC260905One"])
    browser = ListingBrowser([LISTING, article("2026-09-05")])
    run(browser, conn)
    assert "https://site.test/a" in [c[0] for c in browser.calls]


def test_a_site_whose_articles_were_all_duplicates_is_not_recorded_as_failed():
    store, report = FakeStore(), FakeReport()
    absorb(result(found=6, parsed=0, stored=0, dupes=6), store, report)
    assert store.results == [(101, True)]
    assert report.problems == []


def test_links_found_but_nothing_parsed_or_recognised_still_records_failure():
    store, report = FakeStore(), FakeReport()
    absorb(result(found=6, parsed=0, stored=0, dupes=0), store, report)
    assert store.results == [(101, False)]


def test_dropped_articles_reach_the_report():
    store, report = FakeStore(), FakeReport()
    absorb(result(drops={"future": 1, "short": 2, "skipped": 3}), store, report)
    assert report.drops == {"future": 1, "short": 2, "skipped": 3}


MAILING = {"sender": "scraper@example.com", "to": "desk@example.com", "cc": ""}


def test_a_mail_server_that_is_down_does_not_fail_a_finished_run(monkeypatch):
    def refuse(*args, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(scrape.mail, "send", refuse)
    notify(MAILING, Report(date(2026, 9, 1), 1), "20260915T090000", [])


def test_the_subject_names_the_run_and_what_it_did(monkeypatch):
    seen = []
    monkeypatch.setattr(scrape.mail, "send", lambda *args, **kw: seen.append(args))
    report = Report(date(2026, 9, 1), 1)
    report.site(101, 5, 5, 3, 0)
    notify(MAILING, report, "20260915T090000", ["summary", "  3 stored"])
    assert seen[0][2] == "scrape 20260915T090000 -- 3 stored, 0 error(s)"
    assert seen[0][3] == "summary\n  3 stored"


def test_the_summary_goes_to_the_addresses_the_settings_name(monkeypatch):
    seen = []
    monkeypatch.setattr(scrape.mail, "send", lambda *args, **kw: seen.append((args, kw)))
    notify(dict(MAILING, cc="editor@example.com"), Report(date(2026, 9, 1), 1), "r", [])
    assert seen[0][0][:2] == ("scraper@example.com", "desk@example.com")
    assert seen[0][1] == {"cc_addr": "editor@example.com"}
