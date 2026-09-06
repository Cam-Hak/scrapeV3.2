import mysql.connector
from unidecode import unidecode

from .config import mysql as mysql_config

BODY_LIMIT = 65000
STRIP = ("\u200b", "\u200c", "\u200d", "\ufeff")
INSERT = (
    "INSERT INTO press_release "
    "(a_id, headline, content_date, body_txt, contact_info, filename, status) "
    "VALUES (%s, %s, %s, %s, %s, %s, 'D')"
)


def connect():
    return mysql.connector.connect(**mysql_config())


def clean(text):
    for ch in STRIP:
        text = text.replace(ch, "")
    return unidecode(text)


def save_article(conn, a_id, headline, date, body, contact=None):
    headline = clean(headline)
    body = clean(body)
    contact = clean(contact).encode("latin1") if contact else None
    filename = ("%s %s" % (date.isoformat(), headline))[:100]
    cur = conn.cursor()
    try:
        cur.execute(INSERT, (a_id, headline[:255], date, body[:BODY_LIMIT], contact, filename))
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
