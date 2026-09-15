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


def test_a_wire_end_marker_wrapped_in_punctuation_still_ends_the_body():
    text = "The congressman visited the site on Tuesday.\n\n-###-\n\nSign up for our newsletter."
    body, _ = clean(text, "A visit", WHEN)
    assert body == "The congressman visited the site on Tuesday."


def test_a_sentence_ending_in_ends_is_not_an_end_marker():
    text = "The program ends today.\n\nIt served 300 families."
    body, _ = clean(text, "A program", WHEN)
    assert "It served 300 families." in body


def test_an_empty_heading_at_the_end_is_dropped():
    text = "The congressman toured the river.\n\n####"
    body, _ = clean(text, "A tour", WHEN)
    assert body == "The congressman toured the river."


def test_an_empty_heading_does_not_take_the_text_above_it():
    text = "First paragraph here.\n\n####\n\nSecond paragraph here."
    body, _ = clean(text, "A tour", WHEN)
    assert "First paragraph here." in body
    assert "Second paragraph here." in body


def test_a_wire_end_marker_still_cuts_what_follows_it():
    text = "The release body.\n\n###\n\nSign up for our newsletter."
    body, _ = clean(text, "A release", WHEN)
    assert body == "The release body."


def test_a_contact_heading_that_opens_with_the_organisation_still_splits():
    text = ("The university named five trustees.\n\nBelmont University Media Contact"
            "\n\nJane Doe, Director of PR\n\njane@belmont.edu")
    body, contact = clean(text, "Five trustees", WHEN)
    assert body == "The university named five trustees."
    assert "jane@belmont.edu" in contact


def test_a_sentence_mentioning_a_media_contact_is_not_a_heading():
    text = "The senator met the media contact team today.\n\nShe praised the staff."
    body, contact = clean(text, "A meeting", WHEN)
    assert "media contact team" in body
    assert contact is None


def test_a_title_printed_twice_is_only_dropped_once_from_the_body():
    text = ("A speech to the congress\n\nA speech to the congress.\n\n"
            "It is a privilege to be here today.")
    body, _ = clean(text, "A speech to the congress", WHEN)
    assert body == "It is a privilege to be here today."


def test_a_body_that_merely_repeats_a_word_from_the_title_is_kept():
    text = "A speech to the congress\n\nThe congress met on Tuesday to debate the bill."
    body, _ = clean(text, "A speech to the congress", WHEN)
    assert body == "The congress met on Tuesday to debate the bill."


def test_an_empty_heading_between_paragraphs_is_dropped():
    text = "The parade began at noon.\n\n##\n\nA Day to Remember\n\nThe day was filled with food."
    body, _ = clean(text, "A carnival", WHEN)
    assert "##" not in body
    assert "A Day to Remember" in body
    assert "The parade began at noon." in body


def test_three_hashes_still_read_as_a_wire_end_marker():
    text = "The release body.\n\n###\n\nFollow us on social media."
    body, _ = clean(text, "A release", WHEN)
    assert body == "The release body."
