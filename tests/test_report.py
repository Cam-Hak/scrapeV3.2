from datetime import date

from scraper.config import MIN_WORDS, SHORT_DOC
from scraper.report import Report, _elapsed


def report():
    return Report(date(2026, 9, 1), 1)


def has(r, text):
    return any(text in line for line in r.lines())


def test_a_site_whose_articles_were_all_duplicates_is_not_called_empty():
    r = report()
    r.site(101, 20, 20, 0, 20)
    assert r.empty == []


def test_a_site_that_stored_and_matched_nothing_is_called_empty():
    r = report()
    r.site(101, 12, 0, 0, 0)
    assert r.empty == [101]


def test_the_same_problem_is_only_reported_once_per_site():
    r = report()
    for _ in range(40):
        r.problem(101, "1406 (22001): Data too long")
    r.problem(102, "1406 (22001): Data too long")
    assert r.problems == [(101, "1406 (22001): Data too long"),
                          (102, "1406 (22001): Data too long")]


def test_sites_with_no_lede_are_counted():
    r = report()
    r.no_lede()
    r.no_lede()
    assert has(r, "No Ledes found: 2")


def test_dropped_articles_are_counted_in_the_summary():
    r = report()
    r.dropped({"future": 1, "short": 2, "skipped": 0})
    r.dropped({"short": 3})
    assert has(r, "Article Description Too Short: 5")
    assert has(r, "Article Dated Ahead: 1")
    assert has(r, "Article Skipped Due to Keyword: 0")


def test_a_site_that_reported_no_drops_at_all_is_not_an_error():
    r = report()
    r.dropped(None)
    assert has(r, "Article Description Too Short: 0")


def test_routed_docs_are_counted_by_the_box_they_went_to():
    r = report()
    r.sent({"E": 2, "W": 1, "short_doc": 1})
    r.sent({"E": 3})
    assert has(r, "Docs Sent To Box 4 Editor Box For Phrase: 5")
    assert has(r, "Docs Sent To Box 7 Repairs: 1")
    assert has(r, "Short Docs Sent To Box 7 Repairs: 1")


def test_a_site_that_routed_nothing_at_all_is_not_an_error():
    r = report()
    r.sent(None)
    assert has(r, "Docs Sent To Box 4 Editor Box For Phrase: 0")


def test_the_summary_opens_with_the_version():
    assert report().lines()[0].startswith("Load Version ")


def test_the_parameters_name_the_run():
    r = Report(date(2026, 9, 1), 1, days=2, senate=True)
    assert has(r, "Pull House and Senate: True")
    assert has(r, "Number of days back: 2")


def test_the_word_thresholds_are_spelled_out():
    r = report()
    assert has(r, "Words Needed To Load: more than %d" % MIN_WORDS)
    assert has(r, "Short Doc Range: %d-%d words" % (MIN_WORDS, SHORT_DOC))


def test_elapsed_time_reads_as_hours_minutes_seconds():
    assert _elapsed(22160) == "6:09:20"
    assert _elapsed(0) == "0:00:00"


def test_docs_loaded_counts_what_was_stored():
    r = report()
    r.site(101, 20, 18, 12, 6)
    assert has(r, "Docs Loaded: 12")
    assert has(r, "URLS processed: 20")
    assert has(r, "DUPS skipped: 6")
