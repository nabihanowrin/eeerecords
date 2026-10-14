"""
Course resources: files shared with everyone taking a course.

Four shelves per course:
    notes   Notes
    books   Books
    finals  Previous year final questions
    cts     Class test questions

Who can add a file: a student enrolled in the course, or a teacher the office
has given the course. Everyone in the course (and its teachers and the office)
can open it. Only the person who added a file, or the office, can remove it.

Each file's fingerprint (sha256) goes on the chain when it is added, so a
question paper cannot be swapped for a different one later without it showing.
Removing a file is also recorded on the chain.
"""

import os
import hashlib
import datetime as dt

from ledger import connect, add_entry
from contract import Refused

CATEGORIES = {
    "notes":  "Notes",
    "books":  "Books",
    "finals": "Previous year final questions",
    "cts":    "Class test questions",
}
TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
MAX_FILE = 15 * 1024 * 1024          # 15 MB a file
MAX_PER_PERSON = 150 * 1024 * 1024   # 150 MB in total per person
FOLDER = os.path.join("uploads", "resources")

# a few standard textbooks, shown on the Books shelf as suggestions (no file)
SUGGESTED = {
    "EEE511-2026": [("Digital Design", "M. Morris Mano")],
    "EEE513-2026": [("Communication Systems", "Simon Haykin")],
    "EEE515-2026": [("Engineering Electromagnetics", "W. H. Hayt, J. A. Buck")],
    "CSE517-2026": [("Computer Networks", "A. S. Tanenbaum")],
    "EEE519-2026": [("Principles of Power System", "V. K. Mehta")],
}


def init():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS course_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id TEXT, category TEXT, title TEXT,
        filename TEXT, path TEXT, size INTEGER, sha256 TEXT, uploader TEXT, uploader_name TEXT,
        uploaded_at TEXT, block_no INTEGER)""")
    con.commit()
    con.close()


def _rows(sql, args=()):
    con = connect()
    out = con.execute(sql, args).fetchall()
    con.close()
    return out


def actor_of(user):
    """The id written on the chain for this person."""
    if user["role"] == "student":
        return "student:" + user["roll"]
    if user["role"] == "teacher":
        return "teacher:" + user["roll"]
    return f"{user['role']}:{user['email']}"


def can_see(user, course_id):
    if user["role"] in ("office", "examiner"):
        return True
    if user["role"] == "student":
        return bool(_rows("SELECT 1 FROM enrollments WHERE roll=? AND course_id=?", (user["roll"], course_id)))
    if user["role"] == "teacher":
        return bool(_rows("SELECT 1 FROM teaching WHERE teacher_id=? AND course_id=?",
                          ("teacher:" + user["roll"], course_id)))
    return False


def can_add(user, course_id):
    return user["role"] in ("student", "teacher") and can_see(user, course_id)


def _bd(at):
    """Bangladesh time (UTC+6), for showing."""
    try:
        return (dt.datetime.fromisoformat(at) + dt.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return at or ""


def listing(user, course_id):
    me = actor_of(user)
    shelves = {key: [] for key in CATEGORIES}
    for i, cat, title, fname, size, who, name, at in _rows(
            "SELECT id, category, title, filename, size, uploader, uploader_name, uploaded_at "
            "FROM course_resources WHERE course_id=? ORDER BY id DESC", (course_id,)):
        shelves.setdefault(cat, []).append({
            "id": i, "title": title, "filename": fname, "size": size,
            "by": name, "teacher": who.startswith("teacher:"), "at": _bd(at),
            "type": os.path.splitext(fname)[1].lstrip(".").upper(),
            "mine": who == me, "can_remove": who == me or user["role"] == "office"})
    return {"categories": [{"key": k, "label": v, "files": shelves[k]} for k, v in CATEGORIES.items()],
            "suggested": [{"title": t, "author": a} for t, a in SUGGESTED.get(course_id, [])],
            "can_add": can_add(user, course_id),
            "types": sorted(e[1:].upper() for e in TYPES), "max_mb": MAX_FILE // (1024 * 1024)}


def add(user, display_name, course_id, category, filename, title, data):
    if not can_add(user, course_id):
        raise Refused("You can only add files to a course you are taking or teaching.")
    if category not in CATEGORIES:
        raise Refused("Please choose what kind of file this is.")
    filename = os.path.basename((filename or "").replace("\\", "/")).strip()[:120]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in TYPES:
        raise Refused("Allowed files: " + ", ".join(sorted(e[1:].upper() for e in TYPES)) + ".")
    if not data:
        raise Refused("That file is empty.")
    if len(data) > MAX_FILE:
        raise Refused(f"Files must be under {MAX_FILE // (1024 * 1024)} MB.")
    me = actor_of(user)
    used = _rows("SELECT COALESCE(SUM(size),0) FROM course_resources WHERE uploader=?", (me,))[0][0]
    if used + len(data) > MAX_PER_PERSON:
        raise Refused(f"You have used your {MAX_PER_PERSON // (1024 * 1024)} MB for shared files. "
                      "Remove an old file first.")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise Refused("That file does not look like a real PDF.")
    digest = hashlib.sha256(data).hexdigest()
    if _rows("SELECT 1 FROM course_resources WHERE course_id=? AND sha256=?", (course_id, digest)):
        raise Refused("This exact file is already in this course's resources.")
    title = " ".join((title or "").split())[:120] or os.path.splitext(filename)[0]

    os.makedirs(FOLDER, exist_ok=True)
    path = os.path.join(FOLDER, digest[:24] + ext)
    with open(path, "wb") as f:
        f.write(data)
    block_no = add_entry("resource_added", {"course_id": course_id, "category": category,
                                            "file": filename, "sha256": digest}, me)[0]
    con = connect()
    cur = con.execute("INSERT INTO course_resources (course_id, category, title, filename, path, size, "
                      "sha256, uploader, uploader_name, uploaded_at, block_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (course_id, category, title, filename, path, len(data), digest, me, display_name,
                       dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), block_no))
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return new_id


def open_file(user, rid):
    """(path, filename, content type) if this person may open it, otherwise None."""
    found = _rows("SELECT course_id, path, filename FROM course_resources WHERE id=?", (rid,))
    if not found:
        return None
    course_id, path, filename = found[0]
    if not can_see(user, course_id) or not os.path.isfile(path):
        return None
    return path, filename, TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def remove(user, rid):
    found = _rows("SELECT course_id, path, uploader, sha256 FROM course_resources WHERE id=?", (rid,))
    if not found:
        raise Refused("No such file.")
    course_id, path, who, digest = found[0]
    if who != actor_of(user) and user["role"] != "office":
        raise Refused("Only the person who added this file, or the office, can remove it.")
    add_entry("resource_removed", {"course_id": course_id, "sha256": digest}, actor_of(user))
    con = connect()
    con.execute("DELETE FROM course_resources WHERE id=?", (rid,))
    con.commit()
    con.close()
    if not _rows("SELECT 1 FROM course_resources WHERE path=?", (path,)) and os.path.isfile(path):
        os.remove(path)
