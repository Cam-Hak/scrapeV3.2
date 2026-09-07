from scraper.browser import Browser, SETTLE_POLLS, settled, wait_for


def test_returns_once_the_size_holds_still():
    reads = iter([100, 100, 100, 100])
    naps = []
    settled(lambda: next(reads), naps.append)
    assert len(naps) == 3


def test_keeps_waiting_while_the_page_is_still_growing():
    reads = iter([76, 244, 248, 255, 255, 255, 255])
    naps = []
    settled(lambda: next(reads), naps.append)
    assert len(naps) == 6


def test_gives_up_once_the_page_never_stops_growing():
    sizes = iter(range(100, 500))
    naps = []
    settled(lambda: next(sizes), naps.append)
    assert len(naps) == SETTLE_POLLS


def test_no_wait_before_the_first_request():
    assert wait_for(None, 1000.0, 2) == 0


def test_a_slow_fetch_pays_no_extra_delay():
    assert wait_for(1000.0, 1009.0, 2) == 0


def test_a_fast_fetch_waits_out_the_remainder():
    assert wait_for(1000.0, 1000.5, 2) == 1.5


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

    def evaluate(self, script):
        return 12

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
