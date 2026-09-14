from datetime import date

from scraper.articles import FILENAME_CHARS, filename
from scraper.lede import document, format_date, render

WHEN = date(2026, 9, 10)
TEMPLATE = "ALEXANDRIA, Virginia, DATE -- The Vision Council issued the following news release:"


def test_the_lede_date_carries_no_year():
    assert format_date(WHEN) == "Sept. 10"
    assert format_date(date(2026, 3, 2)) == "March 2"


def test_the_date_token_is_filled_in():
    assert render(TEMPLATE, WHEN).startswith("ALEXANDRIA, Virginia, Sept. 10 -- ")


def test_a_category_tag_on_its_own_line_survives():
    assert "[Category: Health Care]" in render(
        TEMPLATE + "\r\n\r\n[Category: Health Care]", WHEN)


def test_a_stray_footer_in_the_template_is_cut():
    body = render(TEMPLATE + "\r\n\r\n* * *\r\nOriginal text here:", WHEN)
    assert "Original text here:" not in body


def test_the_document_is_laid_out_the_way_the_loader_expects():
    out = document(TEMPLATE, "A Headline", "First para.\n\nSecond para.", WHEN, "https://x.test/a")
    assert out == (
        "ALEXANDRIA, Virginia, Sept. 10 -- The Vision Council issued the following news release:"
        "\n\n* * *\n\nA Headline\n\n*\n\nFirst para.\n\nSecond para."
        "\n\n***\n\nOriginal text here: https://x.test/a")


def test_carriage_returns_from_the_stored_template_are_normalised():
    out = document(TEMPLATE + "\r\n\r\n[Category: Health Care]", "H", "Body.", WHEN, "u")
    assert "\r" not in out


def test_the_filename_is_prefix_then_yymmdd_then_the_headline_tail():
    assert filename("PP-VC", WHEN, "Rising Prices Prop Up Optical Market") == \
        "$H PP-VC260910cal Market"


def test_a_headline_shorter_than_the_tail_is_used_whole():
    assert filename("PP-VC", WHEN, "Our Hero") == "$H PP-VC260910Our Hero"
    assert len("Our Hero") < FILENAME_CHARS
