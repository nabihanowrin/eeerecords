"""
Who you are.

contract.py holds the rules about records. This file holds the rules
about identity: registering, signing in, staying signed in, and being
locked out after too many wrong guesses.

Nothing here ever stores a password or a code as plain text.
"""

import hashlib
import hmac
import secrets
import unicodedata
import os
import datetime as dt

from ledger import connect
from contract import Refused

DOMAIN = "std.cu.ac.bd"
STAFF_DOMAIN = "cu.ac.bd"
# For testing email delivery: these three inboxes may create a staff account
# with the role shown, even though they are not @cu.ac.bd. Students still need
# @std.cu.ac.bd. Remove an address here to close it again.
TEST_STAFF = {
    "teacher.demo.eee@gmail.com": "teacher",
    "office.demo.eee@gmail.com": "office",
    "nebanowyn92@gmail.com": "examiner",
}
MAX_TRIES = 5
LOCK_MINUTES = 15
CODE_MINUTES = 10
REMEMBER_DAYS = 30
SHORT_HOURS = 12

# OPEN registration: any @std.cu.ac.bd student can sign up and is placed in
# their batch's semester. Switch to False to go back to "only students the
# office has already added, checked against the office's record".
OPEN_REGISTRATION = True

# While email is not set up on a server, show the code on the page instead of
# hiding it in the server's log. Turn off (SHOW_CODE=0) once email works.
#   SHOW_CODE=1       show it only when email could not be sent (default)
#   SHOW_CODE=always  show it even when it was emailed (handy for a live demo)
#   SHOW_CODE=0       never show it
SHOW_CODE = os.environ.get("SHOW_CODE", "1").strip().lower()
SHOW_CODE_WHEN_EMAIL_OFF = SHOW_CODE in ("1", "always")


# ------------------------------------------------------------------
# tables
# ------------------------------------------------------------------
def init_auth():
    con = connect()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS accounts (
        email TEXT PRIMARY KEY, roll TEXT, role TEXT,
        salt TEXT, pw_hash TEXT, created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pending (
        email TEXT PRIMARY KEY, code_hash TEXT, expires TEXT, tries INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, email TEXT, role TEXT, expires TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pending_profile (
        email TEXT PRIMARY KEY, name TEXT, batch TEXT, father TEXT, mother TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS failures (
        key TEXT PRIMARY KEY, count INTEGER, locked_until TEXT)""")
    con.commit()
    con.close()


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _one(sql, args=()):
    con = connect()
    cur = con.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    con.close()
    return row


def _run(sql, args=()):
    con = connect()
    con.execute(sql, args)
    con.commit()
    con.close()


# ------------------------------------------------------------------
# small helpers
# ------------------------------------------------------------------
def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def hash_password(password, salt):
    """PBKDF2 runs SHA-256 200,000 times, so guessing is slow on purpose."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def same_name(typed, on_file):
    """Capitals, extra spaces and dots don't matter. Works for Bangla too."""
    def clean(s):
        s = unicodedata.normalize("NFC", s or "").casefold().replace(".", " ")
        return " ".join(s.split())
    return bool(on_file) and clean(typed) == clean(on_file)


def roll_from_email(email):
    email = (email or "").strip().lower()
    if "@" not in email:
        raise Refused("That doesn't look like an email address.")
    local, domain = email.rsplit("@", 1)
    if domain != DOMAIN:
        raise Refused(f"Use your university email, the one ending in @{DOMAIN}.")
    if not local.isdigit():
        raise Refused("The part before the @ should be your roll number.")
    return email, local


# ------------------------------------------------------------------
# lockout: five wrong tries, then a wait
# ------------------------------------------------------------------
def check_lock(key):
    row = _one("SELECT count, locked_until FROM failures WHERE key=?", (key,))
    if row and row[1] and dt.datetime.fromisoformat(row[1]) > _now():
        mins = int((dt.datetime.fromisoformat(row[1]) - _now()).total_seconds() // 60) + 1
        raise Refused(f"Too many wrong tries. Try again in {mins} minute{'s' if mins != 1 else ''}.")


def record_failure(key):
    row = _one("SELECT count FROM failures WHERE key=?", (key,))
    count = (row[0] if row else 0) + 1
    until = (_now() + dt.timedelta(minutes=LOCK_MINUTES)).isoformat() if count >= MAX_TRIES else None
    _run("INSERT OR REPLACE INTO failures VALUES (?,?,?)",
         (key, 0 if until else count, until))
    left = MAX_TRIES - count
    return left if not until else 0


def clear_failures(key):
    _run("DELETE FROM failures WHERE key=?", (key,))


# ------------------------------------------------------------------
# registration, step 1: who you are
# ------------------------------------------------------------------
def batches():
    """Batches a student can choose when signing up, newest first."""
    con = connect()
    out = [{"name": n, "semester": c} for n, c in con.execute(
        "SELECT name, current_semester FROM academic_sessions ORDER BY name DESC")]
    con.close()
    return out


def start_registration(email, father, mother, name=None, batch=None):
    """Returns (status, code_to_show). code_to_show is None unless email is off."""
    email, roll = roll_from_email(email)
    key = "register:" + email
    check_lock(key)

    if _one("SELECT 1 FROM accounts WHERE email=?", (email,)):
        raise Refused("This email already has an account. Sign in instead.")

    father, mother = (father or "").strip(), (mother or "").strip()
    name, batch = (name or "").strip(), (batch or "").strip()
    record = _one("SELECT father_en, father_bn, mother_en, mother_bn, session FROM profile WHERE roll=?",
                  (roll,))
    on_file = bool(record and (record[0] or record[1]) and (record[2] or record[3]))

    if on_file:
        # the office already holds the parents' names: check them, as before
        fa_ok = same_name(father, record[0]) or same_name(father, record[1])
        mo_ok = same_name(mother, record[2]) or same_name(mother, record[3])
        if not (fa_ok and mo_ok):
            left = record_failure(key)
            raise Refused("Those names don't match the office's record."
                          + (f" {left} tr{'ies' if left != 1 else 'y'} left." if left else
                             f" Locked for {LOCK_MINUTES} minutes."))
    elif OPEN_REGISTRATION:
        # nothing on file yet: the student tells us, and it is saved to their record
        if not name:
            raise Refused("Please type your full name.")
        if not father or not mother:
            raise Refused("Please type both your father's and your mother's name.")
        if not record:
            if not batch:
                raise Refused("Please choose your batch.")
            if not _one("SELECT 1 FROM academic_sessions WHERE name=?", (batch,)):
                raise Refused("Please choose your batch from the list.")
        _run("INSERT OR REPLACE INTO pending_profile VALUES (?,?,?,?,?)",
             (email, name, batch or record[4], father, mother))
    else:
        raise Refused("That roll number is not on the enrolment list.")

    clear_failures(key)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (_now() + dt.timedelta(minutes=CODE_MINUTES)).isoformat()
    _run("INSERT OR REPLACE INTO pending VALUES (?,?,?,0)", (email, sha(code), expires))

    import mailer
    status, _ = mailer.send(email, "Your EEE Records registration code",
                            f"Your code is {code}\n\nIt works for {CODE_MINUTES} minutes. "
                            "If you didn't ask for this, you can ignore this email.")
    if status != "sent":
        # email isn't available for this address — show it to whoever runs the server
        print(f"\n  >>> Registration code for {email}: {code}  "
              f"(email {status}; valid {CODE_MINUTES} minutes)\n", flush=True)
        if SHOW_CODE_WHEN_EMAIL_OFF:
            return status, code
    elif SHOW_CODE == "always":
        return status, code
    return status, None


# ------------------------------------------------------------------
# registration, step 2: the code proves the inbox, then set a password
# ------------------------------------------------------------------
def finish_registration(email, code, password):
    email, roll = roll_from_email(email)
    row = _one("SELECT code_hash, expires, tries FROM pending WHERE email=?", (email,))
    if not row:
        raise Refused("Start again — no code was sent to this email.")
    if dt.datetime.fromisoformat(row[1]) < _now():
        _run("DELETE FROM pending WHERE email=?", (email,))
        raise Refused("That code has expired. Start again for a new one.")
    if not hmac.compare_digest(sha((code or "").strip()), row[0]):
        tries = row[2] + 1
        if tries >= MAX_TRIES:
            _run("DELETE FROM pending WHERE email=?", (email,))
            raise Refused("Too many wrong codes. Start again for a new one.")
        _run("UPDATE pending SET tries=? WHERE email=?", (tries, email))
        raise Refused(f"Wrong code. {MAX_TRIES - tries} tr{'ies' if MAX_TRIES - tries != 1 else 'y'} left.")
    if len(password or "") < 8:
        raise Refused("Choose a password of at least 8 characters.")

    given = _one("SELECT name, batch, father, mother FROM pending_profile WHERE email=?", (email,))
    if given:
        import contract
        contract.self_register(roll, *given)

    salt = secrets.token_hex(16)
    _run("INSERT INTO accounts VALUES (?,?,?,?,?,?)",
         (email, roll, "student", salt, hash_password(password, salt), _now().isoformat()))
    _run("DELETE FROM pending WHERE email=?", (email,))
    _run("DELETE FROM pending_profile WHERE email=?", (email,))

    # on the demo server, a new student gets a sample record to look at
    import demo_results
    batch = _one("SELECT session FROM profile WHERE roll=?", (roll,))
    if batch:
        demo_results.give(roll, batch[0])
    return email


def staff_register_start(email):
    """A test staff inbox asks for a sign-up code. Returns (status, code_to_show)."""
    email = (email or "").strip().lower()
    if email not in TEST_STAFF:
        raise Refused("Staff accounts are set up by the office. This email can't sign up here.")
    key = "register:" + email
    check_lock(key)
    if _one("SELECT 1 FROM accounts WHERE email=?", (email,)):
        raise Refused("This email already has an account. Sign in instead.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (_now() + dt.timedelta(minutes=CODE_MINUTES)).isoformat()
    _run("INSERT OR REPLACE INTO pending VALUES (?,?,?,0)", (email, sha(code), expires))
    import mailer
    status, _ = mailer.send(email, "Your EEE Records staff sign-up code",
                            f"Your code is {code}\n\nIt works for {CODE_MINUTES} minutes. "
                            f"It creates the {TEST_STAFF[email]} account for this email.")
    if status != "sent":
        print(f"\n  >>> Staff sign-up code for {email}: {code}  (email {status})\n", flush=True)
        if SHOW_CODE_WHEN_EMAIL_OFF:
            return status, code
    elif SHOW_CODE == "always":
        return status, code
    return status, None


def staff_register_finish(email, code, password):
    email = (email or "").strip().lower()
    if email not in TEST_STAFF:
        raise Refused("This email can't sign up here.")
    row = _one("SELECT code_hash, expires, tries FROM pending WHERE email=?", (email,))
    if not row:
        raise Refused("Start again — no code was sent to this email.")
    if dt.datetime.fromisoformat(row[1]) < _now():
        _run("DELETE FROM pending WHERE email=?", (email,))
        raise Refused("That code has expired. Start again for a new one.")
    if not hmac.compare_digest(sha((code or "").strip()), row[0]):
        tries = row[2] + 1
        if tries >= MAX_TRIES:
            _run("DELETE FROM pending WHERE email=?", (email,))
            raise Refused("Too many wrong codes. Start again for a new one.")
        _run("UPDATE pending SET tries=? WHERE email=?", (tries, email))
        raise Refused(f"Wrong code. {MAX_TRIES - tries} tr{'ies' if MAX_TRIES - tries != 1 else 'y'} left.")
    if len(password or "") < 8:
        raise Refused("Choose a password of at least 8 characters.")
    create_staff_account(email, TEST_STAFF[email], password)
    _run("DELETE FROM pending WHERE email=?", (email,))
    return email, TEST_STAFF[email]


def create_staff_account(email, role, password):
    """Staff sign in with their @cu.ac.bd address (or a TEST_STAFF inbox)."""
    email = email.strip().lower()
    local, domain = email.rsplit("@", 1)
    if domain != STAFF_DOMAIN and email not in TEST_STAFF:
        raise Refused(f"Staff accounts use @{STAFF_DOMAIN}.")
    salt = secrets.token_hex(16)
    _run("INSERT OR REPLACE INTO accounts VALUES (?,?,?,?,?,?)",
         (email, local, role, salt, hash_password(password, salt), _now().isoformat()))


def create_account(email, role, password):
    """Used by the seed to make demo accounts."""
    email, roll = roll_from_email(email)
    salt = secrets.token_hex(16)
    _run("INSERT OR REPLACE INTO accounts VALUES (?,?,?,?,?,?)",
         (email, roll, role, salt, hash_password(password, salt), _now().isoformat()))


# ------------------------------------------------------------------
# signing in and staying signed in
# ------------------------------------------------------------------
def sign_in(email, password, remember):
    email = (email or "").strip().lower()
    key = "signin:" + email
    check_lock(key)

    row = _one("SELECT salt, pw_hash, role FROM accounts WHERE email=?", (email,))
    if not row or not hmac.compare_digest(hash_password(password or "", row[0]), row[1]):
        left = record_failure(key)
        raise Refused("Wrong email or password."
                      + (f" {left} tr{'ies' if left != 1 else 'y'} left." if left else
                         f" Locked for {LOCK_MINUTES} minutes."))

    clear_failures(key)
    token = secrets.token_urlsafe(32)          # the ticket the browser keeps
    life = dt.timedelta(days=REMEMBER_DAYS) if remember else dt.timedelta(hours=SHORT_HOURS)
    _run("INSERT INTO sessions VALUES (?,?,?,?)",
         (sha(token), email, row[2], (_now() + life).isoformat()))
    return token, row[2]


def who(token):
    """Returns the signed-in person for a ticket, or None."""
    if not token:
        return None
    row = _one("SELECT s.email, s.role, s.expires, a.roll FROM sessions s "
               "JOIN accounts a ON a.email = s.email WHERE s.token_hash=?", (sha(token),))
    if not row:
        return None
    if dt.datetime.fromisoformat(row[2]) < _now():
        _run("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
        return None
    return {"email": row[0], "role": row[1], "roll": row[3]}


def sign_out(token):
    if token:
        _run("DELETE FROM sessions WHERE token_hash=?", (sha(token),))


# ------------------------------------------------------------------
# forgotten password: a code sent to the inbox proves it's you
# ------------------------------------------------------------------
def reset_start(email):
    """
    Emails a 6-digit reset code. Returns "sent" or the reason it couldn't.

    The code is NEVER shown on the page, unlike the sign-up code: anyone
    could type someone else's email here, so showing the code would let
    them take over that account.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        raise Refused("That doesn't look like an email address.")
    key = "reset:" + email
    check_lock(key)
    record_failure(key)            # counts requests: the 5th locks for a while

    if not _one("SELECT 1 FROM accounts WHERE email=?", (email,)):
        raise Refused("There is no account with this email. Check it, or register instead.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (_now() + dt.timedelta(minutes=CODE_MINUTES)).isoformat()
    _run("INSERT OR REPLACE INTO pending VALUES (?,?,?,0)", (key, sha(code), expires))

    import mailer
    status, _ = mailer.send(email, "Your EEE Records password reset code",
                            f"Your code is {code}\n\nIt works for {CODE_MINUTES} minutes. "
                            "If you didn't ask to reset your password, ignore this email — "
                            "your password stays the same.")
    if status != "sent":
        _run("DELETE FROM pending WHERE email=?", (key,))
        print(f"\n  >>> Password reset for {email} could not be emailed ({status}).\n", flush=True)
        raise Refused("We couldn't email a code to this address right now. "
                      "Ask the academic office to help you reset your password.")
    return status


def reset_finish(email, code, password):
    """Checks the code, sets the new password, and signs out every old session."""
    email = (email or "").strip().lower()
    key = "reset:" + email
    row = _one("SELECT code_hash, expires, tries FROM pending WHERE email=?", (key,))
    if not row:
        raise Refused("Start again — no code was sent to this email.")
    if dt.datetime.fromisoformat(row[1]) < _now():
        _run("DELETE FROM pending WHERE email=?", (key,))
        raise Refused("That code has expired. Start again for a new one.")
    if not hmac.compare_digest(sha((code or "").strip()), row[0]):
        tries = row[2] + 1
        if tries >= MAX_TRIES:
            _run("DELETE FROM pending WHERE email=?", (key,))
            raise Refused("Too many wrong codes. Start again for a new one.")
        _run("UPDATE pending SET tries=? WHERE email=?", (tries, key))
        raise Refused(f"Wrong code. {MAX_TRIES - tries} tr{'ies' if MAX_TRIES - tries != 1 else 'y'} left.")
    if len(password or "") < 8:
        raise Refused("Choose a password of at least 8 characters.")

    salt = secrets.token_hex(16)
    _run("UPDATE accounts SET salt=?, pw_hash=? WHERE email=?",
         (salt, hash_password(password, salt), email))
    _run("DELETE FROM pending WHERE email=?", (key,))
    _run("DELETE FROM sessions WHERE email=?", (email,))   # old sign-ins stop working
    clear_failures(key)
    clear_failures("signin:" + email)                    # a locked-out user can get back in

    import mailer
    mailer.send_later(email, "Your EEE Records password was changed",
                      "The password for your EEE Records account was just changed.\n\n"
                      "If this wasn't you, tell the academic office straight away.")
    return email
