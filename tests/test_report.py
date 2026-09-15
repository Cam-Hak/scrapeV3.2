from datetime import date

from scraper.report import Report


def report():
    return Report(date(2026, 9, 1), 1)


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


def test_sites_with_no_lede_are_called_out_once_with_a_count():
    r = report()
    r.no_lede()
    r.no_lede()
    assert any("2 site(s)" in line and "TKTK" in line for line in r.lines())


def test_nothing_is_said_when_every_site_has_a_lede():
    assert not any("TKTK" in line for line in report().lines())


def test_dropped_articles_are_counted_in_the_summary():
    r = report()
    r.dropped({"future": 1, "short": 2, "skipped": 0})
    r.dropped({"short": 3})
    assert any("1 future-dated, 5 too short, 0 on a keyword" in line for line in r.lines())


def test_nothing_is_said_when_no_article_was_dropped():
    r = report()
    r.dropped({"future": 0, "short": 0, "skipped": 0})
    assert not any("dropped:" in line for line in r.lines())


def test_a_site_that_reported_no_drops_at_all_is_not_an_error():
    r = report()
    r.dropped(None)
    assert not any("dropped:" in line for line in r.lines())
