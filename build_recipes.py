import argparse
import time

from bs4 import BeautifulSoup

from scraper import config
from scraper.browser import Browser
from scraper.lede import footer, load_ledes, render
from scraper.llm import (SKELETON_LIMIT, field_recipe, link_recipe, make_client,
                         skeleton)
from scraper.parse import _date, _norm, _text, extract, find_items, set_dayfirst
from scraper.recipe import Recipe
from scraper.sites import load_sites
from scraper.strip import load_strips, patterns_for
from scraper.store import Store

CANDIDATES = 3
VERIFY = 4
MIN_PASSES = 3
TAIL_LINES = 12
MIN_REPEATS = 3


def log(msg):
    print(msg, flush=True)


def build(browser, client, url, lede, drop, drop_title, prune=()):
    fetch = cache(browser)
    log("  loading listing page")
    listing = fetch(url)
    recipe, links, found = read_page(client, listing, url)
    if not found:
        # nothing at all usually means js content that had not landed yet, so wait properly
        log("  nothing matched -- loading the listing again patiently")
        listing = browser.get(url, patient=True)
        recipe, links, found = read_page(client, listing, url)
    log("  those match %d links" % len(found))
    if not found:
        return None, "no article links found"
    rows = {i["url"]: i for i in find_items(listing, url, recipe)}
    # the first link can be atypical, so try a few before giving up on the site
    problem = None
    for n, link in enumerate(found[:CANDIDATES], 1):
        log("  sample article %d: %s" % (n, link[:78]))
        article = fetch(link)
        if not (recipe.headline_on_listing and recipe.date_on_listing):
            art = skeleton(article)
            if len(art) >= SKELETON_LIMIT:
                log("  article skeleton TRUNCATED at %d chars" % len(art))
            fields = field_recipe(client, art, problem)
            if not recipe.headline_on_listing:
                recipe.headline_selector = fields.get("headline_selector", "")
                recipe.headline_fallback = fields.get("headline_fallback", "")
            if not recipe.date_on_listing:
                recipe.date_selector = fields.get("date_selector", "")
                recipe.date_fallback = fields.get("date_fallback", "")
            log("  headline=%r date=%r" % (recipe.headline_selector, recipe.date_selector))
        item = extract(article, recipe, drop, link, rows.get(link), drop_title, prune)
        if not item:
            problem = "the selectors matched nothing on the article page"
            log("  those selectors matched nothing on this article")
            continue
        passed, total, bodies, heads = verify_elsewhere(fetch, recipe, found, link, drop,
                                                        rows, drop_title, prune)
        if is_banner(item["headline"], heads):
            problem = ("headline_selector returned %r on every article, so it is a"
                       " banner rather than the article headline" % item["headline"][:60])
            log("  headline %r is the same on every article -- looks like a site"
                " banner, trying another sample" % item["headline"][:44])
            continue
        if passed < min(MIN_PASSES, total):
            problem = ("the selectors worked on only %d of %d other articles, so they are"
                       " too specific to one page" % (passed, total))
            log("  worked on only %d of %d other articles -- trying another sample"
                % (passed, total))
            continue
        log("  validated on %d of %d other articles" % (passed, total))
        recipe.boilerplate = learn_boilerplate([item["body"]] + bodies)
        if recipe.boilerplate:
            log("  boilerplate learned from repetition (%d lines):" % len(recipe.boilerplate))
            for line in recipe.boilerplate:
                log("    | %s" % line[:84])
        # the recipe has changed since the first extract, so take the sample again
        item = extract(article, recipe, drop, link, rows.get(link), drop_title, prune)
        if not item:
            problem = "the sample only parsed through a selector that proved to be a banner"
            log("  sample no longer parses under the final recipe -- trying another sample")
            continue
        show_sample(item, lede, link)
        return recipe, None
    return None, "selectors matched no sample article (tried %d)" % min(CANDIDATES, len(found))


def read_page(client, listing, url):
    page = skeleton(listing)
    log("  asking the model where the article links are (skeleton %d chars%s)"
        % (len(page), " -- TRUNCATED, it may not see the whole list"
           if len(page) >= SKELETON_LIMIT else ""))
    links = link_recipe(client, page)
    recipe = Recipe(links.get("link_selector", ""), links.get("url_filter", ""), "", "",
                    item_selector=links.get("item_selector", ""))
    log("  item=%r link=%r url_filter=%r"
        % (recipe.item_selector, recipe.link_selector, recipe.url_filter))
    return recipe, links, read_listing(recipe, links, listing, url)


def cache(browser, sleep=time.sleep):
    # candidates verify against each other, so the same article comes up repeatedly
    pages = {}

    def fetch(url):
        if url not in pages:
            sleep(config.REQUEST_DELAY)
            pages[url] = browser.get(url)
        return pages[url]

    return fetch


def is_banner(headline, heads):
    # a site banner reads the same on every article; a real headline does not
    return any(heads) and len({_norm(h) for h in [headline] + heads if h}) <= 1


def read_listing(recipe, links, listing, url):
    # repair the recipe first, or the listing fields are judged against broken selectors
    found = loosen(recipe, listing, url)
    _use_listing(recipe, links, listing, url)
    if recipe.date_on_listing and set_dayfirst(recipe, [BeautifulSoup(listing, "html.parser")]):
        log("  numeric dates on this site read day first")
    return found


def loosen(recipe, listing, url):
    found = _urls(recipe, listing, url)
    # the model over-constrains, so drop whichever single guess matched nothing
    for attr in ("item_selector", "url_filter"):
        guess = getattr(recipe, attr)
        if found or not guess:
            continue
        setattr(recipe, attr, "")
        found = _urls(recipe, listing, url)
        if found:
            log("  %s %r matched no link -- dropping it" % (attr, guess))
        else:
            setattr(recipe, attr, guess)
    return found


def _urls(recipe, listing, url):
    return [i["url"] for i in find_items(listing, url, recipe)]


def _use_listing(recipe, links, listing, url):
    # a row missing the field would lose its article: extract() has no fallback here
    for field in ("headline", "date"):
        sel = links.get("listing_%s_selector" % field, "")
        if not sel:
            continue
        setattr(recipe, "%s_selector" % field, sel)
        setattr(recipe, "%s_on_listing" % field, True)
        rows = find_items(listing, url, recipe)
        if rows and all(row[field] for row in rows) and not _cut(rows, field):
            log("  %s comes from the listing: %r" % (field, sel))
        else:
            setattr(recipe, "%s_selector" % field, "")
            setattr(recipe, "%s_on_listing" % field, False)


def _cut(rows, field):
    # a listing that ends the field with an ellipsis keeps the whole one on the article
    return any(str(row[field] or "").rstrip().endswith(("...", "…")) for row in rows)


def verify_elsewhere(fetch, recipe, found, used, drop, rows=None, drop_title=(), prune=()):
    # selectors derived from one page can be tied to it, so prove them on several
    others = [l for l in found[:CANDIDATES + VERIFY] if l != used][:VERIFY]
    soups = [BeautifulSoup(fetch(o), "html.parser") for o in others]
    drop_banner_fallbacks(recipe, soups)
    if not recipe.date_on_listing and set_dayfirst(recipe, soups):
        log("  numeric dates on this site read day first")
    passed, bodies, heads = 0, [], []
    for other in others:
        item = extract(fetch(other), recipe, drop, other, (rows or {}).get(other),
                       drop_title, prune)
        if item:
            passed += 1
            bodies.append(item["body"])
            heads.append(item["headline"])
    return passed, len(others), bodies, heads


def drop_banner_fallbacks(recipe, soups):
    # a fallback reading the same on every article is a site banner, not the article's own
    for field, read in (("headline_fallback", _text), ("date_fallback", _date)):
        selector = getattr(recipe, field)
        if not selector:
            continue
        seen = [v for v in (read(soup, selector) for soup in soups) if v]
        if len(seen) > 1 and len(set(seen)) == 1:
            log("  %s reads %r on all %d test articles -- dropping it"
                % (field, str(seen[0])[:56], len(seen)))
            setattr(recipe, field, "")


def learn_boilerplate(bodies):
    # boilerplate is simply the tail text that repeats across a site's articles
    if len(bodies) < MIN_REPEATS:
        return []
    counts, order = {}, []
    for body in bodies:
        for line in dict.fromkeys(body.split("\n\n")[-TAIL_LINES:]):
            line = line.strip()
            if not line:
                continue
            if line not in counts:
                order.append(line)
            counts[line] = counts.get(line, 0) + 1
    return [l for l in order if counts[l] >= MIN_REPEATS]


def show_sample(item, lede, link):
    body = "\n\n".join([render(lede, item["date"]), item["body"], footer(link)])
    lines = [l for l in body.split("\n") if l.strip()]
    log("  --- sample record ---")
    log("  headline: %s" % item["headline"][:72])
    log("  date:     %s" % item["date"])
    log("  contact:  %s" % (item["contact"].split("\n")[0][:52] if item["contact"] else "none"))
    log("  body:     %d paragraphs, %d chars" % (len(lines), len(body)))
    for line in lines[:4]:
        log("  | %s" % line[:86])
    if len(lines) > 6:
        log("  | ... %d more ..." % (len(lines) - 6))
    for line in lines[-2:]:
        log("  | %s" % line[:86])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, nargs="+")
    ap.add_argument("--from", dest="start", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    sites = load_sites(config.SITES_CSV, args.id, args.start, args.limit, args.last)
    if not sites:
        print("no matching sites")
        return

    store = Store(config.SQLITE_PATH, config.MAX_FAILURES)
    ledes = load_ledes(config.LEDES_CSV)
    strips = load_strips(config.STRIP_CSV)
    client = make_client()
    started = time.time()
    failed = []
    with Browser() as browser:
        for a_id, url in sites:
            log("")
            log("%s %s" % (a_id, url))
            if store.get_recipe(a_id) and not args.force:
                log("  already has a recipe -- use --force to rebuild")
                continue
            begun = time.time()
            try:
                recipe, error = build(browser, client, url, ledes.get(a_id),
                                      patterns_for(strips, a_id),
                                      patterns_for(strips, a_id, "title"),
                                      patterns_for(strips, a_id, "prune"))
            except Exception as e:
                recipe, error = None, "%s: %s" % (type(e).__name__, e)
            if recipe:
                store.save_recipe(a_id, recipe)
            else:
                failed.append((a_id, error))
            log("  %s (%ds)" % (error or "saved", time.time() - begun))
    store.close()
    log("")
    log("finished in %ds" % (time.time() - started))
    if failed:
        log("no recipe for %d site(s):" % len(failed))
        for a_id, error in failed:
            log("  %s %s" % (a_id, error))


if __name__ == "__main__":
    main()
