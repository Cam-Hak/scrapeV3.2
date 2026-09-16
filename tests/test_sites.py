from scraper.sites import by_host, congress, load_sites


def test_sites_on_different_hosts_become_separate_groups():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y")]
    assert by_host(sites) == [[(1, "https://a.test/x")], [(2, "https://b.test/y")]]


def test_sites_sharing_a_host_stay_in_one_group():
    # production tuples are 8-wide (a_id, url, recipe, cutoff, lede, drop, drop_title, prune) -- url stays at index 1
    sites = [(1, "https://a.test/x", None, None, None, [], [], []),
             (2, "https://b.test/y", None, None, None, [], [], []),
             (3, "https://a.test/z", None, None, None, [], [], [])]
    assert by_host(sites) == [[sites[0], sites[2]], [sites[1]]]


def test_by_host_treats_www_and_bare_domain_as_the_same_host():
    sites = [(1, "https://WWW.a.test:8443/x"), (2, "https://a.test/y")]
    assert by_host(sites) == [[(1, "https://WWW.a.test:8443/x"), (2, "https://a.test/y")]]


def test_every_site_survives_the_grouping():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y"), (3, "https://a.test/z")]
    assert sorted(s for g in by_host(sites) for s in g) == sorted(sites)


CSV = """632,https://www.collins.senate.gov/newsroom/press-releases
921,https://delauro.house.gov/media-center/press-releases
17463,https://lighthouse.mq.edu.au/media-releases
22027,https://www.earthworks.org/media-releases/
"""


def sites(tmp_path, **kw):
    path = tmp_path / "test-sites.csv"
    path.write_text(CSV, encoding="utf-8")
    return [a_id for a_id, _ in load_sites(str(path), **kw)]


def test_the_senate_half_is_the_chambers(tmp_path):
    assert sites(tmp_path, senate=True) == [632, 921]


def test_the_other_half_is_everything_else(tmp_path):
    assert sites(tmp_path, senate=False) == [17463, 22027]


def test_the_two_halves_add_up_to_the_whole_file(tmp_path):
    both = sites(tmp_path, senate=True) + sites(tmp_path, senate=False)
    assert sorted(both) == sites(tmp_path)


def test_a_word_inside_a_longer_one_is_not_a_chamber():
    assert not congress("https://lighthouse.mq.edu.au/media-releases")
    assert not congress("https://www.pahouse.com/NewsCenter")


def test_an_underscore_still_separates_the_word():
    assert congress("https://example.test/press_house_releases")


def test_the_word_is_found_whatever_its_case():
    assert congress("https://KING.SENATE.GOV/newsroom")


def test_naming_ids_outright_ignores_the_split(tmp_path):
    # --id already overrides the other selectors, so a named site always runs
    assert sites(tmp_path, only=[17463], senate=True) == [17463]


def test_the_split_is_applied_before_a_count_is_taken(tmp_path):
    assert sites(tmp_path, limit=1, senate=True) == [632]
