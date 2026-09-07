import sys
import time

from seleniumbase import sb_cdp

from .config import HEADLESS, REQUEST_DELAY

TURNSTILE = '[name="cf-turnstile-response"]'
CHALLENGE = "cdn-cgi/challenge-platform"
SETTLE = 2
CHALLENGE_WAIT = 30
POLL = 0.3
STABLE_READS = 3
PATIENT_READS = 20
SETTLE_POLLS = 40
SIZE = "document.documentElement.outerHTML.length"
# headless never clears Cloudflare, so run headed and park the window off-screen
OFFSCREEN = (["--window-position=-3000,-3000", "--window-size=1400,1000"]
             if sys.platform == "win32" else None)


def settled(size, sleep, stable=STABLE_READS):
    # js-built listings land after the page loads, so poll until the size holds still
    last = size()
    seen = 0
    for _ in range(SETTLE_POLLS):
        sleep(POLL)
        now = size()
        seen = seen + 1 if now == last else 0
        last = now
        if seen >= stable:
            return


def wait_for(last, now, delay):
    return max(0.0, delay - (now - last)) if last else 0.0


class Browser:
    def __init__(self, headless=HEADLESS):
        self.headless = headless
        self.sb = None
        self.last = None

    def get(self, url, patient=False):
        try:
            return self._fetch(url, patient)
        except Exception:
            pass  # one bad page is not a dead session, so spend a retry before judging
        try:
            return self._fetch(url, patient)
        except Exception:
            self.close()  # a dead session would poison every later fetch
            raise

    def _fetch(self, url, patient=False):
        pause = wait_for(self.last, time.time(), REQUEST_DELAY)
        if pause:
            time.sleep(pause)
        self.last = time.time()
        if self.sb is None:
            self.sb = sb_cdp.Chrome(url, headless=self.headless, browser_args=OFFSCREEN)
        else:
            self.sb.open(url)
        self._settle(patient)
        if self._past_challenge():
            self._settle(patient)  # the interstitial settled, the real page has not
        return self.sb.get_html()

    def _settle(self, patient=False):
        settled(lambda: self.sb.evaluate(SIZE), self.sb.sleep,
                PATIENT_READS if patient else STABLE_READS)

    def _past_challenge(self):
        # a Cloudflare interstitial can outlast the settle poll, so wait for the real page
        html = self.sb.get_html()
        if CHALLENGE not in html:
            return False
        deadline = time.time() + CHALLENGE_WAIT
        while CHALLENGE in html and time.time() < deadline:
            if self.sb.is_element_visible(TURNSTILE):
                self.sb.solve_captcha()
            self.sb.sleep(SETTLE)
            html = self.sb.get_html()
        return CHALLENGE not in html

    def close(self):
        if self.sb:
            try:
                self.sb.quit()
            except Exception:
                pass
            self.sb = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
