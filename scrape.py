import argparse
import queue
import threading
import time
from collections import namedtuple
from datetime import date, timedelta

from bs4 import BeautifulSoup

from scraper import articles, config, keywords, mail, route
from scraper.browser import Browser
from scraper.history import ERROR, OK, SKIPPED, STALE, History
from scraper.isolate import run_site_isolated, sweep_profiles
from scraper.lede import document
from scraper.parse import _norm, extract, find_items, set_dayfirst
from scraper.report import Report
from scraper.sites import by_host, load_sites
from scraper.strip import clean_title, load_strips, patterns_for
from scraper.store import Store


def log(msg):
    print(msg + "\n", end="", flush=True)  # one write so threads can't interleave inside a line


def scrape_site(browser, conn, a_id, url, recipe, cutoff, agency, drop, drop_title, prune, lines, cap=None):
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
    found = len(rows)
    if cap:
        rows = rows[:cap]
        lines.append("  limited to the first %d article(s)" % cap)
    extracted = stored = duplicates = stale = repeated = 0
    previous = None
    problems = []
    drops = {"future": 0, "short": 0, "skipped": 0}
    routed = {"E": 0, "W": 0, "short_doc": 0}
    names = _names(rows, agency[0], drop_title) if (
        recipe.headline_on_listing and recipe.date_on_listing) else {}
    have = articles.existing(conn, list(names.values()))
    horizon = date.today() + timedelta(days=config.MAX_DAYS_AHEAD)
    for i, row in enumerate(rows, 1):
        link = row["url"]
        tag = "  [%d/%d]" % (i, len(rows))
        if names.get(link) in have:
            duplicates += 1
            lines.append("%s already have it -- not fetched" % tag)
            continue
        item = extract(browser.get(link), recipe, drop, link, row, drop_title, prune)
        if not item:
            # js-built articles land after the page loads, same as the listing above
            item = extract(browser.get(link, patient=True), recipe, drop, link, row,
                           drop_title, prune)
        if not item:
            lines.append("%s no headline, date or body -- skipped" % tag)
            continue
        extracted += 1
        if item["date"] > horizon:
            drops["future"] += 1
            lines.append("%s %s is dated ahead -- dropped" % (tag, item["date"]))
            continue
        if item["date"] < cutoff:
            stale += 1
            lines.append("%s %s older than cutoff (%d in a row)" % (tag, item["date"], stale))
            # listings run newest-first, so a run of old ones means the rest are older
            if stale >= config.STOP_AFTER_OLD:
                lines.append("  stopping this site: %d older articles in a row" % stale)
                break
            continue
        stale = 0
        words = len(item["body"].split())
        if words <= config.MIN_WORDS:
            drops["short"] += 1
            lines.append("%s only %d words -- dropped" % (tag, words))
            continue
        phrase = route.skipped(item["headline"], item["body"])
        if phrase:
            drops["skipped"] += 1
            lines.append("%s skipped on %r" % (tag, phrase))
            continue
        status, comment, markers = route.decide(item["headline"], item["body"], words)
        routed[status] = routed.get(status, 0) + 1
        if route.short(words):
            routed["short_doc"] += 1
        body = document(agency[1], item["headline"], item["body"], item["date"], link)
        for mark in markers:
            body += " (%s)" % mark
        ok, reason = articles.save_article(
            conn, a_id, agency[0], item["headline"], item["date"], body, item["contact"],
            status, comment
        )
        if ok:
            stored += 1
            lines.append("%s %s stored %s %s" % (tag, item["date"], status,
                                                 item["headline"][:56]))
            if comment:
                lines.append("         %s" % comment)
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
    return found, extracted, stored, duplicates, drops, routed, problems


def _names(rows, prefix, drop_title):
    # both fields come off the listing here, so the insert's filename is known before the fetch
    found = {}
    for row in rows:
        if row["headline"] and row["date"]:
            found[row["url"]] = articles.filename(
                prefix, row["date"], articles.clean(clean_title(row["headline"], drop_title)))
    return found


Result = namedtuple("Result",
                    "a_id found parsed stored dupes drops routed problems error lines")


def run_site(browser, conn, a_id, url, recipe, cutoff, agency, drop, drop_title, prune, cap=None):
    log("  -> %s %s" % (a_id, url))  # one interleaved line so a long run shows what is in flight
    begun = time.time()
    head = ["", "%s %s" % (a_id, url)]
    lines = [] if agency[1] else ["  no lede -- the body opens with TKTK placeholders"]
    try:
        found, parsed, stored, dupes, drops, routed, problems = scrape_site(
            browser, conn, a_id, url, recipe, cutoff, agency, drop, drop_title, prune, lines, cap)
    except Exception as e:
        why = "%s: %s" % (type(e).__name__, e)
        return Result(a_id, 0, 0, 0, 0, {}, {}, [], why, head + lines + ["  ERROR " + why])
    lines.append("  %s done in %ds -- found=%s parsed=%s stored=%s dupes=%s"
                 % (a_id, time.time() - begun, found, parsed, stored, dupes))
    return Result(a_id, found, parsed, stored, dupes, drops, routed, problems, None,
                  head + lines)


def absorb(r, store, report, history=None):
    if r.error:
        store.record_result(r.a_id, False)
        report.error(r.a_id, r.error)
        state = ERROR
    else:
        # links but nothing parsed or recognised means the selectors have gone stale;
        # a site we already hold every article for never parses one, and is not stale
        healthy = r.found > 0 and (r.parsed > 0 or r.dupes > 0)
        store.record_result(r.a_id, healthy)
        report.site(r.a_id, r.found, r.parsed, r.stored, r.dupes)
        report.dropped(r.drops)
        report.sent(r.routed)
        if not healthy:
            report.problem(r.a_id, "found=%s parsed=0" % r.found)
        for problem in r.problems:
            report.problem(r.a_id, problem)
        state = OK if healthy else STALE
    if history:
        history.site(r.a_id, state, r.found, r.parsed, r.stored, r.dupes,
                     r.error or "", r.problems, r.drops, r.routed)
    log("\n".join(r.lines))


def worker(jobs, results, site_timeout=None):
    try:
        if site_timeout:
            # Isolated: each site runs in its own process with a hard timeout, so
            # a page load that never returns costs one site instead of holding
            # this worker for the rest of the run. Nothing blocking is done here,
            # so this loop cannot wedge.
            while True:
                try:
                    group = jobs.get_nowait()
                except queue.Empty:
                    return
                for job in group:
                    results.put(Result(**run_site_isolated(job, site_timeout)))
            return
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
    except BaseException as e:
        # BaseException, not Exception: an import inside seleniumbase can raise
        # SystemExit, which slips past every `except Exception` above and kills
        # the thread silently -- the run then reports "0 ran, 0 errored" and
        # gives no clue why. A worker thread never receives KeyboardInterrupt
        # (that goes to the main thread), so widening this costs nothing.
        log("worker stopped: %s: %s" % (type(e).__name__, e))


def stop(jobs):
    dropped = []
    while True:
        try:
            dropped.extend(jobs.get_nowait())
        except queue.Empty:
            return dropped


def drain(threads, results, store, report, history=None, stall_limit=None):
    # a worker that dies must not hang the drain, so watch the threads rather than a count
    last = time.time()
    while any(t.is_alive() for t in threads) or not results.empty():
        try:
            r = results.get(timeout=0.5)
        except queue.Empty:
            # A page load has no timeout of its own, and a blocked call raises
            # nothing for run_site to catch -- so one unresponsive site can hold
            # its worker forever. When every worker has gone quiet this long,
            # give up on them rather than let the whole run hang.
            if stall_limit and time.time() - last > stall_limit:
                stuck = sum(1 for t in threads if t.is_alive())
                log("  nothing has finished in %ds -- abandoning %d stuck worker(s)"
                    % (stall_limit, stuck))
                return
            continue
        last = time.time()
        absorb(r, store, report, history)


def notify(conf, report, run_id, lines):
    # both halves mail in on the same morning, so the subject has to say which one this is
    half = "house and senate" if report.senate else "all other sites"
    subject = "scrape %s, %s -- %d docs loaded, %d error(s)" % (
        run_id, half, report.stored, report.errors)
    try:
        mail.send(conf["sender"], conf["to"], subject, "\n".join(lines), cc_addr=conf["cc"])
        log("summary emailed to %s" % conf["to"])
    except Exception as e:
        # a mail server that is down must not turn a finished run into a failed one
        log("could not email the summary: %s: %s" % (type(e).__name__, e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.DEFAULT_DAYS)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--id", type=int, nargs="+")
    ap.add_argument("--from", dest="start", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=config.WORKERS)
    ap.add_argument("--max-articles", type=int)
    ap.add_argument("--stall-limit", type=int, default=config.STALL_LIMIT,
                    help="give up when no site has finished in this many seconds (0 = never)")
    ap.add_argument("--site-timeout", type=int, default=config.SITE_TIMEOUT,
                    help="kill a site that has not finished in this many seconds")
    ap.add_argument("--allow-missing-lede", action="store_true",
                    help="run sites with no lede on their agencies row, filling the"
                         " opening with TKTK placeholders -- for testing, not for loading")
    ap.add_argument("--in-process", action="store_true",
                    help="run sites in this process instead of isolating each one"
                         " -- faster, but one unresponsive site hangs its worker")
    ap.add_argument("--senate", action="store_true",
                    help="run only the sites whose url carries house or senate;"
                         " without it those are the sites left out")
    ap.add_argument("--production", action="store_true",
                    help="email the run summary when the run finishes,"
                         " to the addresses in SCRAPER_MAIL_TO")
    args = ap.parse_args()
    # read up front, so a missing setting fails before an hour of scraping rather than after
    mailing = config.mail() if args.production else None
    cutoff = date.today() - timedelta(days=args.days)
    sites = load_sites(config.SITES_CSV, args.id, args.start, args.limit, args.last,
                       senate=args.senate)
    if not sites:
        print("no matching sites")
        return

    store = Store(config.SQLITE_PATH, config.MAX_FAILURES)
    history = History(runs=config.RUNS_LOG, sites=config.RUN_SITES_LOG)
    if args.retry_failed:
        store.clear_failures()
    conn = articles.connect()
    agencies = articles.load_agencies(conn, [a_id for a_id, _ in sites])
    conn.close()
    strips = load_strips(config.STRIP_CSV)
    keywords.load(config.KEYWORDS_CSV)
    report = Report(cutoff, len(sites), days=args.days, senate=args.senate)
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
            history.site(a_id, SKIPPED, error="no recipe")
            continue
        if store.is_failed(a_id):
            log("")
            log("%s %s" % (a_id, url))
            log("  marked failed, skipping -- use --retry-failed")
            report.skip(a_id, "marked failed, skipped")
            history.site(a_id, SKIPPED, error="marked failed")
            continue
        agency = agencies.get(a_id, ("", ""))
        if not agency[1]:
            report.no_lede()
            # without a lede the document cannot be built, so the rows would be unusable
            if not args.allow_missing_lede:
                log("")
                log("%s %s" % (a_id, url))
                log("  no lede on the agencies row -- use --allow-missing-lede to run anyway")
                report.skip(a_id, "no lede")
                history.site(a_id, SKIPPED, error="no lede")
                continue
        ready.append((a_id, url, recipe, cutoff, agency,
                      patterns_for(strips, a_id), patterns_for(strips, a_id, "title"),
                      patterns_for(strips, a_id, "prune"), args.max_articles))
    for group in by_host(ready):
        jobs.put(group)

    results = queue.Queue()
    # daemon: a worker wedged inside a page load can never be joined, and a
    # non-daemon thread would keep the process alive after the summary printed
    site_timeout = 0 if args.in_process else args.site_timeout
    if site_timeout:
        # a killed Chrome never removes its profile, and they run to hundreds of
        # MB -- a previous run's leftovers would otherwise fill the disk
        swept = sweep_profiles()
        if swept:
            log("cleared %d stale browser profile(s) from a previous run" % swept)
    threads = [threading.Thread(target=worker, args=(jobs, results, site_timeout), daemon=True)
               for _ in range(max(1, args.workers))]
    for t in threads:
        t.start()
        time.sleep(1)  # Chrome launch is the one thing several workers must not do at once
    try:
        drain(threads, results, store, report, history, args.stall_limit)
    except KeyboardInterrupt:
        log("interrupted -- letting workers finish their current group, then stopping")
        for job in stop(jobs):
            report.skip(job[0], "not run -- interrupted")
            history.site(job[0], SKIPPED, error="not run -- interrupted")
        drain(threads, results, store, report, history, args.stall_limit)
    finally:
        stop(jobs)
        for t in threads:
            # bounded: a wedged worker would never return from join()
            t.join(timeout=5)

    store.close()
    history.finish(report, days=args.days, workers=args.workers)
    lines = report.lines()
    log("")
    for line in lines:
        log(line)
    if mailing:
        notify(mailing, report, history.run_id, lines)


if __name__ == "__main__":
    main()
