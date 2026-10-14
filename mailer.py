"""
Sending email.

Three ways to send, picked automatically in this order:

1. The Gmail API over the web (used on Render).
   Render's free plan blocks ordinary email (SMTP) ports, but this goes over
   the normal web connection, so it works there.
     GMAIL_CLIENT_ID      from Google Cloud -> Google Auth Platform -> Clients
     GMAIL_CLIENT_SECRET  same place
     GMAIL_REFRESH_TOKEN  from the OAuth Playground (scope gmail.send)
     MAIL_FROM            the Gmail address the token belongs to
     MAIL_FROM_NAME       optional, defaults to "EEE Records"
   While the Google Cloud app is in "Testing", the refresh token stops
   working after 7 days (the log then shows invalid_grant). Make a new one
   in the Playground and paste it into GMAIL_REFRESH_TOKEN.

2. Brevo (an email-sending service) over the web, if BREVO_API_KEY is set.

3. Gmail with an app password (SMTP). Works on a laptop.
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
import time
import base64
import smtplib
import threading
from email.message import EmailMessage
from urllib.error import HTTPError
from urllib.parse import urlencode
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


def _gmail_api_ready():
    return all(_env(n) for n in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                                 "GMAIL_REFRESH_TOKEN", "MAIL_FROM"))


def method():
    """Which way email would go right now: 'gmail-api', 'brevo', 'gmail' or None."""
    if _gmail_api_ready():
        return "gmail-api"
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


# ------------------------------------------------------------------
# Gmail API: swap the long-lived refresh token for a 1-hour access token,
# then hand Google the finished email.
# ------------------------------------------------------------------
_token = {"value": None, "until": 0.0}
_token_lock = threading.Lock()


def _gmail_access_token():
    with _token_lock:
        if _token["value"] and time.time() < _token["until"]:
            return _token["value"]
        form = urlencode({
            "client_id": _env("GMAIL_CLIENT_ID"),
            "client_secret": _env("GMAIL_CLIENT_SECRET"),
            "refresh_token": _env("GMAIL_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        }).encode()
        ask = Request("https://oauth2.googleapis.com/token", data=form, method="POST",
                      headers={"content-type": "application/x-www-form-urlencoded"})
        with urlopen(ask, timeout=20) as answer:
            got = json.loads(answer.read())
        _token["value"] = got["access_token"]
        # renew a minute early so a token never runs out mid-send
        _token["until"] = time.time() + int(got.get("expires_in", 3600)) - 60
        return _token["value"]


def _via_gmail_api(to, subject, text):
    msg = EmailMessage()
    msg["From"] = f'{_env("MAIL_FROM_NAME", "EEE Records")} <{_env("MAIL_FROM")}>'
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    ask = Request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                  data=json.dumps({"raw": raw}).encode(), method="POST",
                  headers={"authorization": f"Bearer {_gmail_access_token()}",
                           "content-type": "application/json"})
    try:
        with urlopen(ask, timeout=20) as answer:
            if answer.status >= 300:
                raise RuntimeError(f"Gmail answered {answer.status}")
    except HTTPError as e:
        if e.code == 401:                        # access token went stale: forget it
            _token["value"] = None
        raise


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
    sender = {"gmail-api": _via_gmail_api, "brevo": _via_brevo, "gmail": _via_gmail}[how]
    try:
        sender(to, subject, body + FOOTER)
        return "sent", f"accepted for delivery ({how})"
    except smtplib.SMTPAuthenticationError:
        return "failed", "Google rejected the app password"
    except HTTPError as e:                       # Google/Brevo said no — log why
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"  [mail] could not send to {to}: HTTP {e.code}: {detail}", flush=True)
        if "invalid_grant" in detail:
            print("  [mail] the Gmail refresh token has expired or was revoked — "
                  "make a new one in the OAuth Playground and update GMAIL_REFRESH_TOKEN",
                  flush=True)
        return "failed", f"HTTP {e.code}"
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
