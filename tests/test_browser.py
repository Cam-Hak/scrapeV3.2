from scraper.browser import Browser, GROW_TRIES, grown


def pages(*sizes):
    return ["x" * n for n in sizes]


def test_waits_while_the_page_is_still_rendering():
    reads = iter(pages(76, 244, 248, 255, 255))
    naps = []
    html = grown(lambda: next(reads), naps.append)
    assert len(html) == 255
    assert len(naps) == 4


def test_returns_as_soon_as_the_page_stops_growing():
    reads = iter(pages(100, 100))
    naps = []
    html = grown(lambda: next(reads), naps.append)
    assert len(html) == 100
    assert len(naps) == 1


def test_gives_up_once_the_page_keeps_growing():
    sizes = iter(range(100, 300))
    naps = []
    grown(lambda: "x" * next(sizes), naps.append)
    assert len(naps) == GROW_TRIES


class FlakySb:
    def __init__(self, failures):
        self.failures = failures
        self.opens = 0
        self.quit_called = False

    def open(self, url):
        self.opens += 1
        if self.opens <= self.failures:
            raise RuntimeError("page timed out")

    def sleep(self, secs):
        pass

    def get_html(self):
        return "<html>ok</html>"

    def is_element_visible(self, selector):
        return False

    def quit(self):
        self.quit_called = True


def browser_on(sb):
    b = Browser()
    b.sb = sb
    return b


def test_one_bad_page_does_not_cost_the_browser_session():
    sb = FlakySb(failures=1)
    b = browser_on(sb)
    assert b.get("https://site.test/a") == "<html>ok</html>"
    assert b.sb is sb
    assert not sb.quit_called


def test_a_session_that_keeps_failing_is_torn_down():
    sb = FlakySb(failures=9)
    b = browser_on(sb)
    try:
        b.get("https://site.test/a")
        raise AssertionError("expected the failure to propagate")
    except RuntimeError:
        pass
    assert sb.quit_called
    assert b.sb is None
