from scraper.browser import Browser, CHALLENGE, SETTLE_POLLS, settled, wait_for


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


class TracingSb:
    # get_html returns the challenge marker for the first `challenge_reads` reads, then the real page
    def __init__(self, challenge_reads):
        self.calls = []
        self.challenge_reads = challenge_reads
        self.reads = 0

    def open(self, url):
        self.calls.append("open")

    def evaluate(self, script):
        self.calls.append("evaluate")
        return 12

    def sleep(self, secs):
        pass

    def get_html(self):
        self.calls.append("get_html")
        self.reads += 1
        return CHALLENGE if self.reads <= self.challenge_reads else "<html>real</html>"

    def is_element_visible(self, selector):
        return False


def settle_passes(calls):
    # a settle pass is a run of "evaluate" calls; a challenge check never calls evaluate
    labels = [c for c in calls if c in ("evaluate", "get_html")]
    return sum(1 for i, label in enumerate(labels)
               if label == "evaluate" and (i == 0 or labels[i - 1] != "evaluate"))


def test_settle_runs_before_the_challenge_check_and_again_once_it_clears():
    sb = TracingSb(challenge_reads=2)
    b = browser_on(sb)
    b.get("https://site.test/a")
    labels = [c for c in sb.calls if c in ("evaluate", "get_html")]
    assert labels[0] == "evaluate"
    assert settle_passes(sb.calls) == 2


def test_an_unchallenged_page_settles_exactly_once():
    sb = TracingSb(challenge_reads=0)
    b = browser_on(sb)
    b.get("https://site.test/a")
    assert settle_passes(sb.calls) == 1


def test_a_patient_settle_waits_for_a_longer_quiet_run():
    reads = iter([100] * 12)
    naps = []
    settled(lambda: next(reads), naps.append, stable=6)
    assert len(naps) == 6


def test_a_patient_settle_rides_out_a_pause_before_the_content_lands():
    # the shell holds still for four polls, then the js grid arrives
    reads = iter([76, 76, 76, 76, 276, 276, 276, 276, 276, 276, 276])
    naps = []
    settled(lambda: next(reads), naps.append, stable=4)
    assert len(naps) == 8
