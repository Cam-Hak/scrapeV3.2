import argparse
import os
import queue
import sys
import threading
import time
import traceback
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


def page_title(html):
    tag = BeautifulSoup(html or "", "html.parser").title
    return tag.get_text(" ", strip=True)[:80] if tag else ""


def scrape_site(browser, conn, a_id, url, recipe, cutoff, agency, drop, drop_title, prune, lines, cap=None):
    listing = browser.get(url)
    rows = find_items(listing, url, recipe)
    if not rows:
        # nothing at all usually means js content that had not landed yet, so wait properly
        listing = browser.get(url, patient=True)
        rows = find_items(listing, url, recipe)
        lines.append("  listing was empty -- fetched again patiently")
        if not rows:
            # the title tells a bot wall ("Just a moment...", "Access Denied") from a changed page
            lines.append("  page title %r, %d bytes" % (page_title(listing), len(listing or "")))
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
            status, comment, agency[2]
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


def stand_in(a_id, agency):
    # no agencies row means no filename prefix either, and an empty one is shared, so
    # two sites can collide on the unique key -- the a_id keeps their filenames apart
    # a test run's docs are not real, so they must not be attributed to a real user
    return (agency[0] or "TEST%d" % a_id, agency[1], "test_uname")


def in_production(group):
    # the old loader filtered with LIKE 'M-%', which ignores case, so this does too
    return group.upper().startswith(config.PRODUCTION_GROUP)


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


def absorb(r, report, history=None):
    if r.error:
        report.error(r.a_id, r.error)
        state = ERROR
    else:
        # links but nothing parsed or recognised means the selectors have gone stale;
        # a site we already hold every article for never parses one, and is not stale
        healthy = r.found > 0 and (r.parsed > 0 or r.dupes > 0)
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
                    try:
                        results.put(Result(**run_site_isolated(job, site_timeout)))
                    except Exception as e:
                        # a site that cannot even be started must not take the worker's other sites with it
                        why = "%s: %s" % (type(e).__name__, e)
                        results.put(Result(job[0], 0, 0, 0, 0, {}, {}, [], why,
                                           ["", "%s %s" % (job[0], job[1]), "  ERROR " + why]))
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


def drain(threads, results, report, history=None, stall_limit=None):
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
        try:
            absorb(r, report, history)
        except Exception as e:
            # a result that cannot be recorded costs that site's line, not the run
            why = "%s: %s" % (type(e).__name__, e)
            log("  %s result not recorded -- %s" % (r.a_id, why))
            report.problem(r.a_id, "result not recorded -- " + why)


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
    ap.add_argument("--retry-failed", action="store_true",
                    help="does nothing now -- kept so an older command line still starts")
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
    ap.add_argument("--in-process", action="store_true",
                    help="run sites in this process instead of isolating each one"
                         " -- faster, but one unresponsive site hangs its worker")
    ap.add_argument("--headless", action="store_true",
                    help="run Chrome with no window -- quiet, but a site behind Cloudflare"
                         " will not let a headless browser through")
    ap.add_argument("--senate", action="store_true",
                    help="run only the sites whose url carries house or senate;"
                         " without it those are the sites left out")
    ap.add_argument("--production", action="store_true",
                    help="a real load: only sites in an M- url group, under their own uname,"
                         " and the summary emailed to SCRAPER_MAIL_TO. Without it every run"
                         " is a test and loads as test_uname")
    args = ap.parse_args()
    # first, so even a run that fails at startup says which code it was
    log(config.VERSION_LINE)
    if args.headless:
        os.environ["SCRAPER_HEADLESS"] = "1"  # the isolated children inherit it
    # read up front, so a missing setting fails before an hour of scraping rather than after
    mailing = config.mail() if args.production else None
    cutoff = date.today() - timedelta(days=args.days)
    sites = load_sites(config.SITES_CSV, args.id, args.start, args.limit, args.last,
                       senate=args.senate)
    if not sites:
        print("no matching sites")
        return

    # only build_recipes.py writes recipes.db
    store = Store(config.SQLITE_PATH, readonly=True)
    history = History(runs=config.RUNS_LOG, sites=config.RUN_SITES_LOG)
    conn = articles.connect()
    agencies = articles.load_agencies(conn, [a_id for a_id, _ in sites])
    conn.close()
    if args.production:
        # like the old loader's LIKE 'M-%', a site outside an M- group is never selected at all
        kept = [s for s in sites if in_production(agencies.get(s[0], ("", "", "", ""))[3])]
        if len(kept) < len(sites):
            log("%d site(s) left out, not in an %s url group"
                % (len(sites) - len(kept), config.PRODUCTION_GROUP))
        sites = kept
    strips = load_strips(config.STRIP_CSV)
    keywords.load(config.KEYWORDS_CSV)
    report = Report(cutoff, len(sites), days=args.days, senate=args.senate)
    log("%d site(s), keeping articles on or after %s" % (len(sites), cutoff))

    crashed = False
    try:
        jobs = queue.Queue()
        ready = []
        for a_id, url in sites:
            try:
                recipe = store.get_recipe(a_id)
            except (ValueError, TypeError) as e:
                # one bad recipe row must not stop every other site; a broken database still stops the run
                log("")
                log("%s %s" % (a_id, url))
                log("  recipe unreadable -- %s: %s" % (type(e).__name__, e))
                report.skip(a_id, "recipe unreadable")
                history.site(a_id, SKIPPED, error="recipe unreadable")
                continue
            if not recipe:
                log("")
                log("%s %s" % (a_id, url))
                log("  no recipe -- run build_recipes.py --id %s" % a_id)
                report.skip(a_id, "no recipe")
                history.site(a_id, SKIPPED, error="no recipe")
                continue
            prefix, lede, uname, _ = agencies.get(a_id, ("", "", "", ""))
            agency = (prefix, lede, uname)
            if not lede:
                report.no_lede()
            if not args.production:
                # a run without --production is a test, so its docs never go to a real user
                agency = stand_in(a_id, agency)
            elif not lede:
                # without a lede the document cannot be built, so the rows would be unusable
                log("")
                log("%s %s" % (a_id, url))
                log("  no lede on the agencies row")
                report.skip(a_id, "no lede")
                history.site(a_id, SKIPPED, error="no lede")
                continue
            elif not uname:
                # every doc is tied to a user by the uname, so a site without one cannot load
                log("")
                log("%s %s" % (a_id, url))
                log("  no uname on the agency's url group")
                report.skip(a_id, "no uname")
                history.site(a_id, SKIPPED, error="no uname")
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
            drain(threads, results, report, history, args.stall_limit)
        except KeyboardInterrupt:
            log("interrupted -- letting workers finish their current group, then stopping")
            for job in stop(jobs):
                report.skip(job[0], "not run -- interrupted")
                history.site(job[0], SKIPPED, error="not run -- interrupted")
            drain(threads, results, report, history, args.stall_limit)
        finally:
            stop(jobs)
            for t in threads:
                # bounded: a wedged worker would never return from join()
                t.join(timeout=5)
    except Exception as e:
        # whatever goes wrong, the run still ends with its summary, email and history
        crashed = True
        log(traceback.format_exc())
        report.problem("run", "stopped early -- %s: %s" % (type(e).__name__, e))

    store.close()
    history.finish(report, days=args.days, workers=args.workers)
    lines = report.lines()
    log("")
    for line in lines:
        log(line)
    if mailing:
        notify(mailing, report, history.run_id, lines)
    if crashed:
        sys.exit(1)


if __name__ == "__main__":
    main()
