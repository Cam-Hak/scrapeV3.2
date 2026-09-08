from scraper.sites import by_host


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
