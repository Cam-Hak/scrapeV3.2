from scraper.strip import clean_title, load_strips, patterns_for


def write(tmp_path, text):
    path = tmp_path / "strip.csv"
    path.write_text(text, encoding="utf-8")
    return load_strips(str(path))


def test_a_row_with_only_a_body_column_loads(tmp_path):
    strips = write(tmp_path, "34684,Background:\n")
    assert patterns_for(strips, 34684) == ["Background:"]
    assert patterns_for(strips, 34684, "title") == []


def test_an_empty_column_contributes_nothing(tmp_path):
    strips = write(tmp_path, "34684,Background:,\n")
    assert strips == {("34684", "body"): ["Background:"]}


def test_each_column_feeds_its_own_mode(tmp_path):
    strips = write(tmp_path, "21911,Background:,Press Release:\n")
    assert patterns_for(strips, 21911) == ["Background:"]
    assert patterns_for(strips, 21911, "title") == ["Press Release:"]


def test_one_column_holds_several_patterns_split_on_the_separator(tmp_path):
    strips = write(tmp_path, "21911,Media contact:~Traditional Owners,Press Release:~| Newsroom\n")
    assert patterns_for(strips, 21911) == ["Media contact:", "Traditional Owners"]
    assert patterns_for(strips, 21911, "title") == ["Press Release:", "| Newsroom"]


def test_space_around_the_separator_is_not_part_of_the_pattern(tmp_path):
    strips = write(tmp_path, "21911,, Press Release: ~ MEDIA RELEASE \n")
    assert patterns_for(strips, 21911, "title") == ["Press Release:", "MEDIA RELEASE"]


def test_the_every_site_row_merges_with_the_site_row(tmp_path):
    strips = write(tmp_path, "*,,Share this\n21911,,Press Release:\n")
    assert patterns_for(strips, 21911, "title") == ["Share this", "Press Release:"]


def test_a_second_row_for_one_site_adds_to_the_first(tmp_path):
    strips = write(tmp_path, "21911,Background:,\n21911,Media contact:,\n")
    assert patterns_for(strips, 21911) == ["Background:", "Media contact:"]


def test_the_key_at_the_top_of_the_file_is_not_a_pattern(tmp_path):
    strips = write(tmp_path, "# a_id,body,title\n34684,Background:,\n")
    assert strips == {("34684", "body"): ["Background:"]}


def test_a_missing_file_is_not_an_error():
    assert patterns_for(load_strips("no-such-file.csv"), 1) == []


def test_a_prefix_is_cut_with_the_separator_it_left_behind():
    assert clean_title("Press Release: ANZ opens Perth", ["Press Release:"]) == "ANZ opens Perth"


def test_a_phrase_mid_title_does_not_glue_the_words_together():
    assert clean_title("ANZ | MEDIA | opens Perth", ["| MEDIA |"]) == "ANZ opens Perth"


def test_the_match_ignores_case():
    assert clean_title("PRESS RELEASE: ANZ opens", ["Press Release:"]) == "ANZ opens"


def test_a_pattern_is_literal_text_not_a_pattern():
    assert clean_title("Q3 (2026) results", ["(2026)"]) == "Q3 results"


def test_no_patterns_leaves_the_title_alone():
    assert clean_title("ANZ opens Perth", []) == "ANZ opens Perth"


def test_a_title_cut_down_to_nothing_comes_back_empty():
    assert clean_title("Press Release:", ["Press Release:"]) == ""
