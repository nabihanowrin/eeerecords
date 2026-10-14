"""
Sample results for the online demo.

When a student registers on the demo server, this gives them a believable
record to look at straight away:
  - a published GPA of 3.50 for every semester their batch has finished
    (every 10th student to register is lucky: 4.00, full CT marks, full attendance)
  - for the current semester: class-test marks for the tests already held,
    and attendance for the classes already held, so CATM is worked out

Everything written here is signed by the actor "sample-data", so the page
can label it clearly as sample data and nobody mistakes it for a real mark.
It is written straight to the chain (not through the teacher rules), and no
emails are sent for it.

Switch it off with SAMPLE_RESULTS=0.
"""

import os
import json
import random
import datetime as dt

from ledger import connect, add_entry

ACTOR = "sample-data"
GPA = 3.50
CREDITS = 20


def enabled():
    return os.environ.get("SAMPLE_RESULTS", "1") == "1"


def _rows(sql, args=()):
    con = connect()
    out = con.execute(sql, args).fetchall()
    con.close()
    return out


def has_sample(roll):
    con = connect()
    found = con.execute("SELECT payload FROM blocks WHERE actor=?", (ACTOR,)).fetchall()
    con.close()
    return any(json.loads(p).get("roll") == roll for (p,) in found)


def give(roll, batch):
    """Write the sample record for one newly registered student."""
    if not enabled() or has_sample(roll):
        return 0
    import contract
    found = _rows("SELECT current_semester FROM academic_sessions WHERE name=?", (batch,))
    if not found:
        return 0
    current = found[0][0]
    rng = random.Random(int(roll))               # the same student always gets the same sample

    # every 10th student to register is a lucky one: a perfect record
    # (called right after the account is created, so this student is counted)
    con = connect()
    registered = con.execute("SELECT COUNT(*) FROM accounts WHERE role='student'").fetchone()[0]
    con.close()
    lucky = registered > 0 and registered % 10 == 0
    gpa = 4.00 if lucky else GPA
    today = dt.date.today()
    written = 0

    # finished semesters: a published GPA
    for sem in range(1, current):
        add_entry("semester_result", {"roll": roll, "semester": sem, "gpa": gpa,
                                      "credits": CREDITS, "sample": True}, ACTOR)
        written += 1

    # current semester: class tests already held
    for item_id, course_id, limit, held_on in _rows(
            "SELECT i.item_id, i.course_id, i.weight, m.held_on FROM items i "
            "JOIN item_meta m ON m.item_id = i.item_id "
            "JOIN courses c ON c.course_id = i.course_id "
            "JOIN enrollments e ON e.course_id = i.course_id AND e.roll = ? "
            "WHERE c.semester = ? AND m.category = 'ct' AND m.held_on IS NOT NULL",
            (roll, current)):
        if dt.date.fromisoformat(held_on) > today:
            continue
        value = limit if lucky else round(limit * rng.uniform(0.70, 0.90))   # about 14-18 of 20
        add_entry("score", {"course_id": course_id, "roll": roll, "item_id": item_id,
                            "value": value, "absent": False, "sample": True}, ACTOR)
        written += 1

    # current semester: attendance for classes already held (about 9 in 10 present)
    for session_id, course_id, held_on in _rows(
            "SELECT s.session_id, s.course_id, s.held_on FROM class_sessions s "
            "JOIN courses c ON c.course_id = s.course_id "
            "JOIN enrollments e ON e.course_id = s.course_id AND e.roll = ? "
            "WHERE c.semester = ? ORDER BY s.held_on", (roll, current)):
        day = dt.date.fromisoformat(held_on)
        if day > today or not contract.attends(roll, course_id, day):
            continue
        add_entry("attendance", {"course_id": course_id, "session_id": session_id, "roll": roll,
                                 "present": lucky or rng.random() < 0.9, "sample": True}, ACTOR)
        written += 1
    return written
