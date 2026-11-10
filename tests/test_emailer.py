import pytest

from travel_adviser import emailer


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.sent, self.started_tls, self.logged_in = host, port, [], False, None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture()
def configured(monkeypatch):
    _FakeSMTP.instances.clear()
    emailer._sent_at.clear()
    monkeypatch.setattr(emailer, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(emailer, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(emailer, "SMTP_FROM", "sender@example.com")
    monkeypatch.setattr(emailer, "SMTP_PORT", 587)
    monkeypatch.setattr(emailer.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(emailer, "_write_event", lambda record: None)


def test_sends_html_and_attachment(configured):
    emailer.send_plan_email("traveler@example.com", "Your trip plan: Kyoto", "# Plan\n\n- Day 1")
    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls and smtp.logged_in == ("sender@example.com", "app-password")
    msg = smtp.sent[0]
    assert msg["To"] == "traveler@example.com" and msg["Subject"] == "Your trip plan: Kyoto"
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "<h1>Plan</h1>" in html and "<li>Day 1</li>" in html
    assert [p.get_filename() for p in msg.iter_attachments()] == ["trip_plan.md"]


@pytest.mark.parametrize(
    "bad",
    ["", "no-at-sign", "a@b", "a b@example.com", "a@example.com,b@example.com", "a@example.com\nBcc: x@y.com"],
)
def test_rejects_invalid_addresses(configured, bad):
    with pytest.raises(emailer.EmailError):
        emailer.send_plan_email(bad, "s", "body")
    assert not _FakeSMTP.instances


def test_subject_header_injection_is_flattened(configured):
    emailer.send_plan_email("traveler@example.com", "Hi\r\nBcc: attacker@example.com", "body")
    msg = _FakeSMTP.instances[0].sent[0]
    assert msg["Bcc"] is None and "\n" not in msg["Subject"]


def test_not_configured_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(emailer, "SMTP_PASSWORD", "")
    with pytest.raises(emailer.EmailError, match="isn't set up"):
        emailer.send_plan_email("traveler@example.com", "s", "body")


def test_login_failure_hides_credentials(configured, monkeypatch):
    class _Rejecting(_FakeSMTP):
        def login(self, user, password):
            raise emailer.smtplib.SMTPAuthenticationError(535, b"bad credentials app-password")

    monkeypatch.setattr(emailer.smtplib, "SMTP", _Rejecting)
    with pytest.raises(emailer.EmailError) as info:
        emailer.send_plan_email("traveler@example.com", "s", "body")
    assert "app-password" not in str(info.value) and "App Password" in str(info.value)


def test_daily_limit(configured, monkeypatch):
    monkeypatch.setattr(emailer, "EMAIL_DAILY_LIMIT", 2)
    for _ in range(2):
        emailer.send_plan_email("traveler@example.com", "s", "body")
    with pytest.raises(emailer.EmailError, match="daily email limit"):
        emailer.send_plan_email("traveler@example.com", "s", "body")
