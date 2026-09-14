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
