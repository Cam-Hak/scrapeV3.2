import argparse
import collections
import re

from scraper import articles

SOURCE = re.compile(r"^Original text here: (\S+)", re.M)
# a day only counts when its own path segment ends, or "/2026/09/25-years-on" reads as the 25th
URL_DATE = re.compile(r"/(20\d{2})/(\d{1,2})(?=/)(?:/(\d{1,2})(?=[/?#]|$))?")
LEDE = re.compile(r"^TKTK.*?issued the following news release:\s*", re.S)
FOOTER = re.compile(r"\n\s*\*\s\*\s\*\s*\nOriginal text here:.*$", re.S)
HEAD_DATE = re.compile(r"^\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
                       r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2})")
LEFTOVER = ("for immediate release", "media contact", "press contact", "continue reading",
            "read more", "skip to main content", "cookie", "subscribe to our newsletter",
            "share this", "click here to", "javascript")
SHORT_BODY = 400
SHORT_LINE = 40


def core(body):
    # the stored body is lede + article + source footer, and only the middle is the site's
    return FOOTER.sub("", LEDE.sub("", body or "")).strip()


def source_url(body):
    found = SOURCE.search(body or "")
    return found.group(1) if found else ""


def url_date(url):
    found = URL_DATE.search(url)
    if not found:
        return None
    y, m, d = found.group(1), found.group(2), found.group(3)
    return (int(y), int(m), int(d) if d else None)


def rows(conn, a_id=None):
    cur = conn.cursor()
    sql = "SELECT pr_id, a_id, headline, content_date, body_txt FROM press_release"
    cur.execute(sql + (" WHERE a_id = %s" % int(a_id) if a_id else ""))
    out = cur.fetchall()
    cur.close()
    return out


def check(records):
    flags = collections.defaultdict(list)
    by_site = collections.defaultdict(list)
    for r in records:
        by_site[r[1]].append(r)
    for a_id, site in by_site.items():
        heads = collections.Counter(r[2] for r in site)
        bodies = collections.Counter(core(r[4]) for r in site)
        dates = {r[3] for r in site}
        if len(site) >= 3 and len(dates) == 1:
            flags["one date for the whole site"].append((a_id, None, str(dates.pop())))
        for pr_id, _, head, when, body in site:
            text = core(body)
            first = next((l for l in text.split("\n") if l.strip()), "")
            if heads[head] > 1:
                flags["headline repeats within the site"].append((a_id, pr_id, head[:70]))
            if head.rstrip().endswith(("...", "\u2026")):
                flags["headline truncated"].append((a_id, pr_id, head[-46:]))
            if HEAD_DATE.match(head):
                flags["headline starts with a date"].append((a_id, pr_id, head[:70]))
            if bodies[text] > 1:
                flags["body repeats within the site"].append((a_id, pr_id, head[:70]))
            if len(text) < SHORT_BODY:
                flags["body under %d chars" % SHORT_BODY].append(
                    (a_id, pr_id, "%d chars | %s" % (len(text), head[:50])))
            if first[:60].strip().lower() == head[:60].strip().lower():
                flags["body opens with its own headline"].append((a_id, pr_id, head[:70]))
            low = text.lower()
            for word in LEFTOVER:
                if word in low:
                    flags["leftover: %s" % word].append((a_id, pr_id, head[:56]))
            lines = [l for l in text.split("\n") if l.strip()]
            if len(lines) >= 6 and sum(len(l) < SHORT_LINE for l in lines) > len(lines) * 0.6:
                flags["mostly very short lines"].append((a_id, pr_id, head[:70]))
            got = url_date(source_url(body))
            if got and when:
                if got[0] != when.year or got[1] != when.month or (
                        got[2] and got[2] != when.day):
                    flags["date disagrees with the url"].append(
                        (a_id, pr_id, "stored %s | url %s" % (when, got)))
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int)
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()
    conn = articles.connect()
    records = rows(conn, args.id)
    conn.close()
    print("%d row(s) across %d site(s)\n" % (records and len(records) or 0,
                                             len({r[1] for r in records})))
    flags = check(records)
    for name in sorted(flags, key=lambda k: -len(flags[k])):
        hits = flags[name]
        sites = len({h[0] for h in hits})
        print("%-38s %4d row(s) across %3d site(s)" % (name, len(hits), sites))
        for a_id, pr_id, detail in hits[:args.show]:
            print("     %-7s %-8s %s" % (a_id, pr_id or "-", detail))
        if len(hits) > args.show:
            print("     ... %d more" % (len(hits) - args.show))
        print()


if __name__ == "__main__":
    main()
