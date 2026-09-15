from datetime import date

from scraper.articles import clean, existing, filename, save_article
from scraper.strip import clean_title

WHEN = date(2026, 9, 14)


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = rows
        self.sql = None
        self.args = None

    def execute(self, sql, args=None):
        self.sql, self.args = sql, args

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(rows)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def predicted(prefix, headline, when, drop_title=()):
    # what scrape.py builds from a listing row, before the article is fetched
    return filename(prefix, when, clean(clean_title(headline, drop_title)))


def test_the_predicted_filename_matches_the_one_the_insert_would_use():
    conn = FakeConn()
    headline = "Barr Applauds Trump EPA Action to Unleash American Energy"
    save_article(conn, 21459, "HR-Barr-HKY", headline, WHEN, "A body")
    assert conn.cur.args[5] == predicted("HR-Barr-HKY", headline, WHEN)


def test_the_prediction_survives_a_headline_the_strip_rules_cut():
    conn = FakeConn()
    raw = "Press Release: Barr Applauds EPA Action"
    drop = ["Press Release:"]
    save_article(conn, 21459, "HR-Barr-HKY", clean_title(raw, drop), WHEN, "A body")
    assert conn.cur.args[5] == predicted("HR-Barr-HKY", raw, WHEN, drop)


def test_a_headline_over_the_column_length_still_names_the_file_from_its_tail():
    conn = FakeConn()
    headline = "x" * 400 + "the tail"
    save_article(conn, 1, "P", headline, WHEN, "A body")
    assert conn.cur.args[5].endswith("the tail")
    assert len(conn.cur.args[1]) == 255


def test_a_status_and_a_comment_reach_the_insert():
    conn = FakeConn()
    save_article(conn, 1, "P", "A headline", WHEN, "A body", status="E",
                 comment="CC `report` found")
    assert conn.cur.args[6] == "E"
    assert conn.cur.args[7] == "CC `report` found"


def test_the_default_status_is_unchanged_for_callers_that_pass_none():
    conn = FakeConn()
    save_article(conn, 1, "P", "A headline", WHEN, "A body")
    assert conn.cur.args[6] == "D"


def test_a_comment_longer_than_the_column_is_cut():
    conn = FakeConn()
    save_article(conn, 1, "P", "A headline", WHEN, "A body", comment="x" * 400)
    assert len(conn.cur.args[7]) == 255


def test_no_comment_writes_an_empty_string_not_null():
    conn = FakeConn()
    save_article(conn, 1, "P", "A headline", WHEN, "A body")
    assert conn.cur.args[7] == ""


def test_a_comment_is_cut_after_its_characters_are_replaced():
    conn = FakeConn()
    # unidecode turns each ellipsis into three dots, so cutting first would overrun
    save_article(conn, 1, "P", "A headline", WHEN, "A body", comment="…" * 200)
    assert len(conn.cur.args[7]) == 255


def test_no_names_asks_the_database_nothing():
    conn = FakeConn()
    assert existing(conn, []) == set()
    assert conn.cur.sql is None


def test_known_filenames_come_back_as_a_set():
    conn = FakeConn(rows=[("$H a",), ("$H b",)])
    assert existing(conn, ["$H a", "$H b", "$H c"]) == {"$H a", "$H b"}
    assert conn.cur.args == ("$H a", "$H b", "$H c")
