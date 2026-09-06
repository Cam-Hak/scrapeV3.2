from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from scraper.parse import _date, _dateline, _parse_date, _relative, find_items
from scraper.recipe import Recipe

NOW = datetime(2026, 9, 4, 12, 0)


def test_a_slash_date_reads_month_first_by_default():
    assert _parse_date("03/09/2026") == date(2026, 3, 9)


def test_a_slash_date_reads_day_first_on_a_day_first_site():
    assert _parse_date("03/09/2026", dayfirst=True) == date(2026, 9, 3)


def test_a_month_name_is_unaffected_by_the_flag():
    assert _parse_date("September 2, 2026", dayfirst=True) == date(2026, 9, 2)
    assert _parse_date("2 September 2026", dayfirst=True) == date(2026, 9, 2)


def test_an_iso_date_is_unaffected_by_the_flag():
    assert _parse_date("2026-09-02", dayfirst=True) == date(2026, 9, 2)


def test_a_dateline_honours_the_flag():
    assert _dateline("MELBOURNE, 03/09/2026 -- opening line", dayfirst=True) == date(2026, 9, 3)


def test_a_date_element_honours_the_flag():
    soup = BeautifulSoup("<time>03/09/2026</time>", "html.parser")
    assert _date(soup, "time", dayfirst=True) == date(2026, 9, 3)


LISTING = """
<div class="row"><time>03/09/2026</time><a href="/read/one">One</a></div>
"""


def test_a_listing_row_date_honours_the_flag():
    r = Recipe(link_selector="a", url_filter="", headline_selector="", date_selector="time",
               item_selector=".row", date_on_listing=True, dayfirst=True)
    assert find_items(LISTING, "https://site.test/n", r)[0]["date"] == date(2026, 9, 3)


def test_a_recipe_saved_before_the_flag_existed_still_loads():
    old = ('{"link_selector": "a", "url_filter": "", "headline_selector": "h1",'
           ' "date_selector": "time"}')
    assert Recipe.from_json(old).dayfirst is False


def test_the_flag_survives_a_save_and_load():
    r = Recipe("a", "", "h1", "time", dayfirst=True)
    assert Recipe.from_json(r.to_json()).dayfirst is True


def test_hours_ago_is_the_day_it_was_read():
    assert _relative("2 hours ago", NOW) == date(2026, 9, 4)
    assert _relative("45 minutes ago", NOW) == date(2026, 9, 4)


def test_hours_are_counted_from_now_not_from_midnight():
    assert _relative("10 hours ago", datetime(2026, 9, 4, 9, 0)) == date(2026, 9, 3)
    assert _relative("10 hours ago", datetime(2026, 9, 4, 23, 0)) == date(2026, 9, 4)


def test_days_and_weeks_ago_count_backwards():
    assert _relative("3 days ago", NOW) == date(2026, 9, 1)
    assert _relative("2 weeks ago", NOW) == date(2026, 8, 21)


def test_today_and_yesterday_are_understood():
    assert _relative("Today", NOW) == date(2026, 9, 4)
    assert _relative("Yesterday", NOW) == date(2026, 9, 3)
    assert _relative("just now", NOW) == date(2026, 9, 4)


def test_a_bare_article_counts_as_one():
    assert _relative("an hour ago", NOW) == date(2026, 9, 4)
    assert _relative("a day ago", NOW) == date(2026, 9, 3)


def test_abbreviated_units_are_understood():
    assert _relative("5 mins ago", NOW) == date(2026, 9, 4)
    assert _relative("1 hr ago", NOW) == date(2026, 9, 4)
    assert _relative("45 seconds ago", NOW) == date(2026, 9, 4)
    assert _relative("2 years ago", NOW) == date(2024, 9, 4)


def test_a_prefix_in_front_of_the_ago_phrase_is_ignored():
    assert _relative("Posted 2 hours ago", NOW) == date(2026, 9, 4)
    assert _relative("Updated: 3 days ago", NOW) == date(2026, 9, 1)
    assert _relative("· 3 days ago", NOW) == date(2026, 9, 1)


def test_ago_must_be_a_whole_word():
    assert _relative("3 days agony", NOW) is None


def test_an_absurd_count_is_refused_rather_than_raising():
    assert _relative("1000000000 days ago", NOW) is None
    assert _relative("9999999999 minutes ago", NOW) is None


def test_a_real_date_is_not_relative():
    assert _relative("September 2, 2026", NOW) is None
    assert _relative("03/09/2026", NOW) is None


def test_prose_that_merely_opens_with_a_day_word_is_not_a_date():
    assert _relative("Todays Business News", NOW) is None
    assert _relative("Today's Business News", NOW) is None
    assert _relative("Today in Energy", NOW) is None
    assert _relative("Yesterdays Papers", NOW) is None


def test_a_day_word_followed_by_a_time_still_counts():
    assert _relative("Today, 3:45 PM", NOW) == date(2026, 9, 4)
    assert _relative("Yesterday 18:00", NOW) == date(2026, 9, 3)


def test_a_date_element_falls_back_to_relative_text():
    soup = BeautifulSoup("<span>2 days ago</span>", "html.parser")
    assert _date(soup, "span") == date.today() - timedelta(days=2)


def test_a_datetime_attribute_beats_the_relative_text():
    soup = BeautifulSoup('<time datetime="2026-09-02">2 days ago</time>', "html.parser")
    assert _date(soup, "time") == date(2026, 9, 2)


def test_a_later_tag_holding_a_real_date_beats_an_earlier_relative_one():
    soup = BeautifulSoup(
        '<div class="meta"><span>2 days ago</span><time>2019-08-14</time></div>',
        "html.parser")
    assert _date(soup, ".meta *") == date(2019, 8, 14)


def test_a_prefix_in_front_of_a_day_word_is_ignored():
    assert _relative("Posted today", NOW) == date(2026, 9, 4)
    assert _relative("Updated: Yesterday", NOW) == date(2026, 9, 3)
    assert _relative("Published Today", NOW) == date(2026, 9, 4)


def test_a_day_word_with_a_trailing_time_or_separator_still_counts():
    assert _relative("Yesterday at 5:00 PM", NOW) == date(2026, 9, 3)
    assert _relative("Today, 3:45 PM EST", NOW) == date(2026, 9, 4)
    assert _relative("Today |", NOW) == date(2026, 9, 4)
    assert _relative("yesterday.", NOW) == date(2026, 9, 3)


def test_prose_that_happens_to_contain_an_ago_phrase_is_not_a_date():
    assert _relative("The plant opened 5 years ago and employs 200.", NOW) is None


def test_an_ago_phrase_may_not_start_inside_another_word():
    assert _relative("China hours ago", NOW) is None
    assert _relative("COVID-19 days ago", NOW) is None


def test_months_and_years_use_calendar_arithmetic():
    assert _relative("6 months ago", NOW) == date(2026, 3, 4)
    assert _relative("1 month ago", NOW) == date(2026, 8, 4)
    assert _relative("2 years ago", NOW) == date(2024, 9, 4)
