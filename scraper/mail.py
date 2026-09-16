import re
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config

ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def addresses(value):
    return [a for a in re.split(r"[,;]", (value or "").replace(" ", "")) if a]


def send(from_addr, to_addr, subject, text, html="", cc_addr="",
         attachment=None, filename=None):
    to, cc = addresses(to_addr), addresses(cc_addr)
    if not to:
        raise ValueError("no recipient -- SCRAPER_MAIL_TO is empty")
    bad = [a for a in [from_addr] + to + cc if not ADDRESS.match(a)]
    if bad:
        raise ValueError("bad email address: " + ", ".join(bad))
    msg = MIMEMultipart("mixed" if attachment is not None else "alternative")
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    if html.strip():
        msg.attach(MIMEText(html, "html", "utf-8"))
    if attachment is not None and filename:
        part = MIMEApplication(attachment, Name=filename)
        part["Content-Disposition"] = 'attachment; filename="%s"' % filename
        msg.attach(part)
    conf = config.mail()
    with smtplib.SMTP(conf["host"], conf["port"]) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(conf["user"], conf["password"])
        # a Cc has to be in the envelope as well; the header alone does not deliver it
        server.sendmail(from_addr, to + cc, msg.as_string())
