"""
The facilities complaint box.

Only for faulty infrastructure: a broken fan, a projector that doesn't work,
a leaking roof. Not for complaints about people.

- The student writes what is wrong, why it is a problem, and what should be
  fixed, and may add a photo.
- No name is shown to the office or the chairman. The roll number is kept
  only so that a complaint flagged as unnecessary can be tied to the account
  that sent it, and that student sees the warning.
- Each complaint and each flag is recorded on the chain (only a fingerprint
  of the text, never the text or the name), so complaints cannot be quietly
  deleted or edited.
- On submit, the chairman (CHAIRMAN_EMAIL) and the office (OFFICE_EMAIL)
  are emailed.
"""

import os
import hashlib
import datetime as dt

import mailer
from ledger import connect, add_entry
import db
from contract import Refused, IMAGE_TYPES, MAX_UPLOAD

PER_DAY = 3
FOLDER = os.path.join("uploads", "complaints")


def init():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT, roll TEXT, what TEXT, why TEXT, fix TEXT,
        image TEXT, created_at TEXT, flagged INTEGER DEFAULT 0, flagged_by TEXT, flagged_at TEXT)""")
    con.commit()
    con.close()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def chairman_address():
    return (os.environ.get("CHAIRMAN_EMAIL") or "").strip().lower() or None


def file(roll, what, why, fix):
    what, why, fix = (what or "").strip(), (why or "").strip(), (fix or "").strip()
    if not what or not why or not fix:
        raise Refused("Please fill in all three: what is wrong, why it is a problem, and what should be fixed.")
    if max(len(what), len(why), len(fix)) > 1500:
        raise Refused("Please keep each answer under 1500 characters.")
    con = connect()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    today = con.execute("SELECT COUNT(*) FROM complaints WHERE roll=? AND created_at>?",
                        (roll, since)).fetchone()[0]
    if today >= PER_DAY:
        con.close()
        raise Refused(f"You can send up to {PER_DAY} complaints a day.")
    cur = con.execute("INSERT INTO complaints (roll, what, why, fix, created_at) VALUES (?,?,?,?,?)",
                      (roll, what, why, fix, _now()))
    cid = cur.lastrowid
    con.commit()
    con.close()

    digest = hashlib.sha256(f"{what}\n{why}\n{fix}".encode()).hexdigest()
    add_entry("complaint_filed", {"complaint_id": cid, "sha256": digest}, "student:anonymous")

    body = (f"A facilities complaint was sent through EEE Records (#{cid}).\n\n"
            f"What is wrong:\n{what}\n\nWhy it is a problem:\n{why}\n\nWhat should be fixed:\n{fix}\n\n"
            "The sender's name is not shown. Any photo is on the office's Complaints page.")
    subject = f"Facilities complaint #{cid}: {what[:60]}"
    for to in {chairman_address(), mailer.office_address()} - {None}:
        mailer.send_later(to, subject, body)
    return cid


def add_photo(roll, cid, filename, data):
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in IMAGE_TYPES:
        raise Refused("The photo must be an image (" + ", ".join(sorted(e[1:].upper() for e in IMAGE_TYPES)) + ").")
    if not data or len(data) > MAX_UPLOAD:
        raise Refused("The photo must be under 5 MB.")
    con = connect()
    row = con.execute("SELECT 1 FROM complaints WHERE id=? AND roll=?", (cid, roll)).fetchone()
    if not row:
        con.close()
        raise Refused("No such complaint.")
    path = os.path.join(FOLDER, f"{int(cid)}{ext}")
    db.save_file(path, data)                 # on disk, and in Postgres when online
    con.execute("UPDATE complaints SET image=? WHERE id=?", (path, cid))
    con.commit()
    con.close()


def mine(roll):
    con = connect()
    rows = con.execute("SELECT id, what, created_at, flagged FROM complaints WHERE roll=? "
                       "ORDER BY id DESC", (roll,)).fetchall()
    con.close()
    return [{"id": i, "what": w, "at": a, "flagged": bool(f)} for i, w, a, f in rows]


def for_office():
    """Every complaint, without the sender."""
    con = connect()
    rows = con.execute("SELECT id, what, why, fix, image, created_at, flagged, flagged_by, flagged_at "
                       "FROM complaints ORDER BY id DESC").fetchall()
    con.close()
    return [{"id": i, "what": w, "why": y, "fix": x, "photo": bool(img), "at": a,
             "flagged": bool(f), "flagged_by": fb, "flagged_at": fa}
            for i, w, y, x, img, a, f, fb, fa in rows]


def photo_path(cid):
    con = connect()
    row = con.execute("SELECT image FROM complaints WHERE id=?", (cid,)).fetchone()
    con.close()
    return row[0] if row and row[0] and os.path.isfile(row[0]) else None


def flag(staff_email, cid):
    con = connect()
    row = con.execute("SELECT flagged FROM complaints WHERE id=?", (cid,)).fetchone()
    if not row:
        con.close()
        raise Refused("No such complaint.")
    if row[0]:
        con.close()
        raise Refused("That complaint is already flagged.")
    con.execute("UPDATE complaints SET flagged=1, flagged_by=?, flagged_at=? WHERE id=?",
                (staff_email, _now(), cid))
    con.commit()
    con.close()
    return add_entry("complaint_flagged", {"complaint_id": int(cid)}, f"office:{staff_email}")[0]


def warnings(roll):
    con = connect()
    n = con.execute("SELECT COUNT(*) FROM complaints WHERE roll=? AND flagged=1", (roll,)).fetchone()[0]
    con.close()
    return n
