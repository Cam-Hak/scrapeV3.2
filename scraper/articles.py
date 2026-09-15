import mysql.connector
from unidecode import unidecode

from .config import mysql as mysql_config

BODY_LIMIT = 65000
STRIP = ("\u200b", "\u200c", "\u200d", "\ufeff")
# trailing headline characters in the filename -- every site in the queue uses this default
FILENAME_CHARS = 10
COMMENT_LIMIT = 255
INSERT = (
    "INSERT INTO press_release "
    "(a_id, headline, content_date, body_txt, contact_info, filename, status, headline2) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)
AGENCIES = ("SELECT a_id, filename, CONVERT(leads USING latin1) FROM agencies "
            "WHERE a_id IN (%s)")
EXISTING = "SELECT filename FROM press_release WHERE filename IN (%s)"


def connect():
    return mysql.connector.connect(**mysql_config())


def load_agencies(conn, a_ids):
    """Filename prefix and lede template per site -- both live on the agencies row."""
    cur = conn.cursor()
    cur.execute(AGENCIES % ",".join(["%s"] * len(a_ids)), tuple(a_ids))
    found = {a: (prefix or "", lede or "") for a, prefix, lede in cur.fetchall()}
    cur.close()
    return found


def existing(conn, names):
    """Filenames already in the table -- one query, so a site costs a single round trip."""
    if not names:
        return set()
    cur = conn.cursor()
    cur.execute(EXISTING % ",".join(["%s"] * len(names)), tuple(names))
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    return found


def filename(prefix, date, headline):
    # the unique key on press_release, so this is what stops an article loading twice
    return "$H %s%s%s" % (prefix, date.strftime("%y%m%d"), headline[-FILENAME_CHARS:])


def clean(text):
    for ch in STRIP:
        text = text.replace(ch, "")
    return unidecode(text)


def save_article(conn, a_id, prefix, headline, date, body, contact=None,
                 status="D", comment=""):
    headline = clean(headline)
    body = clean(body)
    contact = clean(contact).encode("latin1") if contact else None
    # cut after unidecode, which can lengthen the text it replaces
    comment = clean(comment)[:COMMENT_LIMIT] if comment else ""
    # built from the cleaned headline: the column is latin1 and the key must survive it
    name = filename(prefix, date, headline)
    cur = conn.cursor()
    try:
        cur.execute(INSERT, (a_id, headline[:255], date, body[:BODY_LIMIT], contact, name,
                             status, comment))
        conn.commit()
        return True, None
    except mysql.connector.IntegrityError:
        conn.rollback()
        return False, "duplicate"
    except mysql.connector.Error as e:
        conn.rollback()
        return False, str(e)[:120]
    finally:
        cur.close()
