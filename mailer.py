"""
Sending email.

Two ways to send, picked automatically:

1. Brevo (an email-sending service) over the web.
   Used when BREVO_API_KEY is set. This is the way that works on Render's
   free plan, which blocks ordinary email (SMTP) ports.
     BREVO_API_KEY   the key from Brevo -> SMTP & API -> API keys
     MAIL_FROM       the sender address you verified in Brevo
     MAIL_FROM_NAME  optional, defaults to "EEE Records"

2. Gmail with an app password (SMTP). Works on a laptop.
   Either the settings MAIL_USER + MAIL_APP_PASSWORD, or mail_secret.txt
   with two lines: the Gmail address, then the 16-letter app password.

Who may receive mail:
   by default only the prototype's allow-list below.
   MAIL_ALLOW_ALL=1  -> any @std.cu.ac.bd student, plus OFFICE_EMAIL
   OFFICE_EMAIL      -> where office alerts go (a team test address is fine)
   CHAIRMAN_EMAIL    -> also receives facilities complaints

Sending never makes a page wait: send_later() puts a message on a queue
and a background worker sends it.
"""

import os
import ssl
import json
import queue
import smtplib
import threading
from email.message import EmailMessage
from urllib.request import Request, urlopen

SECRET_FILE = "mail_secret.txt"
STUDENT_DOMAIN = "std.cu.ac.bd"
ALLOW = {"23702051", "24702045", "24702035", "24702050"}

FOOTER = ("\n\n— EEE Records, Department of Electrical and Electronic Engineering, "
          "University of Chittagong\n(Prototype.)")


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def office_address():
    return _env("OFFICE_EMAIL").lower() or None


def _smtp_secret():
    """(address, app_password) for Gmail, or None."""
    user, pw = _env("MAIL_USER"), _env("MAIL_APP_PASSWORD").replace(" ", "")
    if user and pw:
        return user, pw
    if not os.path.exists(SECRET_FILE):
        return None
    with open(SECRET_FILE, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if len(lines) < 2 or "@" not in lines[0]:
        return None
    return lines[0], lines[1].replace(" ", "")


def method():
    """Which way email would go right now: 'brevo', 'gmail' or None."""
    if _env("BREVO_API_KEY") and _env("MAIL_FROM"):
        return "brevo"
    if _smtp_secret():
        return "gmail"
    return None


def allowed(address):
    address = (address or "").strip().lower()
    if "@" not in address:
        return False
    if address in (office_address(), _env("CHAIRMAN_EMAIL").lower() or None):
        return True
    local, domain = address.rsplit("@", 1)
    if domain != STUDENT_DOMAIN:
        return False
    return _env("MAIL_ALLOW_ALL") == "1" or local in ALLOW


def _via_brevo(to, subject, text):
    body = json.dumps({
        "sender": {"email": _env("MAIL_FROM"), "name": _env("MAIL_FROM_NAME", "EEE Records")},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }).encode()
    ask = Request("https://api.brevo.com/v3/smtp/email", data=body, method="POST",
                  headers={"api-key": _env("BREVO_API_KEY"), "accept": "application/json",
                           "content-type": "application/json"})
    with urlopen(ask, timeout=20) as answer:
        if answer.status >= 300:
            raise RuntimeError(f"Brevo answered {answer.status}")


def _via_gmail(to, subject, text):
    sender, password = _smtp_secret()
    msg = EmailMessage()
    msg["From"] = f"EEE Records <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context(), timeout=20) as server:
        server.login(sender, password)
        server.send_message(msg)


def send(to, subject, body):
    """
    Tries to send one email now. Always returns (status, note):
      sent     — the email service accepted it
      blocked  — the address isn't allowed to receive mail from the prototype
      off      — no way to send email is set up
      failed   — the service refused, or the connection broke
    """
    if not allowed(to):
        return "blocked", "not on the prototype's allow-list"
    how = method()
    if not how:
        return "off", "email is not set up on this computer"
    try:
        (_via_brevo if how == "brevo" else _via_gmail)(to, subject, body + FOOTER)
        return "sent", f"accepted for delivery ({how})"
    except smtplib.SMTPAuthenticationError:
        return "failed", "Google rejected the app password"
    except Exception as e:                       # no internet, timeout, refused key...
        print(f"  [mail] could not send to {to}: {type(e).__name__}: {e}", flush=True)
        return "failed", type(e).__name__


# ------------------------------------------------------------------
# background sending, so a teacher saving 50 marks never waits for 50 emails
# ------------------------------------------------------------------
_queue = queue.Queue()
_worker = None


def _work():
    while True:
        to, subject, body = _queue.get()
        status, note = send(to, subject, body)
        print(f"  [mail] {status}: {subject} -> {to} ({note})", flush=True)
        _queue.task_done()


def send_later(to, subject, body):
    """Queue an email and return at once. Nothing happens if it isn't allowed."""
    global _worker
    if not allowed(to) or not method():
        return False
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, daemon=True)
        _worker.start()
    _queue.put((to, subject, body))
    return True
