import email

import pytest

from scraper import mail

SERVER = {"host": "mail.example.com", "port": 587, "user": "u", "password": "p"}
FROM, TO = "scraper@example.com", "desk@example.com"


@pytest.fixture
def smtp(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, host, port):
            seen["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            seen["tls"] = context is not None

        def login(self, user, password):
            seen["login"] = (user, password)

        def sendmail(self, sender, to, text):
            seen["sent"] = (sender, to, text)

    monkeypatch.setattr(mail.smtplib, "SMTP", Fake)
    monkeypatch.setattr(mail.config, "mail", lambda: dict(SERVER))
    return seen


def parts(seen):
    return email.message_from_string(seen["sent"][2])


def body(part):
    return part.get_payload(decode=True).decode("utf-8")


def test_a_list_splits_on_commas_and_semicolons_and_ignores_spaces():
    assert mail.addresses("a@x.com, b@x.com; c@x.com") == \
        ["a@x.com", "b@x.com", "c@x.com"]


def test_no_recipients_at_all_reads_as_an_empty_list():
    assert mail.addresses("") == [] and mail.addresses(None) == []


def test_the_summary_reaches_the_server(smtp):
    mail.send(FROM, TO, "scrape 20260915 -- 3 stored", "summary\n  3 stored")
    assert smtp["server"] == ("mail.example.com", 587)
    assert smtp["login"] == ("u", "p")
    assert smtp["sent"][0] == FROM
    assert smtp["sent"][1] == [TO]


def test_the_connection_is_secured_before_the_password_is_sent(smtp):
    mail.send(FROM, TO, "A subject", "A body")
    assert smtp["tls"]


def test_the_subject_and_the_body_are_in_the_message(smtp):
    mail.send(FROM, TO, "A subject", "line one")
    sent = parts(smtp)
    assert sent["Subject"] == "A subject"
    assert body(sent.get_payload()[0]) == "line one"


def test_a_summary_with_odd_characters_survives_the_trip(smtp):
    mail.send(FROM, TO, "A subject", "Bogotá — 3 stored")
    assert body(parts(smtp).get_payload()[0]) == "Bogotá — 3 stored"


def test_a_cc_is_in_the_envelope_as_well_as_the_header(smtp):
    mail.send(FROM, TO, "A subject", "A body", cc_addr="editor@example.com")
    sender, to, text = smtp["sent"]
    assert to == [TO, "editor@example.com"]
    assert "Cc: editor@example.com" in text


def test_no_cc_writes_no_header(smtp):
    mail.send(FROM, TO, "A subject", "A body")
    assert "Cc:" not in smtp["sent"][2]


def test_an_html_version_rides_alongside_the_plain_one(smtp):
    mail.send(FROM, TO, "A subject", "plain", html="<p>rich</p>")
    sent = parts(smtp)
    assert sent.get_content_subtype() == "alternative"
    assert [p.get_content_type() for p in sent.get_payload()] == \
        ["text/plain", "text/html"]
    assert body(sent.get_payload()[1]) == "<p>rich</p>"


def test_a_blank_html_version_adds_no_part(smtp):
    mail.send(FROM, TO, "A subject", "plain", html="   ")
    assert len(parts(smtp).get_payload()) == 1


def test_an_attachment_is_carried_under_its_own_filename(smtp):
    mail.send(FROM, TO, "A subject", "see attached", attachment=b"a,b\n1,2\n",
              filename="run.csv")
    sent = parts(smtp)
    assert sent.get_content_subtype() == "mixed"
    part = sent.get_payload()[-1]
    assert part["Content-Disposition"] == 'attachment; filename="run.csv"'
    assert part.get_payload(decode=True) == b"a,b\n1,2\n"


def test_an_empty_attachment_is_still_attached(smtp):
    # b"" is falsy, so a truth test here would silently drop a zero-byte file
    mail.send(FROM, TO, "A subject", "A body", attachment=b"", filename="empty.csv")
    assert parts(smtp).get_payload()[-1]["Content-Disposition"] == \
        'attachment; filename="empty.csv"'


def test_an_attachment_with_no_filename_is_not_attached(smtp):
    mail.send(FROM, TO, "A subject", "A body", attachment=b"data")
    assert len(parts(smtp).get_payload()) == 1


def test_a_bad_address_is_caught_before_anything_is_sent(smtp):
    with pytest.raises(ValueError):
        mail.send(FROM, "desk@example.com, not-an-address", "A subject", "A body")
    assert "sent" not in smtp


def test_an_empty_recipient_list_is_an_error_not_a_silent_no_op(smtp):
    with pytest.raises(ValueError):
        mail.send(FROM, "", "A subject", "A body")
    assert "sent" not in smtp
