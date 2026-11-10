"""Emails a finished trip plan over SMTP (stdlib only, plus `markdown` for the HTML body)."""

import re
import smtplib
import ssl
import threading
import time
from collections import deque
from email.message import EmailMessage

import markdown

from .config import EMAIL_DAILY_LIMIT, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
from .logging_utils import _write_event

_ADDRESS = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")
_SECONDS_PER_DAY = 24 * 3600
_sent_at: deque[float] = deque()
_lock = threading.Lock()

_HTML_WRAPPER = (
    '<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
    'max-width:720px;margin:auto;line-height:1.5;color:#1f2937">{body}'
    '<hr style="border:none;border-top:1px solid #e5e7eb;margin-top:32px">'
    '<p style="color:#6b7280;font-size:12px">Sent by Travel Adviser. Prices and weather '
    "notes are estimates; check details before booking.</p></div>"
)


class EmailError(Exception):
    """A failure whose message is safe to show to the end user."""


def email_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def is_valid_address(address: str) -> bool:
    return len(address) <= 254 and bool(_ADDRESS.match(address))


def _reserve_slot() -> None:
    now = time.time()
    with _lock:
        while _sent_at and now - _sent_at[0] > _SECONDS_PER_DAY:
            _sent_at.popleft()
        if len(_sent_at) >= EMAIL_DAILY_LIMIT:
            raise EmailError("The daily email limit has been reached. Download the plan instead, or try again tomorrow.")
        _sent_at.append(now)


def send_plan_email(to: str, subject: str, plan_markdown: str) -> None:
    """Sends the plan as an HTML email with the Markdown attached.

    Raises EmailError (with a user-presentable message) on any failure.
    """
    if not email_configured():
        raise EmailError("Email isn't set up on this server (SMTP_USER / SMTP_PASSWORD are missing).")
    to = to.strip()
    if not is_valid_address(to):
        raise EmailError("That doesn't look like a valid email address.")

    message = EmailMessage()
    message["Subject"] = " ".join(subject.split())[:150] or "Your trip plan"
    message["From"] = SMTP_FROM
    message["To"] = to
    message.set_content(plan_markdown)
    html = markdown.markdown(plan_markdown, extensions=["tables", "sane_lists"])
    message.add_alternative(_HTML_WRAPPER.format(body=html), subtype="html")
    message.add_attachment(
        plan_markdown.encode("utf-8"), maintype="text", subtype="markdown", filename="trip_plan.md"
    )

    _reserve_slot()
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ssl.create_default_context()) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(
            "The mail server rejected the login. Check SMTP_USER / SMTP_PASSWORD "
            "(Gmail needs an App Password, not your normal password)."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailError("The mail server refused that recipient address.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Couldn't send the email ({type(exc).__name__}). Try again in a moment.") from exc

    _write_event({"event": "email_sent", "to_domain": to.rsplit("@", 1)[1].lower()})
