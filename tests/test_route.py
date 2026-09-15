from scraper import route
from scraper.keywords import load


def rules(tmp_path, text):
    path = tmp_path / "keywords.csv"
    path.write_text(text, encoding="utf-8")
    return load(str(path))


BODY_E = "body,report,E,,TNSmrp,y,\n"
BODY_W = "body,pictured,W,Check for pictured,,,\n"
HEAD_W = "headline,drought,W,Drought,,,\n"
COMMENT = "body,newsletter,,Newsletter found,,,\n"
LONG = " ".join(["word"] * 300)


def test_an_article_with_no_keyword_stays_at_d(tmp_path):
    status, comment, marker = route.decide("A title", LONG, 300, rules(tmp_path, BODY_E))
    assert (status, comment, marker) == ("D", "", [])


def test_a_body_keyword_sets_the_status_and_writes_a_comment(tmp_path):
    status, comment, _ = route.decide("A title", "see the report. " + LONG, 300,
                                      rules(tmp_path, BODY_E))
    assert status == "E"
    assert comment == "CC `report` found"


def test_the_last_check_that_matches_wins_the_status(tmp_path):
    # body E runs before headline W, so the headline hit takes the status
    status, _, _ = route.decide("drought grips the state", "see the report. " + LONG, 300,
                                rules(tmp_path, BODY_E + HEAD_W))
    assert status == "W"


def test_comments_from_every_check_accumulate(tmp_path):
    _, comment, _ = route.decide("drought grips the state", "see the report. " + LONG, 300,
                                 rules(tmp_path, BODY_E + HEAD_W))
    assert comment == "CC `report` found Drought"


def test_every_keyword_in_one_check_adds_its_comment(tmp_path):
    two = "body,pictured,W,First,,,\nbody,creative commons,W,Second,,,\n"
    _, comment, _ = route.decide("A title", "pictured under creative commons " + LONG, 300,
                                 rules(tmp_path, two))
    assert comment == "First Second"


def test_a_headline_hit_says_so_in_the_standard_wording(tmp_path):
    _, comment, _ = route.decide("a disaster area", LONG, 300,
                                 rules(tmp_path, "headline,disaster,W,,,,\n"))
    assert comment == "CC `disaster` found in headline"


def test_a_status_e_body_hit_adds_its_routing_code(tmp_path):
    _, _, marker = route.decide("A title", "see the report. " + LONG, 300,
                                rules(tmp_path, BODY_E))
    assert marker == ["TNSmrp"]


def test_every_routing_code_is_added(tmp_path):
    both = BODY_E + "body,letter,E,,TNSmlt,y,\n"
    _, comment, marker = route.decide("A title", "the report and the letter " + LONG, 300,
                                      rules(tmp_path, both))
    assert marker == ["TNSmrp", "TNSmlt"]
    assert comment == "CC `report` found CC `letter` found"


def test_one_code_shared_by_two_keywords_is_only_added_once(tmp_path):
    both = "body,report,E,,TNSmrp,y,\nbody,memo,E,,TNSmrp,,\n"
    _, _, marker = route.decide("A title", "the report and the memo " + LONG, 300,
                                rules(tmp_path, both))
    assert marker == ["TNSmrp"]


def test_a_keyword_with_no_routing_code_adds_none(tmp_path):
    both = BODY_E + "body,albanese,E,CC: Albanese,,,\n"
    _, comment, marker = route.decide("A title", "the report from albanese " + LONG, 300,
                                      rules(tmp_path, both))
    assert marker == ["TNSmrp"]
    assert comment == "CC `report` found CC: Albanese"


def test_the_routing_code_survives_a_later_check_winning_the_status(tmp_path):
    status, _, marker = route.decide("drought grips the state", "see the report. " + LONG,
                                     300, rules(tmp_path, BODY_E + HEAD_W))
    assert (status, marker) == ("W", ["TNSmrp"])


def test_a_status_w_hit_carries_no_routing_code(tmp_path):
    _, _, marker = route.decide("A title", "pictured above " + LONG, 300,
                                rules(tmp_path, BODY_W))
    assert marker == []


def test_a_comment_only_keyword_leaves_the_status_alone(tmp_path):
    status, comment, _ = route.decide("A title", "our newsletter " + LONG, 300,
                                      rules(tmp_path, COMMENT))
    assert (status, comment) == ("D", "Newsletter found")


def test_a_body_inside_the_short_band_is_marked_short(tmp_path):
    status, comment, _ = route.decide("A title", LONG, 120, rules(tmp_path, BODY_E))
    assert (status, comment) == ("W", "short doc")


def test_a_body_over_the_short_band_is_not_marked_short(tmp_path):
    status, comment, _ = route.decide("A title", LONG, 151, rules(tmp_path, BODY_E))
    assert (status, comment) == ("D", "")


def test_the_short_doc_note_comes_last(tmp_path):
    _, comment, _ = route.decide("A title", "see the report. " + LONG, 120,
                                 rules(tmp_path, BODY_E))
    assert comment == "CC `report` found short doc"


def test_the_short_doc_note_overrides_an_earlier_status(tmp_path):
    status, _, _ = route.decide("A title", "see the report. " + LONG, 120,
                                rules(tmp_path, BODY_E))
    assert status == "W"


def test_the_first_skip_keyword_names_the_article(tmp_path):
    two = "body,PRNewswire,skip,,,,\nbody,GLOBE NEWSWIRE,skip,,,,\n"
    assert route.skipped("A title", "via PRNewswire and GLOBE NEWSWIRE",
                         rules(tmp_path, two)) == "PRNewswire"


def test_a_skip_keyword_in_the_body_names_the_phrase(tmp_path):
    found = route.skipped("A title", "issued via PRNewswire today",
                          rules(tmp_path, "body,PRNewswire,skip,,,,\n"))
    assert found == "PRNewswire"


def test_a_skip_keyword_in_the_headline_names_the_phrase(tmp_path):
    found = route.skipped("The dean's list is out", "A body",
                          rules(tmp_path, "headline,dean's list,skip,,,,\n"))
    assert found == "dean's list"


def test_an_article_with_no_skip_keyword_is_kept(tmp_path):
    assert route.skipped("A title", "A body", rules(tmp_path, "body,PRNewswire,skip,,,,\n")) is None


def test_a_routing_keyword_is_not_treated_as_a_skip(tmp_path):
    assert route.skipped("A title", "see the report. " + LONG, rules(tmp_path, BODY_E)) is None
