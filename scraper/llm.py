import json

from anthropic import Anthropic
from bs4 import BeautifulSoup, Comment

from .config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_WORKSPACE_ID

DROP = ["script", "style", "svg", "noscript", "iframe", "head"]
KEEP_ATTRS = {"class", "id", "href", "datetime"}
TEXT_LIMIT = 80
SKELETON_LIMIT = 150000

LINK_PROMPT = """This is the HTML of a page that lists press releases or news articles.

Return JSON only, no prose:
{"item_selector": "<css selector>", "link_selector": "<css selector>",
 "url_filter": "<substring>", "listing_headline_selector": "<css selector>",
 "listing_date_selector": "<css selector>"}

item_selector matches the repeating row or card, one per article. link_selector
matches the anchor linking to the article, and nothing else -- avoid navigation,
category and pagination links.

Listings often already show the headline and the publication date. If they do,
give listing_headline_selector and listing_date_selector relative to one row, so
the article page never has to be parsed for them. Use "" for either when the row
does not carry it. An element showing a relative time such as "2 hours ago" or
"Yesterday" is a date element, so point at it when the row shows nothing better.

Long text below was shortened by this tool and marked " [cut]"; that mark is not
part of the page. A row headline ending in "..." or "…" is the site truncating
it, and the whole headline exists only on the article page. Give "" for
listing_headline_selector whenever the rows read that way.

url_filter is a path substring that appears in the ARTICLE urls themselves. Read
the hrefs you are selecting and copy a fragment common to them. Do not use the
path of this listing page, and do not use a domain name. Use "" whenever the
article urls share no such fragment.

HTML:
%s"""

RETRY = """Your previous answer for this site was rejected: %s
Give different selectors that avoid that problem.

"""

FIELD_PROMPT = """This is the HTML of a single press release or news article.

Return JSON only, no prose:
{"headline_selector": "<css selector>", "date_selector": "<css selector>",
 "headline_fallback": "<css selector>", "date_fallback": "<css selector>"}

Each selector must match exactly one element on this page, and must also work on
every other article on this site. Never use a class or id tied to this single
page, such as post-14410 or entry-9823. Many pages carry a site-name banner
heading, or a newsletter box, before the article headline. The headline you want
is the one that changes from article to article; anything reading the same on
every page is rejected.

For the date, if the page has no dedicated date element, press releases usually
open with a dateline like "ATLANTA, August 17, 2026" or "Montreal, QC, Aug. 31,
2026" at the start of the body, often inside <strong> or <b>. Point the date
selector at that element. Never use :contains(), and never put a month, year or
any other text from this one article into a selector. Prefer a <time> element or
one carrying a datetime attribute when the page has one. An element showing a
relative time such as "2 hours ago" or "Yesterday" is a date element too.

Other articles on this site may tag these elements differently or place them in a
different position. A fallback should be a little broader than the precise
selector, naming the same container with two or three likely tags, and at most
three alternatives. Do not sweep up a whole container with "div", "span" or "*":
an over-broad date fallback will find unrelated dates elsewhere on the page. Give
"" when the precise selector already reads the obvious element and nothing
broader would be an improvement.

Avoid selectors that depend on position, such as nth-of-type or nth-child, unless
nothing else can identify the element.

HTML:
%s"""


def make_client():
    headers = {}
    if LLM_WORKSPACE_ID:
        headers["anthropic-workspace-id"] = LLM_WORKSPACE_ID
    return Anthropic(api_key=ANTHROPIC_API_KEY, default_headers=headers)


def link_recipe(client, page):
    return _ask(client, LINK_PROMPT % page)


def field_recipe(client, page, problem=None):
    prompt = FIELD_PROMPT % page
    if problem:
        prompt = RETRY % problem + prompt
    return _ask(client, prompt)


def skeleton(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(DROP):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in KEEP_ATTRS}
    for node in soup.find_all(string=True):
        if len(node) > TEXT_LIMIT:
            node.replace_with(node[:TEXT_LIMIT] + " [cut]")
    return str(soup)[:SKELETON_LIMIT]


def _ask(client, prompt):
    reply = client.messages.create(
        model=LLM_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(_json_block(reply.content[0].text))


def _json_block(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in model reply: %r" % text[:200])
    return text[start:end + 1]
