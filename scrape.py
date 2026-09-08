import argparse
import queue
import threading
import time
from collections import namedtuple
from datetime import date, timedelta

from bs4 import BeautifulSoup

from scraper import articles, config
from scraper.browser import Browser
from scraper.lede import footer, load_ledes, render
from scraper.parse import _norm, extract, find_items, set_dayfirst
from scraper.report import Report
from scraper.sites import by_host, load_sites
from scraper.strip import load_strips, patterns_for
from scraper.store import Store


def log(msg):
    print(msg + "\n", end="", flush=True)  # one write so threads can't interleave inside a line


def scrape_site(browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title, prune, lines):
    listing = browser.get(url)
    rows = find_items(listing, url, recipe)
    if not rows:
        # nothing at all usually means js content that had not landed yet, so wait properly
        listing = browser.get(url, patient=True)
        rows = find_items(listing, url, recipe)
        lines.append("  listing was empty -- fetched again patiently")
    # the site's date habit is re-read every run, so a stale flag cannot outlive one
    if recipe.date_on_listing and set_dayfirst(recipe, [BeautifulSoup(listing, "html.parser")]):
        lines.append("  numeric dates read %s first -- recipe flag corrected" % ("day" if recipe.dayfirst else "month"))
    lines.append("  listing -> %d links" % len(rows))
    extracted = stored = duplicates = stale = repeated = 0
    previous = None
    problems = []
    for i, row in enumerate(rows, 1):
        link = row["url"]
        tag = "  [%d/%d]" % (i, len(rows))
        item = extract(browser.get(link), recipe, drop, link, row, drop_title, prune)
        if not item:
            lines.append("%s no headline, date or body -- skipped" % tag)
            continue
        extracted += 1
        if item["date"] < cutoff:
            stale += 1
            lines.append("%s %s older than cutoff (%d in a row)" % (tag, item["date"], stale))
            # listings run newest-first, so a run of old ones means the rest are older
            if stale >= config.STOP_AFTER_OLD:
                lines.append("  stopping this site: %d older articles in a row" % stale)
                break
            continue
        stale = 0
        body = "\n\n".join([render(lede, item["date"]), item["body"], footer(link)])
        ok, reason = articles.save_article(
            conn, a_id, item["headline"], item["date"], body, item["contact"]
        )
        if ok:
            stored += 1
            lines.append("%s %s stored  %s" % (tag, item["date"], item["headline"][:58]))
        elif reason == "duplicate":
            duplicates += 1
            lines.append("%s %s already have it" % (tag, item["date"]))
        else:
            problems.append(reason)
            lines.append("%s %s FAILED: %s" % (tag, item["date"], reason))
        if _norm(item["headline"]) == previous:
            repeated += 1
            lines.append("         WARNING same headline as the previous article")
        previous = _norm(item["headline"])
    if repeated:
        problems.append("%d repeated headline(s) -- selector may be a banner" % repeated)
    return len(rows), extracted, stored, duplicates, problems


Result = namedtuple("Result", "a_id found parsed stored dupes problems error lines")


def run_site(browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title, prune):
    log("  -> %s %s" % (a_id, url))  # one interleaved line so a long run shows what is in flight
    begun = time.time()
    head = ["", "%s %s" % (a_id, url)]
    lines = [] if lede else ["  no lede -- the body will open with TKTK placeholders"]
    try:
        found, parsed, stored, dupes, problems = scrape_site(
            browser, conn, a_id, url, recipe, cutoff, lede, drop, drop_title, prune, lines)
    except Exception as e:
        why = "%s: %s" % (type(e).__name__, e)
        return Result(a_id, 0, 0, 0, 0, [], why, head + lines + ["  ERROR " + why])
    lines.append("  %s done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                 % (a_id, time.time() - begun, found, parsed, stored, dupes))
    return Result(a_id, found, parsed, stored, dupes, problems, None, head + lines)


def absorb(r, store, report):
    if r.error:
        store.record_result(r.a_id, False)
        report.error(r.a_id, r.error)
    else:
        # links but nothing parsed means the selectors have gone stale
        healthy = r.found > 0 and r.parsed > 0
        store.record_result(r.a_id, healthy)
        report.site(r.a_id, r.found, r.parsed, r.stored, r.dupes)
        if not healthy:
            report.problem(r.a_id, "found=%s parsed=0" % r.found)
        for problem in r.problems:
            report.problem(r.a_id, problem)
    log("\n".join(r.lines))


def worker(jobs, results):
    try:
        with Browser() as browser:
            conn = articles.connect()
            try:
                while True:
                    try:
                        group = jobs.get_nowait()
                    except queue.Empty:
                        return
                    for job in group:
                        results.put(run_site(browser, conn, *job))
            finally:
                conn.close()
    except Exception as e:
        log("worker stopped: %s: %s" % (type(e).__name__, e))


def stop(jobs):
    dropped = []
    while True:
        try:
            dropped.extend(jobs.get_nowait())
        except queue.Empty:
            return dropped


def drain(threads, results, store, report):
    # a worker that dies must not hang the drain, so watch the threads rather than a count
    while any(t.is_alive() for t in threads) or not results.empty():
        try:
            r = results.get(timeout=0.5)
        except queue.Empty:
            continue
        absorb(r, store, report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.DEFAULT_DAYS)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--id", type=int, nargs="+")
    ap.add_argument("--from", dest="start", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=config.WORKERS)
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
    report = Report(cutoff, len(sites))
    log("%d site(s), keeping articles on or after %s" % (len(sites), cutoff))

    jobs = queue.Queue()
    ready = []
    for a_id, url in sites:
        recipe = store.get_recipe(a_id)
        if not recipe:
            log("")
            log("%s %s" % (a_id, url))
            log("  no recipe -- run build_recipes.py --id %s" % a_id)
            report.skip(a_id, "no recipe")
            continue
        if store.is_failed(a_id):
            log("")
            log("%s %s" % (a_id, url))
            log("  marked failed, skipping -- use --retry-failed")
            report.skip(a_id, "marked failed, skipped")
            continue
        lede = ledes.get(a_id)
        if not lede:
            report.no_lede()
        ready.append((a_id, url, recipe, cutoff, lede,
                      patterns_for(strips, a_id), patterns_for(strips, a_id, "title"),
                      patterns_for(strips, a_id, "prune")))
    for group in by_host(ready):
        jobs.put(group)

    results = queue.Queue()
    threads = [threading.Thread(target=worker, args=(jobs, results))
               for _ in range(max(1, args.workers))]
    for t in threads:
        t.start()
        time.sleep(1)  # Chrome launch is the one thing several workers must not do at once
    try:
        drain(threads, results, store, report)
    except KeyboardInterrupt:
        log("interrupted -- letting workers finish their current group, then stopping")
        for job in stop(jobs):
            report.skip(job[0], "not run -- interrupted")
        drain(threads, results, store, report)
    finally:
        stop(jobs)
        for t in threads:
            t.join()

    store.close()
    log("")
    for line in report.lines():
        log(line)


if __name__ == "__main__":
    main()
