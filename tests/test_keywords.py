from scraper.keywords import load, matches


def write(tmp_path, text):
    path = tmp_path / "keywords.csv"
    path.write_text(text, encoding="utf-8")
    return load(str(path))


def only(tmp_path, text):
    rules = write(tmp_path, text)
    assert len(rules) == 1
    return rules[0]


def test_a_row_loads_with_its_field_and_action(tmp_path):
    rule = only(tmp_path, "body,report,E,,TNSmrp,,\n")
    assert (rule["field"], rule["phrase"], rule["action"]) == ("body", "report", "E")
    assert rule["marker"] == "TNSmrp"


def test_a_blank_comment_uses_the_standard_wording(tmp_path):
    assert only(tmp_path, "body,report,E,,,,\n")["comment"] == "CC `report` found"


def test_a_headline_row_says_so_in_the_standard_wording(tmp_path):
    assert only(tmp_path, "headline,drought,W,,,,\n")["comment"] == \
        "CC `drought` found in headline"


def test_a_given_comment_is_kept_verbatim(tmp_path):
    assert only(tmp_path, "body,albanese,E,CC: Albanese,,,\n")["comment"] == "CC: Albanese"


def test_a_whole_word_phrase_matches_when_punctuation_follows(tmp_path):
    rule = only(tmp_path, "body,report,E,,,y,\n")
    assert matches(rule, "see the report.")
    assert matches(rule, "see the (report)")


def test_a_whole_word_phrase_does_not_match_a_longer_word(tmp_path):
    rule = only(tmp_path, "body,report,E,,,y,\n")
    assert not matches(rule, "Tom reports that it rained")
    assert not matches(rule, "she reported it")


def test_a_whole_word_phrase_does_not_match_inside_another_word(tmp_path):
    assert not matches(only(tmp_path, "body,letter,E,,,y,\n"), "sign up for our newsletter")


def test_a_plain_phrase_matches_inside_a_longer_word(tmp_path):
    assert matches(only(tmp_path, "body,sex,W,,,,\n"), "the sexual health clinic")


def test_a_phrase_wrapped_in_brackets_still_matches(tmp_path):
    assert matches(only(tmp_path, "headline,(r),W,,,,\n"), "Acme (R) opens a plant")


def test_a_veto_word_cancels_the_match(tmp_path):
    rule = only(tmp_path, "body,report,E,,,y,journal~journals\n")
    assert not matches(rule, "a report in the journal of medicine")
    assert not matches(rule, "a report across two journals")


def test_a_veto_word_only_matches_as_a_whole_word(tmp_path):
    # a quoted journalist is not a journal, so the report still tags
    rule = only(tmp_path, "body,report,E,,,y,journal~journals\n")
    assert matches(rule, "a report, said the journalist")
    assert matches(rule, "a report on journalism")


def test_a_veto_only_applies_to_its_own_row(tmp_path):
    rules = write(tmp_path, "body,report,E,,,y,journal\nbody,letter,E,,,y,\n")
    assert not matches(rules[0], "the report in the journal")
    assert matches(rules[1], "the letter in the journal")


def test_the_key_lines_at_the_top_of_the_file_are_not_rules(tmp_path):
    rules = write(tmp_path, "# field,phrase,action\nbody,report,E,,,,\n")
    assert len(rules) == 1


def test_a_row_for_an_unsupported_field_is_ignored(tmp_path):
    assert write(tmp_path, "date,commentary,W,Apply Rulebox,,,\n") == []


def test_a_row_without_a_phrase_is_ignored(tmp_path):
    assert write(tmp_path, "body,,E,,,,\n") == []


def test_a_short_row_still_loads(tmp_path):
    assert only(tmp_path, "body,report,skip\n")["action"] == "skip"


def test_a_missing_file_is_not_an_error():
    assert load("no-such-keywords.csv") == []


def test_empty_text_never_matches(tmp_path):
    assert not matches(only(tmp_path, "body,report,E,,,,\n"), "")
