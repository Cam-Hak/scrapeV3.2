import argparse
import time
from datetime import date, timedelta

from bs4 import BeautifulSoup

from scraper import articles, config
from scraper.browser import Browser
from scraper.lede import footer, load_ledes, render
from scraper.parse import _norm, extract, find_items, set_dayfirst
from scraper.report import Report
from scraper.sites import load_sites
from scraper.strip import load_strips, patterns_for
from scraper.store import Store


def log(msg):
    print(msg, flush=True)


def scrape_site(browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title):
    listing = browser.get(url)
    # the site's date habit is re-read every run, so a stale flag cannot outlive one
    if recipe.date_on_listing and set_dayfirst(recipe, [BeautifulSoup(listing, "html.parser")]):
        log("  numeric dates read %s first -- recipe flag corrected" % ("day" if recipe.dayfirst else "month"))
    rows = find_items(listing, url, recipe)
    log("  listing -> %d links" % len(rows))
    extracted = stored = duplicates = stale = repeated = 0
    previous = None
    problems = []
    for i, row in enumerate(rows, 1):
        link = row["url"]
        tag = "  [%d/%d]" % (i, len(rows))
        time.sleep(config.REQUEST_DELAY)
        item = extract(browser.get(link), recipe, drop, link, row, drop_title)
        if not item:
            log("%s no headline, date or body -- skipped" % tag)
            continue
        extracted += 1
        if item["date"] < cutoff:
            stale += 1
            log("%s %s older than cutoff (%d in a row)" % (tag, item["date"], stale))
            # listings run newest-first, so a run of old ones means the rest are older
            if stale >= config.STOP_AFTER_OLD:
                log("  stopping this site: %d older articles in a row" % stale)
                break
            continue
        stale = 0
        body = "\n\n".join([render(lede, item["date"]), item["body"], footer(link)])
        ok, reason = articles.save_article(
            conn, a_id, item["headline"], item["date"], body, item["contact"]
        )
        if ok:
            stored += 1
            log("%s %s stored  %s" % (tag, item["date"], item["headline"][:58]))
        elif reason == "duplicate":
            duplicates += 1
            log("%s %s already have it" % (tag, item["date"]))
        else:
            problems.append(reason)
            log("%s %s FAILED: %s" % (tag, item["date"], reason))
        if _norm(item["headline"]) == previous:
            repeated += 1
            log("         WARNING same headline as the previous article")
        previous = _norm(item["headline"])
    if repeated:
        problems.append("%d repeated headline(s) -- selector may be a banner" % repeated)
    return len(rows), extracted, stored, duplicates, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.DEFAULT_DAYS)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--id", type=int, nargs="+")
    ap.add_argument("--from", dest="start", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cutoff = date.today() - timedelta(days=args.days)
    sites = load_sites(config.SITES_CSV, args.id, args.start, args.limit, args.last)
    if not sites:
        print("no matching sites")
        return

    store = Store(config.SQLITE_PATH, config.MAX_FAILURES)
    if args.retry_failed:
        store.clear_failures()
    ledes = load_ledes(config.LEDES_CSV)
    strips = load_strips(config.STRIP_CSV)
    conn = articles.connect()
    report = Report(cutoff, len(sites))
    log("%d site(s), keeping articles on or after %s" % (len(sites), cutoff))
    with Browser() as browser:
        for a_id, url in sites:
            log("")
            log("%s %s" % (a_id, url))
            recipe = store.get_recipe(a_id)
            if not recipe:
                log("  no recipe -- run build_recipes.py --id %s" % a_id)
                report.skip(a_id, "no recipe")
                continue
            if store.is_failed(a_id):
                log("  marked failed, skipping -- use --retry-failed")
                report.skip(a_id, "marked failed, skipped")
                continue
            lede = ledes.get(a_id)
            if not lede:
                log("  no lede -- the body will open with TKTK placeholders")
                report.no_lede()
            begun = time.time()
            try:
                found, extracted, stored, dupes, problems = scrape_site(
                    browser, conn, a_id, url, recipe, cutoff, lede,
                    patterns_for(strips, a_id), patterns_for(strips, a_id, "title")
                )
            except Exception as e:
                log("  ERROR %s: %s" % (type(e).__name__, e))
                store.record_result(a_id, False)
                report.error(a_id, "%s: %s" % (type(e).__name__, e))
                continue
            # links but nothing parsed means the selectors have gone stale
            healthy = found > 0 and extracted > 0
            store.record_result(a_id, healthy)
            report.site(a_id, found, extracted, stored, dupes)
            if not healthy:
                report.problem(a_id, "found=%s parsed=0" % found)
            for problem in problems:
                report.problem(a_id, problem)
            log("  done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                % (time.time() - begun, found, extracted, stored, dupes))

    conn.close()
    store.close()
    log("")
    for line in report.lines():
        log(line)


if __name__ == "__main__":
    main()
