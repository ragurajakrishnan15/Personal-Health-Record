"""Outgoing email.

  * SMTP_HOST set  -> real delivery over SMTP (STARTTLS on port 587 by default; SMTP_SSL=true for port 465).
  * otherwise      -> development outbox: each message is written to backend/.outbox/ and NOTHING leaves the machine.
  * MAIL_BACKEND=memory is used by tests (messages collected in `sent`).

Message bodies contain one-time links, so the outbox is git-ignored and the log never prints a body.
"""
import logging
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("phr.mail")
OUTBOX = Path(__file__).parent / ".outbox"
sent: list[dict] = []                          # MAIL_BACKEND=memory only


def _smtp_send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM", "HealthVault <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if os.getenv("SMTP_SSL", "false").lower() == "true":
        s = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx)
    else:
        s = smtplib.SMTP(host, port, timeout=15)
        s.starttls(context=ctx)
    with s:
        if os.getenv("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        s.send_message(msg)


def send(to: str, subject: str, body: str) -> None:
    """Never raises: a mail failure must not break (or reveal anything about) the request that triggered it."""
    try:
        if os.getenv("MAIL_BACKEND") == "memory":
            sent.append({"to": to, "subject": subject, "body": body})
        elif os.getenv("SMTP_HOST"):
            _smtp_send(to, subject, body)
        else:
            OUTBOX.mkdir(exist_ok=True)
            path = OUTBOX / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.monotonic_ns() % 10**6:06d}.txt"
            path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
            log.info("email written to development outbox: %s (no SMTP_HOST configured)", path.name)
    except Exception:
        log.exception("could not send email (subject %r)", subject)
