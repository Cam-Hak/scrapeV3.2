import csv

# AP style: months longer than five letters are abbreviated
MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June",
          "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
PLACEHOLDER = "TKTK, DATE -- TKTK issued the following news release:"
FOOTER_MARK = "* * *"


def load_ledes(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {int(row[0]): row[1] for row in csv.reader(f) if row and row[1].strip()}


def format_date(date):
    return "%s %d, %d" % (MONTHS[date.month - 1], date.day, date.year)


def render(template, date):
    # some templates carry the footer already; the opening line is all we want here
    opening = (template or PLACEHOLDER).split(FOOTER_MARK)[0].rstrip()
    return opening.replace("DATE", format_date(date))


def footer(url):
    return "%s\nOriginal text here: %s" % (FOOTER_MARK, url)
