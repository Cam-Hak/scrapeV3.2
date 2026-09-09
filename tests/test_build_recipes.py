from types import SimpleNamespace

from build_recipes import _use_listing, build, cache, is_banner, loosen, read_listing
from scraper import config
from scraper.recipe import Recipe

BASE = "https://site.test/news"
LISTING = """
<div class="loop">
  <div class="e-loop-item"><h3 class="t">One</h3><time datetime="2026-09-01"></time>
    <a class="post" href="/read/one">One</a></div>
  <div class="e-loop-item"><h3 class="t">Two</h3><time datetime="2026-09-02"></time>
    <a class="post" href="/read/two">Two</a></div>
</div>
"""
BOTH = ["https://site.test/read/one", "https://site.test/read/two"]


def recipe(**kw):
    kw.setdefault("url_filter", "")
    return Recipe(headline_selector="", date_selector="", **kw)


def test_drops_a_row_wrapper_that_matches_nothing():
    r = recipe(link_selector="a.post", item_selector=".wrong-wrapper")
    assert loosen(r, LISTING, BASE) == BOTH
    assert r.item_selector == ""


def test_drops_a_url_filter_that_matches_nothing():
    r = recipe(link_selector="a.post", url_filter="/press/")
    assert loosen(r, LISTING, BASE) == BOTH
    assert r.url_filter == ""


def test_keeps_a_url_filter_when_only_the_wrapper_is_wrong():
    r = recipe(link_selector="a.post", item_selector=".wrong-wrapper", url_filter="/read/")
    assert loosen(r, LISTING, BASE) == BOTH
    assert r.url_filter == "/read/"


def test_leaves_working_selectors_alone():
    r = recipe(link_selector="a.post", item_selector=".e-loop-item")
    assert loosen(r, LISTING, BASE) == BOTH
    assert r.item_selector == ".e-loop-item"


def test_keeps_the_row_wrapper_when_only_the_filter_is_wrong():
    r = recipe(link_selector="a.post", item_selector=".e-loop-item", url_filter="/press/")
    assert loosen(r, LISTING, BASE) == BOTH
    assert r.item_selector == ".e-loop-item"
    assert r.url_filter == ""


def test_listing_fields_are_read_after_the_recipe_is_repaired():
    links = {"listing_headline_selector": "h3.t", "listing_date_selector": "time"}
    r = recipe(link_selector="a.post", item_selector=".e-loop-item", url_filter="/press/")
    assert read_listing(r, links, LISTING, BASE) == BOTH
    assert r.headline_on_listing and r.date_on_listing


PARTIAL = """
<div class="loop">
  <div class="e-loop-item"><h3 class="t">Featured</h3>
    <a class="post" href="/read/one">One</a></div>
  <div class="e-loop-item"><a class="post" href="/read/two">Two</a></div>
</div>
"""


def test_listing_headline_is_refused_when_a_row_does_not_carry_one():
    r = recipe(link_selector="a.post", item_selector=".e-loop-item")
    _use_listing(r, {"listing_headline_selector": "h3.t"}, PARTIAL, BASE)
    assert not r.headline_on_listing
    assert r.headline_selector == ""


def test_listing_headline_is_used_when_every_row_carries_one():
    r = recipe(link_selector="a.post", item_selector=".e-loop-item")
    _use_listing(r, {"listing_headline_selector": "h3.t"}, LISTING, BASE)
    assert r.headline_on_listing


def test_a_headline_with_nothing_to_compare_against_is_not_a_banner():
    assert not is_banner("Only story on the page", [])


def test_a_headline_is_not_a_banner_when_no_other_article_yielded_one():
    assert not is_banner("A real headline", ["", ""])


def test_a_headline_repeated_on_every_article_is_a_banner():
    assert is_banner("Institute of Public Affairs", ["Institute of Public Affairs"] * 3)


def test_a_headline_that_changes_between_articles_is_not_a_banner():
    assert not is_banner("First story", ["Second story", "Third story"])


class FakeBrowser:
    def __init__(self):
        self.gets = []

    def get(self, url):
        self.gets.append(url)
        return "<html>%s</html>" % url


def test_a_page_already_loaded_is_not_fetched_again():
    browser = FakeBrowser()
    fetch = cache(browser, lambda _: None)
    assert fetch("u1") == "<html>u1</html>"
    assert fetch("u1") == "<html>u1</html>"
    fetch("u2")
    assert browser.gets == ["u1", "u2"]


def test_each_new_page_is_throttled_but_a_cached_one_is_not():
    browser = FakeBrowser()
    naps = []
    fetch = cache(browser, naps.append)
    fetch("u1")
    fetch("u1")
    fetch("u2")
    assert naps == [config.REQUEST_DELAY, config.REQUEST_DELAY]


class ListingBrowser:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, patient=False):
        self.calls.append((url, patient))
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


class FakeClient:
    def __init__(self, *replies):
        self.replies = replies
        self.asked = []
        self.messages = self

    def create(self, **kw):
        self.asked.append(kw["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(
            text=self.replies[min(len(self.asked) - 1, len(self.replies) - 1)])])


LINKS = ('{"link_selector": "a.post", "url_filter": "", "item_selector": "",'
         ' "listing_headline_selector": "", "listing_date_selector": ""}')
FIELDS = ('{"headline_selector": "h1", "date_selector": "time",'
          ' "headline_fallback": "", "date_fallback": ""}')
EMPTY = "<html><body></body></html>"
ROWS = '<html><body><a class="post" href="/read/one">One</a></body></html>'
ARTICLE = ('<html><body><h1>One</h1><time>2026-09-05</time>'
           '<p>%s</p></body></html>' % ("Body text here. " * 40))


def test_an_empty_listing_is_asked_again_patiently(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_DELAY", 0)
    browser = ListingBrowser([EMPTY, ROWS, ARTICLE])
    build(browser, FakeClient(LINKS, LINKS, FIELDS), BASE, None, (), (), ())
    assert browser.calls[0] == (BASE, False)
    assert browser.calls[1] == (BASE, True)


def test_a_listing_that_yields_links_is_not_asked_twice(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_DELAY", 0)
    browser = ListingBrowser([ROWS, ARTICLE])
    build(browser, FakeClient(LINKS, FIELDS), BASE, None, (), (), ())
    assert browser.calls[0] == (BASE, False)
    assert browser.calls[1][0] == "https://site.test/read/one"
