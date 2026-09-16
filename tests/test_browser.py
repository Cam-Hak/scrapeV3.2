from scraper.browser import (Browser, CHALLENGE, PATIENT_POLLS, SETTLE_POLLS, settled,
                             wait_for)


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


def test_a_patient_settle_outlasts_the_ordinary_poll_budget():
    # the page is still changing past the ordinary ceiling, then the list lands
    reads = iter(list(range(76, 76 + SETTLE_POLLS + 5)) + [276] * 40)
    naps = []
    settled(lambda: next(reads), naps.append, stable=30, polls=PATIENT_POLLS)
    assert len(naps) > SETTLE_POLLS


def test_a_patient_settle_still_gives_up_on_a_page_that_never_stops_growing():
    sizes = iter(range(100, 5000))
    naps = []
    settled(lambda: next(sizes), naps.append, stable=30, polls=PATIENT_POLLS)
    assert len(naps) == PATIENT_POLLS


def test_browser_args_survive_offscreen_being_none(monkeypatch):
    # OFFSCREEN is None off Windows; building args from it must not explode, and
    # with nothing to add the call should pass None exactly as it always did
    import scraper.browser as b

    seen = {}

    class FakeChrome:
        def __init__(self, url, headless=False, browser_args=None):
            seen["args"] = browser_args

        def sleep(self, *a, **k):
            pass

        def evaluate(self, *a, **k):
            return 10

        def get_html(self):
            return "<html></html>"

    monkeypatch.setattr(b, "OFFSCREEN", None)
    monkeypatch.setattr(b.sb_cdp, "Chrome", FakeChrome)
    monkeypatch.setattr(b, "settled", lambda *a, **k: None)

    b.Browser().get("https://site.test")
    assert seen["args"] is None

    b.Browser(user_data_dir="/tmp/profile_x").get("https://site.test")
    assert seen["args"] == ["--user-data-dir=/tmp/profile_x"]

def test_headless_is_off_unless_the_environment_asks_for_it(monkeypatch):
    from scraper import config

    monkeypatch.delenv("SCRAPER_HEADLESS", raising=False)
    assert config.headless() is False
    monkeypatch.setenv("SCRAPER_HEADLESS", "1")
    assert config.headless() is True


def test_a_browser_reads_the_setting_when_it_is_built(monkeypatch):
    # --headless sets the variable after import, so a value bound at import would miss it
    import scraper.browser as b

    monkeypatch.setenv("SCRAPER_HEADLESS", "1")
    assert b.Browser().headless is True


def test_an_explicit_choice_beats_the_environment(monkeypatch):
    import scraper.browser as b

    monkeypatch.setenv("SCRAPER_HEADLESS", "1")
    assert b.Browser(headless=False).headless is False
