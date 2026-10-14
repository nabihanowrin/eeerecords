"""
Emails about marks, and the watchdog that catches changes made behind
the system's back.

Two kinds of change, two kinds of email:

1. A change made through the website (a teacher enters or corrects a mark).
   The website knows the moment it happens, so the student is emailed then:
   the new value, the old one, who did it and the reason.

2. A change made outside the website (someone edits the database directly).
   The website cannot see that happen. So a watchdog re-checks every
   fingerprint every few minutes. When one no longer matches, it emails the
   student and the office: what the record said before, what it says now.

Only students who have registered are emailed.
"""

import os
import json
import time
import threading
import datetime as dt

import mailer
import ledger
from ledger import connect, compute_hash

STUDENT_DOMAIN = "std.cu.ac.bd"


def _one(sql, args=()):
    con = connect()
    row = con.execute(sql, args).fetchone()
    con.close()
    return row


def _registered_email(roll):
    email = f"{roll}@{STUDENT_DOMAIN}"
    return email if _one("SELECT 1 FROM accounts WHERE email=?", (email,)) else None


def _labels(course_id, item_id):
    course = _one("SELECT code, title FROM courses WHERE course_id=?", (course_id,))
    item = _one("SELECT label, weight FROM items WHERE item_id=?", (item_id,))
    code = f"{course[0]} {course[1]}" if course else course_id
    label = item[0] if item else item_id
    out_of = item[1] if item else None
    return code, label, out_of


def _show(value, absent=False, out_of=None):
    if absent:
        return "absent"
    if value is None:
        return "nothing"
    return f"{value:g}/{out_of:g}" if isinstance(out_of, (int, float)) else f"{value:g}"


def _who(actor):
    actor = actor or ""
    if actor.startswith("teacher:"):
        return actor.split(":", 1)[1].split("@")[0].replace(".demo", "").replace(".", " ").title()
    return actor.split("@")[0].replace(".demo", "").replace(".", " ").title() or "the system"


def previous_value(course_id, roll, item_id):
    """What the chain says this mark is right now: (value, absent) or None."""
    con = connect()
    rows = con.execute("SELECT payload FROM blocks WHERE entry_type IN ('score','correction') "
                       "ORDER BY block_no DESC").fetchall()
    con.close()
    for (text,) in rows:
        p = json.loads(text)
        if (p.get("course_id"), p.get("roll"), p.get("item_id")) == (course_id, roll, item_id):
            return p.get("value"), bool(p.get("absent"))
    return None


def mark_saved(kind, payload, actor, before):
    """Called right after a score or correction block is written."""
    try:
        to = _registered_email(payload["roll"])
        if not to:
            return
        code, label, out_of = _labels(payload["course_id"], payload["item_id"])
        now = _show(payload.get("value"), payload.get("absent"), out_of)
        if kind == "correction":
            was = _show(before[0], before[1], out_of) if before else "nothing"
            subject = f"Your {label} mark in {' '.join(code.split(' ')[:2])} was changed"
            body = (f"Your mark for {label} in {code} was changed.\n\n"
                    f"  Before: {was}\n  Now:    {now}\n"
                    f"  By:     {_who(actor)}\n"
                    f"  Reason: {payload.get('reason') or '(none given)'}\n\n"
                    "The change and its reason are kept permanently in the mark's history. "
                    "If you think it is wrong, open the mark on the website and raise an objection.")
        else:
            subject = f"New mark: {label} in {' '.join(code.split(' ')[:2])}"
            body = (f"A mark was entered for you.\n\n"
                    f"  Course: {code}\n  Item:   {label}\n  Mark:   {now}\n"
                    f"  By:     {_who(actor)}\n\n"
                    "You can see it, and its full history, on the website.")
        mailer.send_later(to, subject, body)
    except Exception as e:                      # an email problem must never block a mark
        print(f"  [notices] {type(e).__name__}: {e}", flush=True)


# ------------------------------------------------------------------
# the watchdog
# ------------------------------------------------------------------
_good = {}          # block_no -> payload text, from the last time the chain was all valid
_alerted = set()    # (block_no, payload text) already reported


def _remember(block_no, payload_text):
    _good[block_no] = payload_text


ledger.ON_ADD.append(_remember)


def _scan():
    """Returns the list of blocks whose fingerprint no longer matches."""
    con = connect()
    rows = con.execute("SELECT * FROM blocks ORDER BY block_no").fetchall()
    con.close()
    broken, expected_prev = [], "0" * 64
    for block_no, kind, text, actor, at, prev_hash, stored in rows:
        payload = json.loads(text)
        if prev_hash != expected_prev or compute_hash(block_no, kind, payload, actor, at, prev_hash) != stored:
            broken.append((block_no, kind, text, actor, at))
        else:
            _good[block_no] = text
        expected_prev = stored
    if not broken:
        _alerted.clear()
    return broken


def check_now():
    """One pass of the watchdog. Returns how many new problems were reported."""
    reported = 0
    for block_no, kind, text, actor, at in _scan():
        if (block_no, text) in _alerted:
            continue
        _alerted.add((block_no, text))
        reported += 1
        now = json.loads(text)
        was = json.loads(_good[block_no]) if block_no in _good else None
        roll = now.get("roll")
        try:
            local = dt.datetime.fromisoformat(at) + dt.timedelta(hours=6)
            written = local.strftime("%d %b %Y, %I:%M %p") + " Bangladesh time"
        except ValueError:
            written = at[:16]
        what = f"Block {block_no} ({kind}, written {written})"
        lines = [f"{what} was changed outside the website. Its fingerprint no longer matches."]
        if kind in ("score", "correction") and now.get("course_id"):
            code, label, out_of = _labels(now["course_id"], now.get("item_id"))
            lines.append(f"Record: {label} in {code}, student {roll}.")
            if was:
                lines.append(f"  It said:  {_show(was.get('value'), was.get('absent'), out_of)}")
            lines.append(f"  Now says: {_show(now.get('value'), now.get('absent'), out_of)}")
        lines.append("\nNo correction was entered and no reason was given. The copies kept on "
                     "other computers still hold the original, so it can be put back.")
        body = "\n".join(lines)
        print(f"  [watchdog] {what} altered", flush=True)
        if roll and _registered_email(roll):
            mailer.send_later(_registered_email(roll),
                              "Alert: one of your records was changed without authorisation", body)
        if mailer.office_address():
            mailer.send_later(mailer.office_address(),
                              f"Tamper alert: {what} altered", body)
    return reported


def start(minutes=None):
    """Re-check the whole chain every few minutes, in the background."""
    minutes = float(minutes or os.environ.get("CHECK_MINUTES") or 2)

    def loop():
        while True:
            try:
                check_now()
            except Exception as e:
                print(f"  [watchdog] {type(e).__name__}: {e}", flush=True)
            time.sleep(minutes * 60)

    threading.Thread(target=loop, daemon=True).start()
    return minutes
