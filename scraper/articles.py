import mysql.connector
from unidecode import unidecode

from .config import LEDE_COLUMN
from .config import mysql as mysql_config

BODY_LIMIT = 65000
STRIP = ("\u200b", "\u200c", "\u200d", "\ufeff")
# trailing headline characters in the filename -- every site in the queue uses this default
FILENAME_CHARS = 10
COMMENT_LIMIT = 255
INSERT = (
    "INSERT INTO press_release "
    "(a_id, headline, content_date, body_txt, contact_info, filename, status, headline2, uname) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
# quoted, as one server's column is `lead` -- a reserved word in MySQL 8
AGENCIES = ("SELECT a_id, filename, CONVERT(`" + LEDE_COLUMN + "` USING latin1), uname, "
            "g.descrip FROM agencies a LEFT JOIN url_grp g ON g.ug_id = a.ug_id "
            "WHERE a_id IN (%s)")
EXISTING = "SELECT filename FROM press_release WHERE filename IN (%s)"


def connect():
    return mysql.connector.connect(**mysql_config())


def load_agencies(conn, a_ids):
    """Filename prefix, lede template, uname and url group per site -- the last two come from the url group."""
    cur = conn.cursor()
    cur.execute(AGENCIES % ",".join(["%s"] * len(a_ids)), tuple(a_ids))
    found = {a: (prefix or "", lede or "", uname or "", group or "")
             for a, prefix, lede, uname, group in cur.fetchall()}
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
    # the unique key on press_release, so this is what stops an article loading twice;
    # a " cuts the name short in the TNS form, and saving it there lets the article load again
    tail = headline.replace('"', "")[-FILENAME_CHARS:]
    return "$H %s%s%s" % (prefix, date.strftime("%y%m%d"), tail)


def clean(text):
    for ch in STRIP:
        text = text.replace(ch, "")
    return unidecode(text)


def save_article(conn, a_id, prefix, headline, date, body, contact=None,
                 status="D", comment="", uname=None):
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
                             status, comment, uname))
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
