import re

# AP style: months longer than five letters are abbreviated
MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June",
          "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
PLACEHOLDER = "TKTK, DATE -- TKTK issued the following news release:"
FOOTER_MARK = "* * *"
TIDY = (
    (re.compile(r"\n\s*\n"), "\n\n"),
    (re.compile(r"(\r\n|\r|\n)+"), "\n\n"),
    (re.compile(r"\.[^\S\n]+"), ". "),
    (re.compile(r"\s*\."), "."),
    (re.compile(r"\s*,"), ","),
    (re.compile(r"  "), " "),
    (re.compile(r'\."[^\S\n]+'), '." '),
)


def format_date(date):
    return "%s %d" % (MONTHS[date.month - 1], date.day)


def render(template, date):
    # a few stored templates carry a stray footer; the opening is all we want here
    opening = (template or PLACEHOLDER).split(FOOTER_MARK)[0].rstrip()
    return opening.replace("DATE", format_date(date))


def document(template, headline, body, date, url):
    text = "%s\n\n* * *\n\n%s\n*\n%s\n\n***\n\nOriginal text here: %s" % (
        render(template, date), headline, body, url)
    for pattern, replacement in TIDY:
        text = pattern.sub(replacement, text)
    return text
