from scraper.sites import by_host


def test_sites_on_different_hosts_become_separate_groups():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y")]
    assert by_host(sites) == [[(1, "https://a.test/x")], [(2, "https://b.test/y")]]


def test_sites_sharing_a_host_stay_in_one_group():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y"), (3, "https://a.test/z")]
    assert by_host(sites) == [[(1, "https://a.test/x"), (3, "https://a.test/z")],
                              [(2, "https://b.test/y")]]


def test_every_site_survives_the_grouping():
    sites = [(1, "https://a.test/x"), (2, "https://b.test/y"), (3, "https://a.test/z")]
    assert sorted(s for g in by_host(sites) for s in g) == sorted(sites)
