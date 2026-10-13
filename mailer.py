"""
Sending email.

The project has its own Gmail account. This file logs into it with the
app password kept in mail_secret.txt and sends from it.

Safety rule for the prototype: mail only ever goes to the student inboxes
on the allow-list below. Everything else is recorded as "not sent".

mail_secret.txt holds two lines, and never leaves your laptop:
    line 1: the project Gmail address
    line 2: the 16-letter app password
"""

import os
import ssl
import smtplib
from email.message import EmailMessage

SECRET_FILE = "mail_secret.txt"
STUDENT_DOMAIN = "std.cu.ac.bd"
ALLOW = {"23702051", "24702045", "24702035", "24702050"}


def _secret():
    """Returns (address, app_password), or None if the file isn't set up."""
    if not os.path.exists(SECRET_FILE):
        return None
    with open(SECRET_FILE, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if len(lines) < 2 or "@" not in lines[0]:
        return None
    return lines[0], lines[1].replace(" ", "")


def allowed(address):
    address = (address or "").strip().lower()
    if "@" not in address:
        return False
    local, domain = address.rsplit("@", 1)
    return domain == STUDENT_DOMAIN and local in ALLOW


def send(to, subject, body):
    """
    Tries to send one email. Always returns (status, note):
      sent     — Google accepted it
      blocked  — the address isn't on the allow-list, so nothing was sent
      off      — mail_secret.txt isn't set up yet
      failed   — Google refused, or the connection broke
    """
    if not allowed(to):
        return "blocked", "not on the prototype's allow-list"

    secret = _secret()
    if not secret:
        return "off", "email is not set up on this computer"
    sender, password = secret

    msg = EmailMessage()
    msg["From"] = f"EEE Records <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body + "\n\n— EEE Records, Department of Electrical and Electronic "
                    "Engineering, University of Chittagong\n(Prototype. Marks shown are sample data.)")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                              context=ssl.create_default_context(), timeout=20) as server:
            server.login(sender, password)
            server.send_message(msg)
        return "sent", "delivered to Google for sending"
    except smtplib.SMTPAuthenticationError:
        return "failed", "Google rejected the app password"
    except Exception as e:                       # no internet, timeout, and so on
        return "failed", type(e).__name__
