from datetime import date

from scraper.body import clean

WHEN = date(2026, 9, 4)
BLOB = ('[{"title":"Writing Major","link":"https://x.edu/writing/","keywords":"composition"},'
        '{"title":"Ensembles","link":"https://x.edu/music/","keywords":"choir, band"}]')


def test_a_serialised_data_blob_is_dropped():
    text = "The university announced a new program.\n\n%s" % BLOB
    body, _ = clean(text, "A new program", WHEN)
    assert "The university announced a new program." in body
    assert "Writing Major" not in body


def test_a_json_blob_that_opens_with_an_object_is_dropped():
    text = '{"items":[1,2,3],"total":3}\n\nThe agency issued a statement on Tuesday.'
    body, _ = clean(text, "A statement", WHEN)
    assert body == "The agency issued a statement on Tuesday."


def test_prose_that_merely_mentions_brackets_is_kept():
    text = 'The report [see note] covers "title" and other terms.'
    body, _ = clean(text, "A report", WHEN)
    assert body == text


def test_a_long_paragraph_repeated_word_for_word_is_kept_once():
    quote = ("“Today, I voted to pass legislation to keep the government funded at current"
             " levels and provide certainty for the American people.”")
    text = ("WASHINGTON – The congressman released the following statement.  \n  \n%s  \n\n\n%s"
            % (quote, quote))
    body, _ = clean(text, "A statement", WHEN)
    assert body.count(quote) == 1
    assert "released the following statement." in body


def test_learned_boilerplate_drops_only_lines_that_match_it_whole():
    lede = "ASHBURN, Va. – DXC Technology today announced a new partnership with a bank."
    text = "%s\n\nIt depends on the bank.\n\nAbout DXC Technology\n\n/ENDS" % lede
    body, _ = clean(text, "A partnership", WHEN,
                    boilerplate=["DXC Technology", "About DXC Technology", "/ENDS"])
    assert body == "%s\n\nIt depends on the bank." % lede


def test_strip_patterns_still_drop_lines_that_contain_them():
    text = "The agency issued a statement on Tuesday.\n\nPhotos are available at agency.gov/photos."
    body, _ = clean(text, "A statement", WHEN, drop=["agency.gov/photos"])
    assert body == "The agency issued a statement on Tuesday."


def test_short_lines_that_repeat_are_kept():
    text = ("Revenue rose in both quarters of the year.\n\nTotal\n\n$120 million in sales."
            "\n\nTotal\n\n$98 million in sales.")
    body, _ = clean(text, "Revenue rose", WHEN)
    assert body.count("Total") == 2
