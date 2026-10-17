"""
The contract.

Every rule of the system lives in this one file, and every write to the
chain has to pass through it. Nothing else is allowed to call add_entry
for marks or objections.

This is what a smart contract is: the rules, in one place, enforced.
When the project moves to Hyperledger Fabric, this file becomes the
chaincode almost line for line.
"""

import json
from ledger import connect, add_entry

# Marks are stored raw, exactly as the student got them.
# Each item has its own out-of, set by the teacher: a CT out of 20,
# an assignment out of 5. A mark can never be above its own out-of.


class Refused(Exception):
    """Raised whenever a rule says no. The message is shown to the user."""


# ------------------------------------------------------------------
# small lookups
# ------------------------------------------------------------------
def _one(sql, args):
    con = connect()
    cur = con.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    con.close()
    return row


def _role(actor):
    """A staff member's role, looked up by their email. None if unknown."""
    row = _one("SELECT role FROM accounts WHERE email=?", (actor,))
    return row[0] if row else None


def is_office(actor):
    return _role(actor) == "office"


def teacher_teaches(teacher_id, course_id, session=None):
    """Does this teacher have this class? A class is a course and a session.
    Called without a session it asks only about the course, which is what
    the older rules in this file need."""
    if session is None:
        return _one("SELECT 1 FROM teaching WHERE teacher_id=? AND course_id=?",
                    (teacher_id, course_id)) is not None
    return _one("SELECT 1 FROM teaching WHERE teacher_id=? AND course_id=? AND session=?",
                (teacher_id, course_id, session)) is not None


def init_teaching():
    """The teaching table holds the office's approvals. Older databases have
    it without a session column, so add one rather than start again."""
    con = connect()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS teaching (
        teacher_id TEXT, course_id TEXT, session TEXT,
        PRIMARY KEY (teacher_id, course_id, session))""")
    columns = [row[1] for row in cur.execute("PRAGMA table_info(teaching)")]
    if "session" not in columns:
        cur.execute("ALTER TABLE teaching ADD COLUMN session TEXT")
    con.commit()
    con.close()


def item_exists(course_id, item_id):
    return _one("SELECT 1 FROM items WHERE course_id=? AND item_id=?",
                (course_id, item_id)) is not None


def enrolled(course_id, roll):
    return _one("SELECT 1 FROM enrollments WHERE course_id=? AND roll=?",
                (course_id, roll)) is not None


def mark_was_entered(course_id, roll, item_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT payload FROM blocks WHERE entry_type IN ('score','correction')")
    rows = cur.fetchall()
    con.close()
    for (text,) in rows:
        p = json.loads(text)
        if p.get("course_id") == course_id and p.get("roll") == roll and p.get("item_id") == item_id:
            return True
    return False


# ------------------------------------------------------------------
# rule 1: a mark must be a number inside the allowed range
# ------------------------------------------------------------------
def out_of(course_id, item_id):
    row = _one("SELECT weight FROM items WHERE course_id=? AND item_id=?",
               (course_id, item_id))
    return row[0] if row else None


def check_mark(value, limit):
    if not isinstance(value, (int, float)):
        raise Refused("A mark must be a number.")
    if value < 0 or value > limit:
        raise Refused(f"A mark must be between 0 and {limit:g}, this item's out-of.")


# ------------------------------------------------------------------
# rule 2: only the assigned teacher corrects a mark, and must say why
# ------------------------------------------------------------------
def correct_mark(teacher_id, course_id, roll, item_id, value, reason):
    if not teacher_teaches(teacher_id, course_id):
        raise Refused("You are not assigned to this course.")
    if not item_exists(course_id, item_id):
        raise Refused("That assessment item does not exist in this course.")
    if not enrolled(course_id, roll):
        raise Refused("That student is not enrolled in this course.")
    check_mark(value, out_of(course_id, item_id))
    if not reason or not reason.strip():
        raise Refused("A correction needs a reason the student can read.")

    import notices
    before = notices.previous_value(course_id, roll, item_id)
    payload = {"course_id": course_id, "roll": roll, "item_id": item_id,
               "value": value, "reason": reason.strip()}
    result = add_entry("correction", payload, teacher_id)
    notices.mark_saved("correction", payload, teacher_id, before)
    return result


# ==================================================================
# classes — a teacher asks, the office approves
#
# A class is a course and a session together: EEE 513 for 2023-24.
# Who may enter marks is itself a record, so both the asking and the
# answer are blocks on the chain. The teaching table is only the quick
# lookup built from them.
# ==================================================================
def class_requests(teacher_id=None):
    """Every request with what became of it, replayed from the chain."""
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT block_no, entry_type, payload, actor, created_at FROM blocks
                   WHERE entry_type IN ('class_request','class_decision') ORDER BY block_no""")
    rows = cur.fetchall()
    con.close()

    out = {}
    for block_no, kind, text, actor, at in rows:
        p = json.loads(text)
        if kind == "class_request":
            out[block_no] = {"id": block_no, "teacher_id": p["teacher_id"],
                             "course_id": p["course_id"], "session": p["session"],
                             "status": "waiting", "asked_at": at,
                             "decided_by": None, "decided_at": None, "note": ""}
            continue
        asked = out.get(p.get("request_id"))
        if asked:
            asked.update(status=p["status"], decided_by=actor,
                         decided_at=at, note=p.get("note", ""))

    found = [r for r in out.values() if teacher_id is None or r["teacher_id"] == teacher_id]
    return sorted(found, key=lambda r: r["id"], reverse=True)


def approved_classes(teacher_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT t.course_id, t.session, c.code, c.title, c.semester
                   FROM teaching t JOIN courses c ON c.course_id = t.course_id
                   WHERE t.teacher_id=? ORDER BY c.semester, c.code""", (teacher_id,))
    rows = cur.fetchall()
    con.close()
    return [{"course_id": c, "session": s, "code": code, "title": title, "semester": sem}
            for c, s, code, title, sem in rows]


def request_class(teacher_id, course_id, session):
    """A teacher asks for a class. It waits until the office answers."""
    if not teacher_id.startswith("teacher:"):
        raise Refused("Only a teacher can ask for a class.")
    if not _one("SELECT 1 FROM courses WHERE course_id=?", (course_id,)):
        raise Refused("No such course.")
    if not _one("SELECT 1 FROM academic_sessions WHERE name=?", (session,)):
        raise Refused("No such session.")
    if teacher_teaches(teacher_id, course_id, session):
        raise Refused("You already have this class.")
    for r in class_requests(teacher_id):
        if (r["course_id"], r["session"], r["status"]) == (course_id, session, "waiting"):
            raise Refused(f"Request #{r['id']} for this class is already with the office.")

    block_no, _ = add_entry(
        "class_request",
        {"teacher_id": teacher_id, "course_id": course_id,
         "session": session, "status": "waiting"},
        teacher_id,
    )
    return block_no


def decide_class(office_email, request_id, approve, note=""):
    """The office answers one request. Approving is what lets a teacher
    write marks, so it goes on the chain before the table is touched."""
    if not is_office(office_email):
        raise Refused("Only the office can answer a class request.")
    found = [r for r in class_requests() if r["id"] == request_id]
    if not found:
        raise Refused("No such request.")
    asked = found[0]
    if asked["status"] != "waiting":
        raise Refused(f"Request #{request_id} was already {asked['status']}.")
    note = (note or "").strip()
    if not approve and not note:
        raise Refused("Turning a request down needs a reason the teacher can read.")

    block_no, _ = add_entry(
        "class_decision",
        {"request_id": request_id, "teacher_id": asked["teacher_id"],
         "course_id": asked["course_id"], "session": asked["session"],
         "status": "approved" if approve else "rejected", "note": note},
        f"office:{office_email}",
    )
    if approve:
        con = connect()
        con.execute("INSERT OR REPLACE INTO teaching (teacher_id, course_id, session) VALUES (?,?,?)",
                    (asked["teacher_id"], asked["course_id"], asked["session"]))
        con.commit()
        con.close()
    return block_no


# ==================================================================
# the office's register of people: batches and the students in them
#
# The office is the only one who types a student in. Each change is a
# block, so a name appearing, changing or leaving is part of the record.
# Parents' names are kept in the database but never written to the chain:
# the chain says a record was added, not what is in it.
# ==================================================================
def batches():
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT a.name, a.current_semester, COUNT(p.roll)
                   FROM academic_sessions a LEFT JOIN profile p ON p.session = a.name
                   GROUP BY a.name, a.current_semester ORDER BY a.name DESC""")
    rows_ = cur.fetchall()
    con.close()
    return [{"name": n, "semester": s, "students": c} for n, s, c in rows_]


def students_in(session):
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT s.roll, s.name, p.student_id, p.father_en, p.father_bn,
                          p.mother_en, p.mother_bn,
                          (SELECT COUNT(*) FROM accounts a WHERE a.roll = s.roll)
                   FROM students s JOIN profile p ON p.roll = s.roll
                   WHERE p.session=? ORDER BY s.roll""", (session,))
    rows_ = cur.fetchall()
    con.close()
    return [{"roll": r, "name": n, "student_id": sid, "father_en": fe, "father_bn": fb,
             "mother_en": me, "mother_bn": mb, "registered": bool(acc)}
            for r, n, sid, fe, fb, me, mb, acc in rows_]


def add_batch(office_email, name, current_semester=1):
    if not is_office(office_email):
        raise Refused("Only the office can add a batch.")
    name = (name or "").strip()
    if not name:
        raise Refused("A batch needs a name, like 2026–27.")
    if _one("SELECT 1 FROM academic_sessions WHERE name=?", (name,)):
        raise Refused("There is already a batch with that name.")
    try:
        semester = int(current_semester or 1)
    except (TypeError, ValueError):
        raise Refused("The semester must be a number from 1 to 8.")
    if not 1 <= semester <= 8:
        raise Refused("A batch is somewhere between semester 1 and semester 8.")

    con = connect()
    con.execute("INSERT INTO academic_sessions VALUES (?,?)", (name, semester))
    con.commit()
    con.close()
    block_no, _ = add_entry("batch_added",
                            {"batch": name, "semester": semester},
                            f"office:{office_email}")
    return block_no


def _enroll_upto(cur, roll, semester):
    """A student joins every course of the semesters their batch has reached."""
    cur.execute("SELECT course_id FROM courses WHERE semester<=?", (semester,))
    for (course_id,) in cur.fetchall():
        cur.execute("INSERT OR IGNORE INTO enrollments VALUES (?,?)", (course_id, roll))


def add_student(office_email, session, roll, name, student_id=None,
                father_en=None, father_bn=None, mother_en=None, mother_bn=None):
    if not is_office(office_email):
        raise Refused("Only the office can add a student.")
    found = _one("SELECT current_semester FROM academic_sessions WHERE name=?", (session,))
    if not found:
        raise Refused("No such batch.")
    roll = (roll or "").strip()
    name = (name or "").strip()
    if not roll.isdigit():
        raise Refused("A roll number is digits only — it becomes the student's email.")
    if not name:
        raise Refused("A student needs a name.")
    if _one("SELECT 1 FROM students WHERE roll=?", (roll,)):
        raise Refused(f"{roll} is already on the register.")

    con = connect()
    cur = con.cursor()
    cur.execute("INSERT INTO students VALUES (?,?)", (roll, name))
    cur.execute("INSERT INTO profile VALUES (?,?,?,?,?,?,?,NULL)",
                (roll, (student_id or "").strip() or None, session,
                 (father_en or "").strip() or None, (father_bn or "").strip() or None,
                 (mother_en or "").strip() or None, (mother_bn or "").strip() or None))
    _enroll_upto(cur, roll, found[0])
    con.commit()
    con.close()

    block_no, _ = add_entry(
        "student_added",
        {"roll": roll, "name": name, "batch": session,
         "student_id": (student_id or "").strip() or None,
         "parents_on_file": bool((father_en or father_bn) and (mother_en or mother_bn))},
        f"office:{office_email}",
    )
    return block_no


def self_register(roll, name, batch, father, mother):
    """Open registration: a student who signs up is put on the register
    themselves (or fills in their own placeholder row). Like the office's
    add_student, the chain records that it happened, never the parents' names."""
    found = _one("SELECT current_semester FROM academic_sessions WHERE name=?", (batch,))
    if not found:
        raise Refused("No such batch.")
    con = connect()
    cur = con.cursor()
    exists = cur.execute("SELECT 1 FROM students WHERE roll=?", (roll,)).fetchone()
    if exists:
        cur.execute("UPDATE students SET name=? WHERE roll=?", (name, roll))
        cur.execute("UPDATE profile SET father_en=?, mother_en=? WHERE roll=?", (father, mother, roll))
    else:
        cur.execute("INSERT INTO students VALUES (?,?)", (roll, name))
        cur.execute("INSERT INTO profile VALUES (?,?,?,?,?,?,?,NULL)",
                    (roll, None, batch, father, None, mother, None))
        _enroll_upto(cur, roll, found[0])
    con.commit()
    con.close()
    block_no, _ = add_entry("student_registered",
                            {"roll": roll, "batch": batch, "how": "self-registration"},
                            f"student:{roll}")
    return block_no


def update_student(office_email, roll, fields):
    """Change what the office holds. Names of parents are changed in the
    database; the chain records which fields changed, not their contents."""
    if not is_office(office_email):
        raise Refused("Only the office can change a student's details.")
    if not _one("SELECT 1 FROM students WHERE roll=?", (roll,)):
        raise Refused("No such student.")

    allowed = {"name", "student_id", "session",
               "father_en", "father_bn", "mother_en", "mother_bn"}
    changes = {k: (v or "").strip() or None for k, v in (fields or {}).items() if k in allowed}
    if not changes:
        raise Refused("Nothing to change.")
    if "name" in changes and not changes["name"]:
        raise Refused("A student needs a name.")
    if "session" in changes and not _one("SELECT 1 FROM academic_sessions WHERE name=?",
                                         (changes["session"],)):
        raise Refused("No such batch.")

    con = connect()
    cur = con.cursor()
    before = {}
    if "name" in changes:
        before["name"] = _one("SELECT name FROM students WHERE roll=?", (roll,))[0]
        cur.execute("UPDATE students SET name=? WHERE roll=?", (changes["name"], roll))
    profile_bits = {k: v for k, v in changes.items() if k != "name"}
    if profile_bits:
        row = cur.execute("SELECT student_id, session FROM profile WHERE roll=?", (roll,)).fetchone()
        before["student_id"], before["session"] = row
        sets = ", ".join(f"{k}=?" for k in profile_bits)
        cur.execute(f"UPDATE profile SET {sets} WHERE roll=?", (*profile_bits.values(), roll))
        if "session" in profile_bits:
            semester = _one("SELECT current_semester FROM academic_sessions WHERE name=?",
                            (profile_bits["session"],))[0]
            _enroll_upto(cur, roll, semester)
    con.commit()
    con.close()

    block_no, _ = add_entry(
        "student_changed",
        {"roll": roll, "changed": sorted(changes),
         "name": changes.get("name", before.get("name")),
         "was_name": before.get("name"),
         "batch": changes.get("session", before.get("session"))},
        f"office:{office_email}",
    )
    return block_no


def remove_student(office_email, roll, reason):
    """Takes a student off the register. Anything already on the chain
    stays there — this records that they were removed, and why."""
    if not is_office(office_email):
        raise Refused("Only the office can remove a student.")
    found = _one("SELECT name FROM students WHERE roll=?", (roll,))
    if not found:
        raise Refused("No such student.")
    if not reason or not reason.strip():
        raise Refused("Removing a student needs a reason.")

    con = connect()
    cur = con.cursor()
    session = cur.execute("SELECT session FROM profile WHERE roll=?", (roll,)).fetchone()
    cur.execute("DELETE FROM enrollments WHERE roll=?", (roll,))
    cur.execute("DELETE FROM profile WHERE roll=?", (roll,))
    cur.execute("DELETE FROM students WHERE roll=?", (roll,))
    cur.execute("DELETE FROM sessions WHERE email IN (SELECT email FROM accounts WHERE roll=?)", (roll,))
    cur.execute("DELETE FROM accounts WHERE roll=?", (roll,))
    con.commit()
    con.close()

    block_no, _ = add_entry(
        "student_removed",
        {"roll": roll, "name": found[0], "batch": session[0] if session else None,
         "reason": reason.strip()},
        f"office:{office_email}",
    )
    return block_no


# ==================================================================
# attendance — one block per class, corrections one student at a time
#
# A register is what a teacher signs on paper: the whole class in one
# entry. Changing a tick afterwards is a separate block with a reason,
# so the student can see what it was before and who changed it.
# ==================================================================
def class_list(course_id, session):
    """Who is in this class: enrolled in the course, and in that session."""
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT s.roll, s.name FROM students s
                   JOIN enrollments e ON e.roll = s.roll
                   JOIN profile p ON p.roll = s.roll
                   WHERE e.course_id=? AND p.session=? ORDER BY s.roll""", (course_id, session))
    rows = cur.fetchall()
    con.close()
    return [{"roll": r, "name": n} for r, n in rows]


def registers(course_id):
    """What the register says now, for every class of this course:
       {session_id: {roll: {present, by, at, reason, block_no}}}

    Three kinds of block are read: the plain 'attendance' rows written by
    the seed, a whole-class 'attendance_register', and a one-student
    'attendance_correction'. A later block wins, without erasing the older."""
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT block_no, entry_type, payload, actor, created_at FROM blocks
                   WHERE entry_type IN ('attendance','attendance_register','attendance_correction')
                   ORDER BY block_no""")
    rows = cur.fetchall()
    con.close()

    out = {}
    for block_no, kind, text, actor, at in rows:
        p = json.loads(text)
        if p.get("course_id") != course_id:
            continue
        held = out.setdefault(p.get("session_id"), {})
        mark = lambda present, reason=None: {"present": present, "by": actor, "at": at,
                                             "reason": reason, "block_no": block_no}
        if kind == "attendance_register":
            for roll in p.get("present", []):
                held[roll] = mark(True)
            for roll in p.get("absent", []):
                held[roll] = mark(False)
        else:
            held[p["roll"]] = mark(bool(p.get("present")), p.get("reason"))
    return out


def _class_session(course_id, session_id):
    return _one("SELECT held_on, topic FROM class_sessions WHERE session_id=? AND course_id=?",
                (session_id, course_id))


def save_register(teacher_id, course_id, session, session_id, marks):
    """One class, one block. marks is {roll: True for present, False for absent}."""
    if not teacher_teaches(teacher_id, course_id, session):
        raise Refused("The office has not given you this class.")
    found = _class_session(course_id, session_id)
    if not found:
        raise Refused("That class is not in this course's timetable.")
    held_on = found[0]
    day = _dt.date.fromisoformat(held_on)
    if day > _dt.date.today():
        raise Refused("That class has not happened yet.")
    if session_id in cancelled_classes(course_id):
        raise Refused("This class was cancelled.")
    if session_id in registers(course_id):
        raise Refused("This class already has a register. "
                      "Change one student at a time, with a reason.")

    on_list = {s["roll"] for s in class_list(course_id, session)}
    present, absent = [], []
    for roll, here in (marks or {}).items():
        if roll not in on_list:
            raise Refused(f"{roll} is not on this class list.")
        if not attends(roll, course_id, day):
            raise Refused(f"Group {lab_group(roll)} does not have this lab on {held_on}.")
        (present if here else absent).append(roll)
    if not present and not absent:
        raise Refused("There is nothing to save.")

    block_no, _ = add_entry(
        "attendance_register",
        {"course_id": course_id, "session": session, "session_id": session_id,
         "held_on": held_on, "present": sorted(present), "absent": sorted(absent)},
        teacher_id,
    )
    return block_no


def correct_attendance(teacher_id, course_id, session, session_id, roll, present, reason):
    """Changing a tick that is already on the chain. Always with a reason."""
    if not teacher_teaches(teacher_id, course_id, session):
        raise Refused("The office has not given you this class.")
    found = _class_session(course_id, session_id)
    if not found:
        raise Refused("That class is not in this course's timetable.")
    if roll not in {s["roll"] for s in class_list(course_id, session)}:
        raise Refused(f"{roll} is not on this class list.")
    if not reason or not reason.strip():
        raise Refused("Changing a register needs a reason the student can read.")

    was = registers(course_id).get(session_id, {}).get(roll)
    if was and was["present"] == bool(present):
        raise Refused("That is already what the register says.")

    block_no, _ = add_entry(
        "attendance_correction",
        {"course_id": course_id, "session": session, "session_id": session_id,
         "held_on": found[0], "roll": roll, "present": bool(present),
         "was": None if was is None else was["present"], "reason": reason.strip()},
        teacher_id,
    )
    return block_no


# ------------------------------------------------------------------
# cancelling a class that hasn't happened yet — the students are emailed
# ------------------------------------------------------------------
def cancelled_classes(course_id):
    """{session_id: who cancelled it and when} for one course."""
    con = connect()
    found = con.execute("SELECT payload, actor, created_at FROM blocks "
                        "WHERE entry_type='class_cancelled' ORDER BY block_no").fetchall()
    con.close()
    out = {}
    for text, actor, at in found:
        p = json.loads(text)
        if p.get("course_id") == course_id:
            out[p["session_id"]] = {"by": actor, "at": at}
    return out


def cancel_class(teacher_id, course_id, session, session_id):
    if not teacher_teaches(teacher_id, course_id, session):
        raise Refused("The office has not given you this class.")
    found = _class_session(course_id, session_id)
    if not found:
        raise Refused("That class is not in this course's timetable.")
    held_on, slot = found
    day = _dt.date.fromisoformat(held_on)
    if day < _dt.date.today():
        raise Refused("That class has already happened.")
    if session_id in cancelled_classes(course_id):
        raise Refused("This class is already cancelled.")
    if session_id in registers(course_id):
        raise Refused("Attendance was already taken for this class.")

    block_no, _ = add_entry(
        "class_cancelled",
        {"course_id": course_id, "session": session, "session_id": session_id, "held_on": held_on},
        teacher_id,
    )

    import mailer
    code, title = _one("SELECT code, title FROM courses WHERE course_id=?", (course_id,))
    when = f"{day:%A}, {day.day} {day:%B}"
    time = (slot or "").split("·")[0].strip()
    for s in class_list(course_id, session):
        if not attends(s["roll"], course_id, day):
            continue
        email = f"{s['roll']}@{STUDENT_DOMAIN}"
        if not _one("SELECT 1 FROM accounts WHERE email=?", (email,)):
            continue
        mailer.send_later(email, f"Class cancelled: {code} on {day.day} {day:%b}",
                          f"{code} {title} on {when}" + (f" ({time})" if time else "")
                          + " is cancelled.\n\nIt will not count towards your attendance.")
    return block_no


# ==================================================================
# marks a teacher enters: class tests and lab items, never the final
# ==================================================================
def item_category(item_id):
    row = _one("SELECT category FROM item_meta WHERE item_id=?", (item_id,))
    return row[0] if row else None


def set_out_of(teacher_id, course_id, session, item_id, out_of):
    """The teacher sets what a test is out of — until its first mark is in."""
    if not teacher_teaches(teacher_id, course_id, session):
        raise Refused("The office has not given you this class.")
    if not item_exists(course_id, item_id):
        raise Refused("That item does not belong to this course.")
    if item_category(item_id) == "final":
        raise Refused("Final exam marks belong to the examiners, not to teachers.")
    try:
        out_of = float(out_of)
    except (TypeError, ValueError):
        raise Refused("An out-of must be a number.")
    if not 1 <= out_of <= 100:
        raise Refused("An out-of must be between 1 and 100.")

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT payload FROM blocks WHERE entry_type IN ('score','correction')")
    rows = cur.fetchall()
    for (text,) in rows:
        if json.loads(text).get("item_id") == item_id:
            con.close()
            raise Refused("This test already has marks, so its out-of is fixed now.")
    was = _one("SELECT weight FROM items WHERE course_id=? AND item_id=?", (course_id, item_id))
    was = was[0] if was else None
    cur.execute("UPDATE items SET weight=? WHERE item_id=? AND course_id=?",
                (out_of, item_id, course_id))
    con.commit()
    con.close()

    block_no, _ = add_entry(
        "item_setup",
        {"course_id": course_id, "session": session, "item_id": item_id,
         "out_of": out_of, "was": was},
        teacher_id,
    )
    return block_no


def enter_score(teacher_id, course_id, session, roll, item_id, value, absent=False, reason=""):
    """One mark. The first one is a score; any later one is a correction
    and needs a reason, which is the rule that makes a change visible."""
    if not teacher_teaches(teacher_id, course_id, session):
        raise Refused("The office has not given you this class.")
    if not item_exists(course_id, item_id):
        raise Refused("That item does not belong to this course.")
    if item_category(item_id) == "final":
        raise Refused("Final exam marks belong to the examiners, not to teachers.")
    if roll not in {s["roll"] for s in class_list(course_id, session)}:
        raise Refused(f"{roll} is not on this class list.")

    if absent:
        value = 0
    else:
        check_mark(value, out_of(course_id, item_id))

    payload = {"course_id": course_id, "roll": roll, "item_id": item_id,
               "value": value, "absent": bool(absent)}

    import notices
    if mark_was_entered(course_id, roll, item_id):
        if not reason or not reason.strip():
            raise Refused("Changing a mark that is already in needs a reason the student can read.")
        payload["reason"] = reason.strip()
        before = notices.previous_value(course_id, roll, item_id)
        block_no = add_entry("correction", payload, teacher_id)[0]
        notices.mark_saved("correction", payload, teacher_id, before)
        return block_no
    block_no = add_entry("score", payload, teacher_id)[0]
    notices.mark_saved("score", payload, teacher_id, None)
    return block_no


# ------------------------------------------------------------------
# objections, grouped into threads
# ------------------------------------------------------------------
def objection_threads(course_id, roll, item_id):
    """Every objection on one mark, each with the events that belong to it.

    An objection's ID is the block number where it was opened. Anything
    that follows it (emails, the teacher's reply, closing) carries that ID,
    which is how it gets nested underneath.

    Older entries written before IDs existed are handled too: a close with
    no ID attaches to the most recent open objection on the same mark.
    """
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT block_no, entry_type, payload, actor, created_at
                   FROM blocks WHERE entry_type IN ('objection','notification')
                   ORDER BY block_no""")
    rows = cur.fetchall()
    con.close()

    threads = {}
    order = []
    last_open = None

    for block_no, kind, text, actor, at in rows:
        p = json.loads(text)
        if (p.get("course_id"), p.get("roll"), p.get("item_id")) != (course_id, roll, item_id):
            continue

        event = {"block_no": block_no, "type": kind, "actor": actor, "at": at, "detail": p}

        if kind == "objection" and p.get("status") == "open":
            tid = p.get("objection_id", block_no)
            threads[tid] = {"id": tid, "opened": event, "status": "open", "events": []}
            order.append(tid)
            last_open = tid
            continue

        tid = p.get("objection_id")
        if tid is None and kind == "objection":
            tid = last_open                      # old close with no ID
        if tid is None or tid not in threads:
            continue                             # not part of any objection

        threads[tid]["events"].append(event)
        if kind == "objection" and p.get("status") == "closed":
            threads[tid]["status"] = "closed"

    return [threads[t] for t in order]


def course_objections(course_id):
    """Every objection in one course, oldest first, each with its answer if it has one."""
    con = connect()
    found = con.execute("SELECT block_no, payload, actor, created_at FROM blocks "
                        "WHERE entry_type='objection' ORDER BY block_no").fetchall()
    con.close()
    threads = {}
    for block_no, text, actor, at in found:
        p = json.loads(text)
        if p.get("course_id") != course_id:
            continue
        if p.get("status") == "open" and "objection_id" not in p:
            threads[block_no] = {"id": block_no, "roll": p["roll"], "item_id": p["item_id"],
                                 "note": p.get("note", ""), "at": at, "status": "open",
                                 "answer": None, "answered_by": None, "answered_at": None}
        elif p.get("status") == "closed" and p.get("objection_id") in threads:
            threads[p["objection_id"]].update(status="closed", answer=p.get("note"),
                                              answered_by=actor, answered_at=at)
    return list(threads.values())


def open_objection(course_id, roll, item_id):
    for t in objection_threads(course_id, roll, item_id):
        if t["status"] == "open":
            return t
    return None


# ------------------------------------------------------------------
# notifications — recorded with what really happened to the email
# ------------------------------------------------------------------
STUDENT_DOMAIN = "std.cu.ac.bd"


def notify(course_id, roll, item_id, objection_id, who, address, subject, body):
    import mailer
    if address:
        status, note = mailer.send(address, subject, body)
    else:
        status, note = "blocked", "staff are not on the prototype's allow-list"
    add_entry(
        "notification",
        {"course_id": course_id, "roll": roll, "item_id": item_id,
         "objection_id": objection_id, "to": who, "status": status,
         "note": note, "about": subject},
        "system",
    )
    return status


# ------------------------------------------------------------------
# rule 3: one open objection per mark, only on a mark that exists,
#         and raising one always notifies the teacher
# ------------------------------------------------------------------
def raise_objection(roll, course_id, item_id, note):
    if not enrolled(course_id, roll):
        raise Refused("You are not enrolled in this course.")
    if not mark_was_entered(course_id, roll, item_id):
        raise Refused("There is no mark here to object to yet.")

    already = open_objection(course_id, roll, item_id)
    if already:
        raise Refused(f"Objection #{already['id']} on this mark is still open. "
                      "Wait for it to be answered first.")

    block_no, _ = add_entry(
        "objection",
        {"course_id": course_id, "roll": roll, "item_id": item_id,
         "note": note or "Raised from the results page", "status": "open"},
        f"student:{roll}",
    )

    label = item_id.rsplit("-", 1)[-1]
    notify(course_id, roll, item_id, block_no, "student", f"{roll}@{STUDENT_DOMAIN}",
           f"Objection #{block_no} received — {label}",
           f"Your objection on {label} ({course_id}) has been recorded as #{block_no}.\n"
           f"What you wrote: {note or 'Raised from the results page'}\n\n"
           "Your teacher and the academic office have been told. The objection stays in "
           "this mark's history permanently, even after it is answered.")
    notify(course_id, roll, item_id, block_no, "course teacher", None,
           f"Objection #{block_no} raised on {label}", "")
    return block_no


# ------------------------------------------------------------------
# rule 4: only the course teacher closes an objection, with an outcome,
#         and closing always notifies the student
# ------------------------------------------------------------------
def close_objection(teacher_id, course_id, roll, item_id, outcome):
    if not teacher_teaches(teacher_id, course_id):
        raise Refused("You are not assigned to this course.")
    thread = open_objection(course_id, roll, item_id)
    if not thread:
        raise Refused("There is no open objection on this mark.")
    if not outcome or not outcome.strip():
        raise Refused("Closing an objection needs an outcome the student can read.")

    add_entry(
        "objection",
        {"course_id": course_id, "roll": roll, "item_id": item_id,
         "objection_id": thread["id"], "note": outcome.strip(), "status": "closed"},
        teacher_id,
    )
    label = item_id.rsplit("-", 1)[-1]
    notify(course_id, roll, item_id, thread["id"], "student", f"{roll}@{STUDENT_DOMAIN}",
           f"Objection #{thread['id']} answered — {label}",
           f"Your objection on {label} ({course_id}) has been closed.\n"
           f"Outcome: {outcome.strip()}")
    return thread["id"]


# ==================================================================
# the syllabus rules — from the curriculum, sessions 2022-23 & 2023-24
# ==================================================================
import datetime as _dt

TERM_START = _dt.date(2026, 9, 1)

# attendance percentage → marks per unit (curriculum section 1.4)
ATTENDANCE_SCALE = [(90, 10), (85, 9), (80, 8), (75, 7), (70, 6)]

# theory, 3 credits = 75 marks: attendance 10%, class tests 18%, final 72%
THEORY_SPLIT = {"attendance": 7.5, "ct": 13.5}          # CATM = 21

# lab, 1 credit = 25 marks: attendance 10%, quiz+viva 40%, practical 50%
LAB_SPLIT = {"attendance": 0.10, "quiz_viva": 0.40, "practical": 0.50}

# two labs share one slot; groups swap every week
PAIRED_LABS = {"EEE512-2026": 0, "EEE514-2026": 0,
               "CSE518-2026": 1, "EEE516-2026": 1}


def lab_group(roll):
    """The department's real rule goes here. For now: even last digit → A."""
    return "A" if int(roll[-1]) % 2 == 0 else "B"


def attends(roll, course_id, day):
    """Does this student's group have this lab on this day?"""
    if course_id not in PAIRED_LABS:
        return True
    week = (day - TERM_START).days // 7
    offset = 0 if lab_group(roll) == "A" else 1
    return (week + offset) % 2 == PAIRED_LABS[course_id]


def attendance_marks(percent, portion):
    """Fixed scale: 90%+ full marks, stepping down, below 70% nothing."""
    for floor, per_unit in ATTENDANCE_SCALE:
        if percent >= floor:
            return portion * per_unit / 10
    return 0.0


def best_n(fractions, n):
    """The best n class tests count. Each is a fraction of its own out-of."""
    return sorted(fractions, reverse=True)[:n]


# ==================================================================
# projects — self-reported by the student
# ==================================================================
def add_project(roll, title, summary, year):
    """A student adds their own project. It is not a verified record,
    so it lives in an ordinary table, not on the chain."""
    title = (title or "").strip()
    summary = (summary or "").strip()
    if not title:
        raise Refused("A project needs a title.")
    if len(title) > 120:
        raise Refused("Keep the title under 120 characters.")
    if len(summary) > 400:
        raise Refused("Keep the summary under 400 characters.")
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise Refused("The year must be a number, like 2026.")
    if not 2000 <= year <= 2100:
        raise Refused("That year doesn't look right.")

    con = connect()
    cur = con.cursor()
    cur.execute("INSERT INTO projects (roll, title, summary, year) VALUES (?,?,?,?)",
                (roll, title, summary, year))
    new_id = cur.lastrowid
    con.commit()
    con.close()
    return new_id


def verify_project(teacher_id, project_id):
    """A teacher confirms a project. The confirmation goes on the chain,
    so it is permanent who vouched for what, and when."""
    if not teacher_id.startswith("teacher:"):
        raise Refused("Only a teacher can verify a project.")
    row = _one("SELECT roll, title FROM projects WHERE id=?", (project_id,))
    if not row:
        raise Refused("No such project.")
    block_no, _ = add_entry("project_verified",
                            {"project_id": project_id, "roll": row[0], "title": row[1]},
                            teacher_id)
    con = connect()
    con.execute("UPDATE projects SET verified_by=?, verified_at=? WHERE id=?",
                (teacher_id, _dt.date.today().isoformat(), project_id))
    con.commit()
    con.close()
    return block_no


# ==================================================================
# uploads
# ==================================================================
MAX_UPLOAD = 5 * 1024 * 1024            # 5 MB
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
DOC_TYPES = {".pdf"}


def check_upload(kind, filename, size):
    """Size and type limits. Without these anyone could upload anything."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = IMAGE_TYPES if kind in ("photo", "project") else IMAGE_TYPES | DOC_TYPES
    if ext not in allowed:
        raise Refused("Only " + ", ".join(sorted(e[1:].upper() for e in allowed)) + " files are allowed here.")
    if size == 0:
        raise Refused("That file is empty.")
    if size > MAX_UPLOAD:
        raise Refused("That file is over 5 MB.")
    return ext


# private locker: a student's own PDFs, visible to nobody else
LOCKER_FILE = 30 * 1024 * 1024          # 30 MB per file
LOCKER_TOTAL = 200 * 1024 * 1024        # 200 MB per student


def check_locker(filename, size, used):
    if not filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp")):
        raise Refused("The locker takes PDFs and pictures (JPG, PNG, WEBP).")
    if size == 0:
        raise Refused("That file is empty.")
    if size > LOCKER_FILE:
        raise Refused("That file is over 30 MB.")
    if used + size > LOCKER_TOTAL:
        left = max(0, LOCKER_TOTAL - used) // (1024 * 1024)
        raise Refused(f"Your locker is nearly full — {left} MB left of 200 MB.")


# ==================================================================
# final exam marks — examiners only
# ==================================================================
FINAL_OUT_OF = 54            # 72% of a 3-credit theory course's 75 marks


def is_examiner(actor):
    row = _one("SELECT role FROM accounts WHERE email=?", (actor,))
    return bool(row) and row[0] == "examiner"


def enter_final(examiner, course_id, roll, value, absent):
    """One final-exam mark. Absent is recorded as its own fact, counted as 0."""
    if not is_examiner(examiner):
        raise Refused("Only an examiner can enter final exam marks.")
    item_id = f"{course_id}-FINAL"
    if not item_exists(course_id, item_id):
        raise Refused("That course has no final exam.")
    if not enrolled(course_id, roll):
        raise Refused(f"{roll} is not enrolled in this course.")

    if absent:
        value = 0
    else:
        check_mark(value, FINAL_OUT_OF)

    payload = {"course_id": course_id, "roll": roll, "item_id": item_id,
               "value": value, "absent": bool(absent)}
    import notices
    if mark_was_entered(course_id, roll, item_id):
        payload["reason"] = "Changed by the examiner before results were published"
        before = notices.previous_value(course_id, roll, item_id)
        result = add_entry("correction", payload, examiner)
        notices.mark_saved("correction", payload, examiner, before)
        return result
    result = add_entry("score", payload, examiner)
    notices.mark_saved("score", payload, examiner, None)
    return result


# ==================================================================
# grades, publishing and promotion — from the curriculum
# ==================================================================
from curriculum import GRADES, PROMOTION_GPA


def grade_for(percent, absent=False):
    """The curriculum's table. Absent from the final is an F, like below 40%."""
    if absent:
        return "F", 0.00
    for floor, letter, point in GRADES:
        if percent >= floor:
            return letter, point
    return "F", 0.00


def published(roll, semester):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT payload FROM blocks WHERE entry_type='semester_result'")
    rows = cur.fetchall()
    con.close()
    return any(json.loads(t)["roll"] == roll and json.loads(t)["semester"] == semester
               for (t,) in rows)


def publish(examiner, session, semester, course_result):
    """
    Publishes one semester for one session.

    course_result(course_id, roll) is handed in by the server; it returns a
    course's total, or None when a final is still missing.

    Students with every final in are published. Anyone still missing a
    final is withheld — named, with the courses holding them back — and
    published later once their marks are in.
    """
    if not is_examiner(examiner):
        raise Refused("Only an examiner can publish results.")

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT roll FROM profile WHERE session=? ORDER BY roll", (session,))
    rolls = [r for (r,) in cur.fetchall()]
    cur.execute("SELECT c.course_id, c.code FROM courses c WHERE c.semester=? ORDER BY c.code",
                (semester,))
    courses = cur.fetchall()
    con.close()
    if not rolls or not courses:
        raise Refused("Nothing to publish for that session and semester.")

    done, withheld, skipped = [], [], []
    for roll in rolls:
        if published(roll, semester):
            skipped.append(roll)
            continue
        results = [course_result(cid_, roll) for cid_, _ in courses]
        missing = [code for (cid_, code), r in zip(courses, results) if r is None]
        if missing:
            withheld.append({"roll": roll, "missing": missing})
            continue

        points = credits = 0
        for r in results:
            add_entry("course_result", {"roll": roll, "semester": semester, **r}, examiner)
            points += r["gp"] * r["credits"]
            credits += r["credits"]
        gpa = round(points / credits, 2)
        add_entry("semester_result",
                  {"roll": roll, "semester": semester, "gpa": gpa, "credits": credits,
                   "promoted": gpa >= PROMOTION_GPA},
                  examiner)
        done.append({"roll": roll, "gpa": gpa})

    return {"published": done, "withheld": withheld, "already": skipped}
