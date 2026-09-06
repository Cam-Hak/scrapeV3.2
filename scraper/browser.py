import sys
import time

from seleniumbase import sb_cdp

from .config import HEADLESS

TURNSTILE = '[name="cf-turnstile-response"]'
CHALLENGE = "cdn-cgi/challenge-platform"
SETTLE = 2
CHALLENGE_WAIT = 30
GROW_TRIES = 5
# headless never clears Cloudflare, so run headed and park the window off-screen
OFFSCREEN = (["--window-position=-3000,-3000", "--window-size=1400,1000"]
             if sys.platform == "win32" else None)


def grown(read, sleep):
    # js-built listings land after the page loads, so read until it stops growing
    html = read()
    for _ in range(GROW_TRIES):
        sleep(SETTLE)
        latest = read()
        if len(latest) <= len(html):
            return latest
        html = latest
    return html


class Browser:
    def __init__(self, headless=HEADLESS):
        self.headless = headless
        self.sb = None

    def get(self, url):
        try:
            return self._fetch(url)
        except Exception:
            pass  # one bad page is not a dead session, so spend a retry before judging
        try:
            return self._fetch(url)
        except Exception:
            self.close()  # a dead session would poison every later fetch
            raise

    def _fetch(self, url):
        if self.sb is None:
            self.sb = sb_cdp.Chrome(url, headless=self.headless, browser_args=OFFSCREEN)
        else:
            self.sb.open(url)
        self.sb.sleep(SETTLE)
        self._past_challenge()
        return grown(self.sb.get_html, self.sb.sleep)

    def _past_challenge(self):
        # a Cloudflare interstitial can outlast SETTLE, so wait for the real page
        deadline = time.time() + CHALLENGE_WAIT
        html = self.sb.get_html()
        while CHALLENGE in html and time.time() < deadline:
            if self.sb.is_element_visible(TURNSTILE):
                self.sb.solve_captcha()
            self.sb.sleep(SETTLE)
            html = self.sb.get_html()

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
