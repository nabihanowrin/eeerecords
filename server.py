"""
The server.

Run it with:   python server.py
Then open:     http://localhost:8080/landing.html

Every write goes through contract.py. This file only reads the chain
and hands the browser what it asks for.
"""

import json
import os
import hashlib
import datetime as dt
from urllib.parse import unquote, quote
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from ledger import connect, verify_chain
from compute import read_scores
import contract
import auth
import mailer
import notices
import complaints
import faculty
import resources
from contract import Refused

# a cloud host tells us which port to use; on a laptop it is 8080
PORT = int(os.environ.get("PORT", "8080"))

# the office's "simulate an insider edit" buttons, for showing tamper
# detection on a server where nobody can open a terminal. DEMO_TAMPER=0 hides them.
DEMO_TAMPER = os.environ.get("DEMO_TAMPER", "1") == "1"

# first start on a fresh machine (e.g. a cloud server): begin from the
# anonymous demo database, so no real student data ever leaves a laptop
if not os.path.exists("records.db") and os.path.exists("demo_records.db"):
    import shutil
    shutil.copyfile("demo_records.db", "records.db")
DAYS = {6: "Sunday", 0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday"}

# the other laptops holding a copy, and what each last told us it has.
# Kept in memory only: it is gossip, not a record.
COPIES = {}


def today():
    return dt.date.today()


def rows(sql, args=()):
    con = connect()
    cur = con.cursor()
    cur.execute(sql, args)
    out = cur.fetchall()
    con.close()
    return out


# ------------------------------------------------------------------
# reading the chain
# ------------------------------------------------------------------
def chain_entries(kinds):
    marks = ",".join("?" * len(kinds))
    out = []
    for block_no, kind, text, actor, at in rows(
            f"SELECT block_no, entry_type, payload, actor, created_at FROM blocks "
            f"WHERE entry_type IN ({marks}) ORDER BY block_no", kinds):
        out.append({"block_no": block_no, "type": kind, "actor": actor,
                    "at": at, "detail": json.loads(text)})
    return out


def attendance_record(course_id, roll):
    """Every session this student is meant to attend, with what happened."""
    # registers, corrections and the seed's older one-per-student rows, replayed
    ticks = {sid: who[roll]["present"]
             for sid, who in contract.registers(course_id).items() if roll in who}
    cancelled = contract.cancelled_classes(course_id)

    out = []
    for sid, held_on, label in rows(
            "SELECT session_id, held_on, topic FROM class_sessions "
            "WHERE course_id=? ORDER BY held_on, session_id", (course_id,)):
        day = dt.date.fromisoformat(held_on)
        if not contract.attends(roll, course_id, day):
            continue
        if sid in cancelled:
            state = "cancelled"
        elif sid in ticks:
            state = "present" if ticks[sid] else "absent"
        elif day > today():
            state = "upcoming"
        else:
            state = "not recorded"
        out.append({"date": held_on, "slot": label, "state": state})
    return out


def attendance_summary(record):
    held = [r for r in record if r["state"] in ("present", "absent")]
    present = sum(1 for r in held if r["state"] == "present")
    pct = round(100 * present / len(held), 1) if held else None
    return {"held": len(held), "present": present, "percent": pct}


def mark_history(course_id, roll, item_id):
    out = []
    for e in chain_entries(["score", "correction"]):
        d = e["detail"]
        if (d.get("course_id"), d.get("roll"), d.get("item_id")) == (course_id, roll, item_id):
            out.append(e)
    return out


def items_for(course_id, roll):
    scores = read_scores(course_id).get(roll, {})
    sem = rows("SELECT semester FROM courses WHERE course_id=?", (course_id,))[0][0]
    show_final = contract.published(roll, sem)          # finals stay hidden until published
    out = []
    for item_id, label, limit, category, held_on in rows(
            "SELECT i.item_id, i.label, i.weight, m.category, m.held_on "
            "FROM items i JOIN item_meta m ON m.item_id = i.item_id "
            "WHERE i.course_id=? AND (m.category != 'final' OR ?) "
            "ORDER BY m.category = 'final', m.held_on, i.item_id", (course_id, int(show_final))):
        value = scores.get(item_id)
        events = mark_history(course_id, roll, item_id)
        absent = bool(events and events[-1]["detail"].get("absent"))
        corrected = [e for e in events if e["type"] == "correction"]

        if value is not None:
            state = "entered"
        elif held_on and dt.date.fromisoformat(held_on) > today():
            state = "upcoming"
        elif held_on:
            state = "not entered"
        else:
            state = "not held yet"

        out.append({
            "item_id": item_id, "label": label, "out_of": limit,
            "category": category, "held_on": held_on,
            "value": value, "absent": absent, "state": state,
            "was": events[0]["detail"]["value"] if corrected else None,
            "open_objection": contract.open_objection(course_id, roll, item_id) is not None,
        })
    return out


# ------------------------------------------------------------------
# CATM
# ------------------------------------------------------------------
def theory_catm(items, att, credits):
    entered = [i for i in items if i["state"] == "entered" and i["category"] == "ct"]
    fractions = [i["value"] / i["out_of"] for i in entered]
    n = int(credits)
    best = contract.best_n(fractions, n)

    ranked = sorted(entered, key=lambda i: i["value"] / i["out_of"], reverse=True)
    counted = {i["item_id"] for i in ranked[:n]}
    tests = [i for i in items if i["category"] == "ct"]
    for i in tests:                              # the Final is not a class test; it has no counted/dropped
        i["counted"] = i["item_id"] in counted

    ct = contract.THEORY_SPLIT["ct"] * (sum(best) / len(best)) if best else 0
    att_marks = (contract.attendance_marks(att["percent"], contract.THEORY_SPLIT["attendance"])
                 if att["percent"] is not None else 0)
    return {
        "ct": round(ct, 2), "ct_of": contract.THEORY_SPLIT["ct"],
        "attendance": round(att_marks, 2), "attendance_of": contract.THEORY_SPLIT["attendance"],
        "total": round(ct + att_marks, 2), "total_of": 21,
        "ct_rule": f"best {n} of {len(tests)} class tests count",
    }


def lab_marks(items, att, full):
    parts = {}
    for cat in ("quiz_viva", "practical"):
        got = [i for i in items if i["category"] == cat and i["state"] == "entered"]
        portion = full * contract.LAB_SPLIT[cat]
        if got:
            frac = sum(i["value"] for i in got) / sum(i["out_of"] for i in got)
            parts[cat] = round(portion * frac, 2)
        else:
            parts[cat] = None
        parts[cat + "_of"] = portion

    att_portion = full * contract.LAB_SPLIT["attendance"]
    parts["attendance"] = (round(contract.attendance_marks(att["percent"], att_portion), 2)
                           if att["percent"] is not None else None)
    parts["attendance_of"] = att_portion
    parts["total"] = round(sum(parts[k] or 0 for k in ("quiz_viva", "practical", "attendance")), 2)
    parts["total_of"] = full
    return parts


def grade_estimate(block, kind):
    """Where this course stands out of 4.00, from what is marked so far.
    It is an estimate: for a theory course the final exam is not in it."""
    if kind == "theory":
        c = block["catm"]
        entered = [i for i in block["items"] if i["category"] == "ct" and i["state"] == "entered"]
        best = int(block["credits"] or 0)
        counted = min(len(entered), best) if best else len(entered)
        possible = (c["ct_of"] * counted / best) if best else 0
        if block["attendance"]["summary"]["percent"] is not None:
            possible += c["attendance_of"]
        earned = c["ct"] + c["attendance"]
        basis = (f"{len(entered)} class test{'s' if len(entered) != 1 else ''} and attendance so far"
                 if entered else "attendance so far")
        note = "The final exam is 72% of this course and is not in this number."
    else:
        m = block["marks"]
        possible = sum(m[k + "_of"] for k in ("quiz_viva", "practical") if m[k] is not None)
        if m["attendance"] is not None:
            possible += m["attendance_of"]
        earned = m["total"]
        basis = "the lab work marked so far"
        note = "A lab has no final exam, so this is close to the real one."

    if not possible:
        return None
    percent = round(100 * earned / possible, 1)
    # above full marks cannot happen through the rules — if it shows up, the
    # database was edited behind the system's back
    letter, gp = contract.grade_for(min(percent, 100))
    return {"percent": percent, "letter": letter, "gp": gp, "basis": basis, "note": note,
            "impossible": percent > 100,
            "earned": round(earned, 2), "possible": round(possible, 2)}


def course_block(course_id, roll):
    code, title, full = rows("SELECT code, title, full_marks FROM courses WHERE course_id=?",
                             (course_id,))[0]
    kind, credits, lab_id, teacher = rows(
        "SELECT kind, credits, lab_id, teacher FROM course_meta WHERE course_id=?",
        (course_id,))[0]

    items = items_for(course_id, roll)
    record = attendance_record(course_id, roll)
    att = attendance_summary(record)

    sem = rows("SELECT semester FROM courses WHERE course_id=?", (course_id,))[0][0]
    block = {"course_id": course_id, "code": code, "title": title, "kind": kind,
             "credits": credits, "teacher": course_teachers(course_id, teacher, roll),
             "items": items, "semester": sem,
             "full": full, "result": published_result(course_id, roll),
             "attendance": {"summary": att, "sessions": record}}

    if kind == "theory":
        block["catm"] = theory_catm(items, att, credits)
    else:
        block["marks"] = lab_marks(items, att, full)
        block["group"] = contract.lab_group(roll) if course_id in contract.PAIRED_LABS else None

    block["estimate"] = grade_estimate(block, kind)
    block["changed"] = sum(1 for i in items if i["was"] is not None)
    return block, lab_id


# ------------------------------------------------------------------
# published results and standing — derived, never typed
# ------------------------------------------------------------------
def semester_results(roll):
    out = {}
    for e in chain_entries(["semester_result"]):
        d = e["detail"]
        if d["roll"] == roll:
            out[d["semester"]] = d
    return out


def published_result(course_id, roll):
    found = None
    for e in chain_entries(["course_result"]):
        d = e["detail"]
        if d["roll"] == roll and d["course_id"] == course_id:
            found = d
    return found


def standing(roll):
    """Which semester a student is in, worked out from published results.
    A GPA of 2.00 or more moves you up; below that, you stay."""
    results = semester_results(roll)
    session = rows("SELECT session FROM profile WHERE roll=?", (roll,))
    fallback = rows("SELECT current_semester FROM academic_sessions WHERE name=?",
                    (session[0][0],)) if session else []
    if not results:
        return {"current": fallback[0][0] if fallback else 1, "held_back": False,
                "graduated": False, "from_results": False}
    n = 1
    while n in results and results[n]["gpa"] >= contract.PROMOTION_GPA:
        n += 1
    held = n in results                      # a published GPA below 2.00
    return {"current": min(n, 8), "held_back": held, "graduated": n > 8,
            "from_results": True}


def course_result(course_id, roll):
    """One course's total for publishing. None while a final is missing."""
    code, full = rows("SELECT code, full_marks FROM courses WHERE course_id=?", (course_id,))[0]
    kind, credits = rows("SELECT kind, credits FROM course_meta WHERE course_id=?", (course_id,))[0]
    block, _ = course_block(course_id, roll)
    absent = False
    if kind == "theory":
        events = mark_history(course_id, roll, f"{course_id}-FINAL")
        if not events:
            return None
        last = events[-1]["detail"]
        absent = bool(last.get("absent"))
        total = block["catm"]["total"] + last["value"]
    else:
        total = block["marks"]["total"]
    percent = round(100 * total / full, 2) if full else 0
    letter, gp = contract.grade_for(percent, absent)
    return {"course_id": course_id, "code": code, "credits": credits, "total": round(total, 2),
            "full": full, "percent": percent, "letter": letter, "gp": gp, "absent_final": absent}


def semester_view(roll):
    st = standing(roll)
    results = semester_results(roll)

    semesters = []
    for n in range(1, 9):
        courses = [{"course_id": c, "code": code, "title": t, "kind": k, "credits": cr,
                    "lab_id": lab, "teacher": te}
                   for c, code, t, k, cr, lab, te in rows(
                       "SELECT c.course_id, c.code, c.title, m.kind, m.credits, m.lab_id, m.teacher "
                       "FROM courses c JOIN course_meta m ON m.course_id = c.course_id "
                       "WHERE c.semester=? ORDER BY c.code", (n,))]
        paired = {c["lab_id"] for c in courses if c["lab_id"]}
        by_id = {c["course_id"]: c for c in courses}
        cards = []
        for c in courses:
            if c["course_id"] in paired:
                continue
            c["lab"] = by_id[c["lab_id"]]["code"] if c["lab_id"] in by_id else None
            cards.append(c)

        if n in results:
            state = "done"
        elif n == st["current"]:
            state = "now"
        elif n < st["current"]:
            state = "past"                   # finished, but no published result in the prototype
        else:
            state = "later"
        semesters.append({"n": n, "state": state, "courses": cards,
                          "gpa": results[n]["gpa"] if n in results else None,
                          "credits_known": all(c["credits"] for c in courses)})

    timetable = []
    for weekday, start, finish, codes, is_ct, room in rows(
            "SELECT weekday, start, finish, codes, is_ct, room FROM timetable "
            "ORDER BY weekday, start"):
        timetable.append({"day": DAYS[weekday], "weekday": weekday, "start": start,
                          "finish": finish, "codes": codes.split("|"),
                          "ct": bool(is_ct), "room": room})

    code_of = {c: code for c, code in rows("SELECT course_id, code FROM courses")}
    cts = [{"date": held_on, "code": code_of[c], "label": label}
           for c, label, held_on in rows(
               "SELECT i.course_id, i.label, m.held_on FROM items i "
               "JOIN item_meta m ON m.item_id = i.item_id WHERE m.category='ct' "
               "ORDER BY m.held_on")]

    return {"semester": st["current"], "standing": st, "semesters": semesters,
            "routine_semester": 5, "timetable": timetable, "cts": cts,
            "group": contract.lab_group(roll)}


# ------------------------------------------------------------------
# home page
# ------------------------------------------------------------------
def course_progress(roll, semester):
    """For each course this semester: how many of its classes are done and how many are left."""
    out = []
    for course_id, code, title in rows(
            "SELECT c.course_id, c.code, c.title FROM courses c "
            "JOIN enrollments e ON e.course_id = c.course_id AND e.roll = ? "
            "WHERE c.semester = ? ORDER BY c.code", (roll, semester)):
        cancelled = contract.cancelled_classes(course_id)
        days = [dt.date.fromisoformat(h) for sid, h in rows(
            "SELECT session_id, held_on FROM class_sessions WHERE course_id=? ORDER BY held_on",
            (course_id,)) if sid not in cancelled]
        days = [d for d in days if contract.attends(roll, course_id, d)]
        if not days:
            continue
        done = sum(1 for d in days if d <= today())
        out.append({"course_id": course_id, "code": code, "title": title, "done": done,
                    "total": len(days), "left": len(days) - done,
                    "percent": round(100 * done / len(days)), "last": days[-1].isoformat()})
    return out


FEES = {"odd": 1200, "even": 800}
SONALI_LINK = "https://billpay.sonalibank.com.bd/cufee"


def payments_view(roll):
    """The semester final exam fee for each semester so far. Not connected to the bank:
    finished semesters are shown as paid (sample), the current one as not paid yet."""
    st = standing(roll)
    out = []
    for n in range(1, min(st["current"], 8) + 1):
        out.append({"semester": n, "amount": FEES["odd" if n % 2 else "even"],
                    "paid": n < st["current"]})
    return {"fees": out, "link": SONALI_LINK, "currency": "Tk"}


def home_view(roll):
    name = rows("SELECT name FROM students WHERE roll=?", (roll,))[0][0]
    p = rows("SELECT student_id, session, father_en, father_bn, mother_en, mother_bn, photo "
             "FROM profile WHERE roll=?", (roll,))[0]
    profile = {"name": name, "roll": roll, "student_id": p[0], "session": p[1],
               "email": f"{roll}@{auth.DOMAIN}",
               "father": " · ".join(x for x in (p[2], p[3]) if x) or None,
               "mother": " · ".join(x for x in (p[4], p[5]) if x) or None,
               "photo": p[6]}

    results = semester_results(roll)
    st = standing(roll)

    semesters, running, pts, creds = [], [], 0.0, 0
    for n in range(1, 9):
        if n in results:
            r = results[n]
            pts += r["gpa"] * r["credits"]
            creds += r["credits"]
            running.append(round(pts / creds, 2))
            semesters.append({"n": n, "state": "done", "gpa": r["gpa"], "cgpa_after": running[-1]})
        elif n == st["current"]:
            semesters.append({"n": n, "state": "now", "gpa": None})
        elif n < st["current"]:
            semesters.append({"n": n, "state": "past", "gpa": None})
        else:
            semesters.append({"n": n, "state": "later", "gpa": None})

    projects = [{"id": i, "title": t, "summary": s, "year": y, "image": img,
                 "verified_by": vb, "verified_at": va}
                for i, t, s, y, img, vb, va in rows(
                    "SELECT id, title, summary, year, image, verified_by, verified_at "
                    "FROM projects WHERE roll=? ORDER BY year DESC, id DESC", (roll,))]

    import demo_results
    return {"profile": profile, "semesters": semesters, "standing": st,
            "sample": demo_results.has_sample(roll),
            "progress": course_progress(roll, st["current"]),
            "warnings": complaints.warnings(roll),
            "cgpa": round(pts / creds, 2) if creds else None,
            "credits_done": creds, "projects": projects}


def save_upload(roll, kind, filename, data, project_id=None):
    ext = contract.check_upload(kind, filename, len(data))
    digest = hashlib.sha256(data).hexdigest()

    folder = os.path.join("uploads", roll)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, digest[:16] + ext)
    with open(path, "wb") as f:               # wb = write bytes
        f.write(data)

    url = "/api/file?path=" + path.replace(os.sep, "/")
    con = connect()
    if kind == "photo":
        con.execute("UPDATE profile SET photo=? WHERE roll=?", (url, roll))
    elif kind == "project":
        con.execute("UPDATE projects SET image=? WHERE id=? AND roll=?", (url, project_id, roll))
    con.commit()
    con.close()

    # the file stays on disk; only its fingerprint goes on the chain
    from ledger import add_entry
    add_entry("upload", {"roll": roll, "kind": kind, "file": url,
                         "sha256": digest, "size": len(data)}, f"student:{roll}")
    return url

def landing_view():
    ach = [{"title": t, "detail": d, "year": y, "image": i}
           for t, d, y, i in rows("SELECT title, detail, year, image FROM achievements "
                                  "ORDER BY year DESC, id DESC")]
    pics = [{"image": i, "caption": c}
            for i, c in rows("SELECT image, caption FROM gallery ORDER BY id")
            if os.path.exists(i)]                 # skip pictures that aren't there
    stats = [{"key": k, "label": l, "value": v, "note": n}
             for k, l, v, n in rows("SELECT key, label, value, note FROM stats ORDER BY rowid")]
    return {"achievements": ach, "gallery": pics, "stats": stats,
            "faculty": faculty.listing(), "contact": faculty.CONTACT,
            "batches": auth.batches(), "open_registration": auth.OPEN_REGISTRATION}


# ------------------------------------------------------------------
# examiner views — final exam marks only, never CATM
# ------------------------------------------------------------------
def exam_sessions():
    return [{"name": n, "current": c,
             "students": rows("SELECT COUNT(*) FROM profile WHERE session=?", (n,))[0][0]}
            for n, c in rows("SELECT name, current_semester FROM academic_sessions ORDER BY name DESC")]


def exam_grid(session, semester):
    loaded = rows("SELECT 1 FROM courses WHERE semester=? LIMIT 1", (semester,))
    students = [{"roll": r, "name": n} for r, n in rows(
        "SELECT s.roll, s.name FROM students s JOIN profile p ON p.roll = s.roll "
        "WHERE p.session=? ORDER BY s.roll", (session,))]
    if not loaded or not students:
        return {"loaded": False, "courses": [], "students": students}

    courses = [{"course_id": c, "code": code, "title": t} for c, code, t in rows(
        "SELECT c.course_id, c.code, c.title FROM courses c "
        "JOIN course_meta m ON m.course_id = c.course_id "
        "WHERE c.semester=? AND m.kind='theory' ORDER BY c.code", (semester,))]

    marks = {}
    for c in courses:
        item = c["course_id"] + "-FINAL"
        for st in students:
            events = mark_history(c["course_id"], st["roll"], item)
            if events:
                d = events[-1]["detail"]
                marks[f"{st['roll']}|{c['course_id']}"] = {"value": d["value"], "absent": bool(d.get("absent"))}
    return {"loaded": True, "courses": courses, "students": students,
            "marks": marks, "out_of": contract.FINAL_OUT_OF}


# ------------------------------------------------------------------
# teacher and office views
# ------------------------------------------------------------------
DEMO_STAFF_NAMES = {"sabrina.demo@cu.ac.bd": "Sabrina Alam"}


def staff_name(email):
    """The faculty list's name for this email, or a readable one made from the email."""
    return (faculty.by_email(email) or DEMO_STAFF_NAMES.get((email or "").lower())
            or email.split("@")[0].replace(".demo", "").replace(".", " ").title())


def course_teachers(course_id, default, roll):
    """The course's listed teachers, plus anyone the office has approved for this student's batch."""
    names = [n.strip() for n in (default or "").split("/") if n.strip()]
    session = rows("SELECT session FROM profile WHERE roll=?", (roll,))
    for (email,) in rows("SELECT a.email FROM teaching t JOIN accounts a ON 'teacher:' || a.roll = t.teacher_id "
                         "WHERE t.course_id=? AND (t.session IS NULL OR t.session=?)",
                         (course_id, session[0][0] if session else None)):
        name = staff_name(email)
        if name not in names:
            names.append(name)
    return " / ".join(names) or None


def class_card(course_id, session, status="approved", request_id=None, note=""):
    """One class: the course, the session, and how many students are in it.
    The count is worked out from the class list — never typed by a teacher."""
    code, title, semester = rows(
        "SELECT code, title, semester FROM courses WHERE course_id=?", (course_id,))[0]
    kind, credits, lab_id = rows(
        "SELECT kind, credits, lab_id FROM course_meta WHERE course_id=?", (course_id,))[0]
    students = rows("SELECT COUNT(*) FROM enrollments e JOIN profile p ON p.roll = e.roll "
                    "WHERE e.course_id=? AND p.session=?", (course_id, session))[0][0]
    return {"course_id": course_id, "session": session, "code": code, "title": title,
            "semester": semester, "kind": kind, "credits": credits, "lab_id": lab_id,
            "students": students, "status": status, "request_id": request_id, "note": note}


def teacher_home(email, teacher_id):
    mine = [class_card(c["course_id"], c["session"]) for c in contract.approved_classes(teacher_id)]
    waiting = [class_card(r["course_id"], r["session"], r["status"], r["id"], r["note"])
               for r in contract.class_requests(teacher_id) if r["status"] != "approved"]
    courses = [{"course_id": c, "code": code, "title": t, "semester": sem}
               for c, code, t, sem in rows(
                   "SELECT course_id, code, title, semester FROM courses ORDER BY semester, code")]
    sessions = [n for (n,) in rows("SELECT name FROM academic_sessions ORDER BY name DESC")]
    return {"profile": {"name": staff_name(email), "email": email, "teacher_id": teacher_id},
            "classes": mine, "waiting": waiting, "courses": courses, "sessions": sessions}


def attending_group(course_id, day):
    """For a paired lab, which group has it that day. None when everyone does."""
    if course_id not in contract.PAIRED_LABS:
        return None
    week = (day - contract.TERM_START).days // 7
    return "A" if week % 2 == contract.PAIRED_LABS[course_id] else "B"


def teach_items(course_id):
    """Everything a teacher marks in this course — never the final exam."""
    return rows("SELECT i.item_id, i.label, i.weight, m.category, m.held_on "
                "FROM items i JOIN item_meta m ON m.item_id = i.item_id "
                "WHERE i.course_id=? AND m.category != 'final' "
                "ORDER BY m.held_on IS NULL, m.held_on, i.item_id", (course_id,))


def course_marks(course_id):
    """The chain replayed: {roll: {item_id: what it says now}}."""
    out = {}
    for e in chain_entries(["score", "correction"]):
        d = e["detail"]
        if d.get("course_id") != course_id:
            continue
        out.setdefault(d["roll"], {})[d["item_id"]] = {
            "value": d.get("value"), "absent": bool(d.get("absent")),
            "by": e["actor"], "at": e["at"], "block_no": e["block_no"],
            "changed": e["type"] == "correction", "reason": d.get("reason")}
    return out


def teach_item_rows(course_id, roll, marks=None):
    """One student's items in the shape theory_catm and lab_marks expect."""
    mine = (marks if marks is not None else course_marks(course_id)).get(roll, {})
    out = []
    for item_id, label, limit, category, held_on in teach_items(course_id):
        m = mine.get(item_id)
        if m:
            state = "entered"
        elif held_on and held_on > today().isoformat():
            state = "upcoming"
        elif held_on:
            state = "not entered"
        else:
            state = "not held yet"
        out.append({"item_id": item_id, "label": label, "out_of": limit, "category": category,
                    "held_on": held_on, "value": None if not m else m["value"],
                    "absent": bool(m and m["absent"]), "state": state,
                    "changed": bool(m and m["changed"])})
    return out


def teach_catm(course_id, session, roll):
    """One student's CATM, or a lab's total — worked out, never stored."""
    marks = course_marks(course_id)
    items = teach_item_rows(course_id, roll, marks)
    record = attendance_record(course_id, roll)
    att = attendance_summary(record)
    kind, credits = rows("SELECT kind, credits FROM course_meta WHERE course_id=?", (course_id,))[0]
    full = rows("SELECT full_marks FROM courses WHERE course_id=?", (course_id,))[0][0]
    name = rows("SELECT name FROM students WHERE roll=?", (roll,))[0][0]

    out = {"roll": roll, "name": name, "items": items, "attendance": att, "kind": kind}
    if kind == "theory":
        out["catm"] = theory_catm(items, att, credits)
    else:
        out["marks"] = lab_marks(items, att, full)
        out["group"] = contract.lab_group(roll)
    return out


def teach_chart(course_id, session):
    """Two lines on a 0-100 axis: class average per test, class attendance per class."""
    students = contract.class_list(course_id, session)
    rolls = [s["roll"] for s in students]
    marks = course_marks(course_id)

    tests = []
    for item_id, label, limit, category, held_on in teach_items(course_id):
        got = [marks[r][item_id] for r in rolls if item_id in marks.get(r, {})]
        values = [m["value"] for m in got if m["value"] is not None]
        if values and limit:
            tests.append({"date": held_on, "label": label, "n": len(values),
                          "percent": round(100 * sum(values) / (len(values) * limit), 1)})

    taken = []
    seen = contract.registers(course_id)
    for sid, held_on in rows("SELECT session_id, held_on FROM class_sessions WHERE course_id=? "
                             "ORDER BY held_on, session_id", (course_id,)):
        who = {r: v for r, v in seen.get(sid, {}).items() if r in rolls}
        if who:
            taken.append({"date": held_on, "n": len(who),
                          "percent": round(100 * sum(1 for v in who.values() if v["present"]) / len(who), 1)})
    return {"tests": tests, "attendance": taken}


def teach_class(course_id, session):
    """One class as a grid: who is in it, every class date, and the register."""
    code, title, semester = rows(
        "SELECT code, title, semester FROM courses WHERE course_id=?", (course_id,))[0]
    kind, credits, lab_id = rows(
        "SELECT kind, credits, lab_id FROM course_meta WHERE course_id=?", (course_id,))[0]

    students = [{**s, "group": contract.lab_group(s["roll"])}
                for s in contract.class_list(course_id, session)]
    saved = contract.registers(course_id)
    cancelled = contract.cancelled_classes(course_id)

    dates = []
    for sid, held_on, topic in rows(
            "SELECT session_id, held_on, topic FROM class_sessions WHERE course_id=? "
            "ORDER BY held_on, session_id", (course_id,)):
        marks = saved.get(sid, {})
        dates.append({"session_id": sid, "held_on": held_on, "slot": topic,
                      "group": attending_group(course_id, dt.date.fromisoformat(held_on)),
                      "future": held_on > today().isoformat(),
                      "cancelled": sid in cancelled,
                      "saved": bool(marks),
                      "marks": {roll: m["present"] for roll, m in marks.items()},
                      "changed": sorted(roll for roll, m in marks.items() if m["reason"])})

    marks = course_marks(course_id)
    items = [{"item_id": i, "label": label, "out_of": limit, "category": cat, "held_on": held,
              "locked": any(i in m for m in marks.values())}
             for i, label, limit, cat, held in teach_items(course_id)]
    grid = {roll: {item: {"value": m["value"], "absent": m["absent"],
                          "changed": m["changed"], "reason": m["reason"]}
                   for item, m in got.items()}
            for roll, got in marks.items()}

    names = {st["roll"]: st["name"] for st in students}
    labels = {i: (label, limit) for i, label, limit, _, _ in teach_items(course_id)}
    objections = []
    for o in contract.course_objections(course_id):
        if o["roll"] not in names:
            continue
        label, limit = labels.get(o["item_id"], (o["item_id"].rsplit("-", 1)[-1], None))
        now = grid.get(o["roll"], {}).get(o["item_id"], {})
        objections.append({**o, "name": names[o["roll"]], "label": label, "out_of": limit,
                           "value": now.get("value"), "absent": now.get("absent", False)})
    objections.sort(key=lambda o: (o["status"] != "open", -o["id"]))

    return {"course_id": course_id, "session": session, "code": code, "title": title,
            "semester": semester, "kind": kind, "credits": credits, "lab_id": lab_id,
            "paired": course_id in contract.PAIRED_LABS,
            "students": students, "dates": dates, "today": today().isoformat(),
            "items": items, "marks": grid, "chart": teach_chart(course_id, session),
            "objections": objections}


def office_requests():
    out = []
    for r in contract.class_requests():
        card = class_card(r["course_id"], r["session"], r["status"], r["id"], r["note"])
        acct = rows("SELECT email FROM accounts WHERE 'teacher:' || roll = ?", (r["teacher_id"],))
        card["teacher"] = staff_name(acct[0][0] if acct else r["teacher_id"].replace("teacher:", ""))
        card["teacher_id"] = r["teacher_id"]
        card["asked_at"] = r["asked_at"]
        card["decided_by"] = r["decided_by"]
        card["decided_at"] = r["decided_at"]
        out.append(card)
    return {"requests": out, "waiting": sum(1 for r in out if r["status"] == "waiting")}


# ------------------------------------------------------------------
# private locker
# ------------------------------------------------------------------
def init_locker():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS locker (
        id INTEGER PRIMARY KEY AUTOINCREMENT, roll TEXT, course_id TEXT,
        name TEXT, path TEXT, size INTEGER, uploaded_at TEXT)""")
    con.commit()
    con.close()


def locker_list(roll, course_id):
    return [{"id": i, "name": n, "size": z, "at": at}
            for i, n, z, at in rows("SELECT id, name, size, uploaded_at FROM locker "
                                    "WHERE roll=? AND course_id=? ORDER BY id DESC", (roll, course_id))]


def locker_save(roll, course_id, filename, data):
    used = rows("SELECT COALESCE(SUM(size),0) FROM locker WHERE roll=?", (roll,))[0][0]
    contract.check_locker(filename, len(data), used)
    if not rows("SELECT 1 FROM enrollments WHERE roll=? AND course_id=?", (roll, course_id)):
        raise Refused("You aren't enrolled in that course.")
    folder = os.path.join("uploads", roll, "locker")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, hashlib.sha256(data).hexdigest()[:16] + ".pdf")
    with open(path, "wb") as f:
        f.write(data)
    con = connect()
    con.execute("INSERT INTO locker (roll, course_id, name, path, size, uploaded_at) VALUES (?,?,?,?,?,?)",
                (roll, course_id, os.path.basename(filename)[:120], path, len(data),
                 dt.datetime.now().isoformat(timespec="minutes")))
    con.commit()
    con.close()


def owned_file(roll, path=None, locker_id=None):
    """The file on disk, only if it belongs to this student. Otherwise None."""
    if locker_id:
        found = rows("SELECT path FROM locker WHERE id=? AND roll=?", (locker_id, roll))
        return found[0][0] if found else None
    if not path:
        return None
    path = os.path.normpath(path)
    mine = os.path.normpath(os.path.join("uploads", roll))
    if not path.startswith(mine + os.sep):
        return None
    return path if os.path.isfile(path) else None


def display_name(user):
    """How a person is shown next to a file they shared."""
    if user["role"] == "student":
        found = rows("SELECT name FROM students WHERE roll=?", (user["roll"],))
        return found[0][0] if found else user["roll"]
    if user["role"] == "teacher":
        return staff_name(user["email"])
    return "Department office" if user["role"] == "office" else user["email"]


# ------------------------------------------------------------------
# the request handler
# ------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):

    def reply(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # files the server must never hand out
    BLOCKED = (".db", ".py", ".pyc", ".log", ".txt", ".json", ".zip", ".md")

    def signed_in(self):
        head = self.headers.get("Authorization", "")
        token = head[7:] if head.startswith("Bearer ") else None
        return auth.who(token), token

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        one = lambda k: q.get(k, [None])[0]

        if url.path == "/":
            self.send_response(302)
            self.send_header("Location", "/landing.html")
            self.end_headers()
            return

        if not url.path.startswith("/api/"):
            if (url.path.lower().endswith(self.BLOCKED) or "__pycache__" in url.path
                    or url.path.startswith("/uploads")):          # files go through /api/file only
                return self.reply({"ok": False, "why": "Not available."}, 404)
            return super().do_GET()

        if url.path == "/api/landing":
            return self.reply(landing_view())

        # The chain, open to the other laptops. With ?full=1 it includes the
        # records themselves, which is what a copy needs: a laptop holding
        # only fingerprints can say a record changed, but not what it said.
        if url.path == "/api/chain":
            full = one("full") in ("1", "true", "yes")
            blocks = []
            for n, t, text, a, at, p, h in rows(
                    "SELECT block_no, entry_type, payload, actor, created_at, prev_hash, hash "
                    "FROM blocks ORDER BY block_no"):
                b = {"block_no": n, "type": t, "actor": a, "at": at, "prev_hash": p, "hash": h}
                if full:
                    b["payload"] = json.loads(text)
                blocks.append(b)
            ok, message = verify_chain()
            return self.reply({"count": len(blocks), "ok": ok, "message": message,
                               "head": blocks[-1]["hash"] if blocks else None,
                               "blocks": blocks})

        # the copy program itself, so nobody has to be sent a file by hand
        if url.path == "/api/peer-code":
            with open("peer.py", "rb") as f:
                code = f.read()
            # point the copy at this laptop, whatever Wi-Fi address it has today
            import re
            here = self.headers.get("Host") or f"localhost:{PORT}"
            code = re.sub(rb'^WRITER = "[^"]*"', f'WRITER = "http://{here}"'.encode(),
                          code, count=1, flags=re.M)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(code)))
            self.end_headers()
            self.wfile.write(code)
            return

        # who else is holding a copy, and what they last reported
        if url.path == "/api/peers":
            now = dt.datetime.now()
            out = []
            for name, p in sorted(COPIES.items()):
                age = (now - p["at"]).total_seconds()
                out.append({**p, "name": name, "at": p["at"].isoformat(timespec="seconds"),
                            "seconds_ago": int(age), "live": age < 40})
            ok, message = verify_chain()
            mine = rows("SELECT COUNT(*), (SELECT hash FROM blocks ORDER BY block_no DESC LIMIT 1) "
                        "FROM blocks")[0]
            return self.reply({"writer": {"name": "writer", "count": mine[0], "head": mine[1],
                                          "ok": ok, "message": message},
                               "copies": out})

        user, _ = self.signed_in()
        if not user:
            return self.reply({"ok": False, "why": "Please sign in.", "signin": True}, 401)
        roll = user["roll"]

        if url.path == "/api/me":
            name = rows("SELECT name FROM students WHERE roll=?", (roll,))
            return self.reply({"ok": True, "role": user["role"], "roll": roll,
                               "email": user["email"], "name": name[0][0] if name else roll})

        # course resources: anyone in the course, its teachers and the office
        if url.path == "/api/resources":
            if not resources.can_see(user, one("course_id")):
                return self.reply({"ok": False, "why": "You are not in this course."}, 403)
            return self.reply(resources.listing(user, one("course_id")))
        if url.path == "/api/resource":
            found = resources.open_file(user, int(one("id") or 0))
            if not found:
                return self.reply({"ok": False, "why": "Not found."}, 404)
            path, filename, kind = found
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Filename", quote(filename))
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        # anyone signed in may check the chain — that is what it is for
        if url.path == "/api/verify":
            ok, message = verify_chain()
            alerts = notices.check_now()          # email anyone affected, right away
            return self.reply({"ok": ok, "message": message, "alerts": alerts,
                               "email": mailer.method()})

        # ---------------- examiner ----------------
        if url.path.startswith("/api/exam/"):
            if user["role"] != "examiner":
                return self.reply({"ok": False, "why": "Examiners only."}, 403)
            if url.path == "/api/exam/sessions":
                return self.reply({"sessions": exam_sessions()})
            if url.path == "/api/exam/grid":
                return self.reply(exam_grid(one("session"), int(one("semester") or 0)))
            return self.reply({"ok": False, "why": "No such endpoint."}, 404)

        # ---------------- teacher ----------------
        if url.path.startswith("/api/teach/"):
            if user["role"] != "teacher":
                return self.reply({"ok": False, "why": "Teachers only."}, 403)
            tid = "teacher:" + user["roll"]
            if url.path == "/api/teach/home":
                return self.reply(teacher_home(user["email"], tid))
            if url.path == "/api/teach/class":
                course_id, session = one("course_id"), one("session")
                if not contract.teacher_teaches(tid, course_id, session):
                    return self.reply({"ok": False, "why": "The office has not given you this class."}, 403)
                return self.reply(teach_class(course_id, session))
            if url.path == "/api/teach/catm":
                course_id, session = one("course_id"), one("session")
                if not contract.teacher_teaches(tid, course_id, session):
                    return self.reply({"ok": False, "why": "The office has not given you this class."}, 403)
                return self.reply(teach_catm(course_id, session, one("roll")))
            return self.reply({"ok": False, "why": "No such endpoint."}, 404)

        # ---------------- office ----------------
        if url.path.startswith("/api/office/"):
            if user["role"] != "office":
                return self.reply({"ok": False, "why": "The office only."}, 403)
            if url.path == "/api/office/requests":
                return self.reply(office_requests())
            if url.path == "/api/office/faculty":
                have = {e for (e,) in rows("SELECT email FROM accounts WHERE role='teacher'")}
                return self.reply({"faculty": [{**f, "has_account": f["email"].lower() in have,
                                                "can_have": f["email"].lower().endswith("@cu.ac.bd")}
                                               for f in faculty.listing()]})
            if url.path == "/api/office/complaints":
                return self.reply({"complaints": complaints.for_office()})
            if url.path == "/api/office/complaint-photo":
                path = complaints.photo_path(int(one("id") or 0))
                if not path:
                    return self.reply({"ok": False, "why": "No photo."}, 404)
                with open(path, "rb") as f:
                    data = f.read()
                kinds = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
                self.send_response(200)
                self.send_header("Content-Type", kinds.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if url.path == "/api/office/demo":
                import demo_tamper
                return self.reply({"enabled": DEMO_TAMPER,
                                   "tampered": os.path.exists(demo_tamper.KEPT),
                                   "email": mailer.method(),
                                   "office_email": mailer.office_address()})
            if url.path == "/api/office/batches":
                return self.reply({"batches": contract.batches()})
            if url.path == "/api/office/students":
                session = one("session")
                found = [b for b in contract.batches() if b["name"] == session]
                if not found:
                    return self.reply({"ok": False, "why": "No such batch."}, 404)
                return self.reply({"batch": found[0], "students": contract.students_in(session)})
            return self.reply({"ok": False, "why": "No such endpoint."}, 404)

        if user["role"] != "student":
            return self.reply({"ok": False, "why": "Students only."}, 403)
        if url.path == "/api/home":
            return self.reply(home_view(roll))

        if url.path == "/api/semester":
            return self.reply(semester_view(roll))

        if url.path == "/api/course":
            if not rows("SELECT 1 FROM courses WHERE course_id=?", (one("course_id"),)):
                return self.reply({"ok": False, "why": "No such course."}, 404)
            main, lab_id = course_block(one("course_id"), roll)
            lab = course_block(lab_id, roll)[0] if lab_id else None
            return self.reply({"main": main, "lab": lab})

        if url.path == "/api/history":
            c, r, i = one("course_id"), roll, one("item_id")
            return self.reply({"marks": mark_history(c, r, i),
                               "threads": contract.objection_threads(c, r, i)})

        if url.path == "/api/file":
            path = owned_file(roll, one("path"), one("locker"))
            if not path:
                return self.reply({"ok": False, "why": "Not found."}, 404)
            with open(path, "rb") as f:
                data = f.read()
            kinds = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".webp": "image/webp"}
            self.send_response(200)
            self.send_header("Content-Type", kinds.get(os.path.splitext(path)[1].lower(),
                                                       "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if url.path == "/api/payments":
            return self.reply(payments_view(roll))

        if url.path == "/api/complaints":
            return self.reply({"complaints": complaints.mine(roll), "warnings": complaints.warnings(roll)})

        if url.path == "/api/locker":
            return self.reply({"files": locker_list(roll, one("course_id"))})

        return self.reply({"ok": False, "why": "No such endpoint."}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        one = lambda k: q.get(k, [None])[0]
        length = int(self.headers.get("Content-Length", 0))

        # a copy on another laptop saying hello. No sign-in: a copy is not a
        # person, and it only ever tells us what it holds.
        if url.path == "/api/peers/hello":
            said = json.loads(self.rfile.read(length) or "{}")
            name = str(said.get("name") or "")[:40] or "copy"
            COPIES[name] = {"url": f"http://{self.client_address[0]}:{int(said.get('port') or 8100)}",
                            "count": said.get("count"), "head": said.get("head"),
                            "ok": bool(said.get("ok")), "note": str(said.get("note") or "")[:200],
                            "at": dt.datetime.now()}
            return self.reply({"ok": True, "known": sorted(COPIES)})

        # ---- the only POSTs allowed without being signed in ----
        if url.path in ("/api/register/start", "/api/register/finish", "/api/signin"):
            body = json.loads(self.rfile.read(length) or "{}")
            try:
                if url.path == "/api/register/start":
                    status, shown = auth.start_registration(
                        body.get("email"), body.get("father"), body.get("mother"),
                        body.get("name"), body.get("batch"))
                    out = {"ok": True, "emailed": status == "sent"}
                    if shown:
                        out["code"] = shown          # email is off on this server
                    return self.reply(out)
                if url.path == "/api/register/finish":
                    email = auth.finish_registration(body.get("email"), body.get("code"),
                                                     body.get("password"))
                    token, role = auth.sign_in(email, body.get("password"), body.get("remember"))
                    return self.reply({"ok": True, "token": token, "role": role})
                if url.path == "/api/signin":
                    token, role = auth.sign_in(body.get("email"), body.get("password"), body.get("remember"))
                    return self.reply({"ok": True, "token": token, "role": role})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        user, token = self.signed_in()
        if not user:
            return self.reply({"ok": False, "why": "Please sign in.", "signin": True}, 401)
        roll = user["roll"]

        if url.path == "/api/signout":
            auth.sign_out(token)
            return self.reply({"ok": True})

        if url.path == "/api/resources/upload":
            try:
                if length > resources.MAX_FILE:
                    raise Refused(f"Files must be under {resources.MAX_FILE // (1024 * 1024)} MB.")
                data = self.rfile.read(length)
                new_id = resources.add(user, display_name(user), one("course_id"), one("category"),
                                       unquote(self.headers.get("X-Filename", "")),
                                       unquote(self.headers.get("X-Title", "")), data)
                return self.reply({"ok": True, "id": new_id})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if url.path == "/api/resources/remove":
            body = json.loads(self.rfile.read(length) or "{}")
            try:
                resources.remove(user, int(body.get("id") or 0))
                return self.reply({"ok": True})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if url.path == "/api/exam/publish":
            if user["role"] != "examiner":
                return self.reply({"ok": False, "why": "Examiners only."}, 403)
            body = json.loads(self.rfile.read(length) or "{}")
            try:
                out = contract.publish(user["email"], body.get("session"),
                                       int(body.get("semester") or 0), course_result)
                return self.reply({"ok": True, **out})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if url.path == "/api/exam/save":
            if user["role"] != "examiner":
                return self.reply({"ok": False, "why": "Examiners only."}, 403)
            body = json.loads(self.rfile.read(length) or "{}")
            results = []
            for e in body.get("entries", []):
                try:
                    contract.enter_final(user["email"], e["course_id"], e["roll"],
                                         e.get("value"), bool(e.get("absent")))
                    results.append({"course_id": e["course_id"], "roll": e["roll"], "ok": True})
                except (Refused, KeyError) as why:
                    results.append({"course_id": e.get("course_id"), "roll": e.get("roll"),
                                    "ok": False, "why": str(why)})
            return self.reply({"ok": all(r["ok"] for r in results), "results": results})

        if url.path == "/api/office/add-teacher":
            if user["role"] != "office":
                return self.reply({"ok": False, "why": "The office only."}, 403)
            body = json.loads(self.rfile.read(length) or "{}")
            email = (body.get("email") or "").strip().lower()
            if not faculty.by_email(email):
                return self.reply({"ok": False, "why": "That email is not on the faculty list."}, 400)
            if rows("SELECT 1 FROM accounts WHERE email=?", (email,)):
                return self.reply({"ok": False, "why": "That teacher already has an account."}, 400)
            import secrets
            password = "teach-" + secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
            try:
                auth.create_staff_account(email, "teacher", password)
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)
            from ledger import add_entry
            add_entry("staff_account", {"email": email, "role": "teacher"}, f"office:{user['email']}")
            return self.reply({"ok": True, "email": email, "password": password})

        if url.path == "/api/office/complaint-flag":
            if user["role"] != "office":
                return self.reply({"ok": False, "why": "The office only."}, 403)
            body = json.loads(self.rfile.read(length) or "{}")
            try:
                return self.reply({"ok": True, "block_no": complaints.flag(user["email"], int(body.get("id") or 0))})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        # ---------------- demo: an insider edit, and putting it back ----------------
        if url.path in ("/api/office/demo-tamper", "/api/office/demo-undo"):
            if user["role"] != "office":
                return self.reply({"ok": False, "why": "The office only."}, 403)
            if not DEMO_TAMPER:
                return self.reply({"ok": False, "why": "The demo is switched off."}, 403)
            import demo_tamper
            if url.path.endswith("tamper"):
                if os.path.exists(demo_tamper.KEPT):
                    return self.reply({"ok": False, "why": "A record is already changed. Put it back first."}, 400)
                row = demo_tamper.latest_mark()
                if not row:
                    return self.reply({"ok": False, "why": "No marks yet. Enter one as a teacher first."}, 400)
                block_no, text = row
                before = json.loads(text)
                after = dict(before)
                after["value"] = (before.get("value") or 0) + 5
                with open(demo_tamper.KEPT, "w", encoding="utf-8") as f:
                    json.dump({"block_no": block_no, "payload": text}, f)
                con = connect()
                con.execute("UPDATE blocks SET payload=? WHERE block_no=?",
                            (json.dumps(after, sort_keys=True, separators=(",", ":")), block_no))
                con.commit()
                con.close()
                return self.reply({"ok": True, "block_no": block_no, "roll": before.get("roll"),
                                   "item_id": before.get("item_id"),
                                   "was": before.get("value"), "now": after["value"]})
            if not os.path.exists(demo_tamper.KEPT):
                return self.reply({"ok": False, "why": "Nothing to put back."}, 400)
            with open(demo_tamper.KEPT, encoding="utf-8") as f:
                kept = json.load(f)
            con = connect()
            con.execute("UPDATE blocks SET payload=? WHERE block_no=?", (kept["payload"], kept["block_no"]))
            con.commit()
            con.close()
            os.remove(demo_tamper.KEPT)
            notices.check_now()                   # chain is whole again: refresh the watchdog
            return self.reply({"ok": True, "block_no": kept["block_no"]})

        # ---------------- teacher and office writes ----------------
        if url.path in ("/api/teach/request", "/api/office/decide",
                        "/api/teach/attendance", "/api/teach/attendance/correct",
                        "/api/teach/cancel", "/api/teach/objection/close",
                        "/api/teach/marks", "/api/teach/out-of",
                        "/api/office/batch", "/api/office/student"):
            body = json.loads(self.rfile.read(length) or "{}")
            tid = "teacher:" + user["roll"]
            try:
                if url.path.startswith("/api/teach/"):
                    if user["role"] != "teacher":
                        return self.reply({"ok": False, "why": "Teachers only."}, 403)

                if url.path == "/api/teach/attendance":
                    block_no = contract.save_register(tid, body.get("course_id"), body.get("session"),
                                                      body.get("session_id"), body.get("marks") or {})
                    return self.reply({"ok": True, "block_no": block_no})

                if url.path == "/api/teach/attendance/correct":
                    block_no = contract.correct_attendance(
                        tid, body.get("course_id"), body.get("session"), body.get("session_id"),
                        body.get("roll"), bool(body.get("present")), body.get("reason", ""))
                    return self.reply({"ok": True, "block_no": block_no})

                if url.path == "/api/teach/cancel":
                    block_no = contract.cancel_class(tid, body.get("course_id"), body.get("session"),
                                                     body.get("session_id"))
                    return self.reply({"ok": True, "block_no": block_no})

                if url.path == "/api/teach/objection/close":
                    oid = contract.close_objection(tid, body.get("course_id"), body.get("roll"),
                                                   body.get("item_id"), body.get("outcome", ""))
                    return self.reply({"ok": True, "objection_id": oid})

                if url.path == "/api/teach/out-of":
                    block_no = contract.set_out_of(tid, body.get("course_id"), body.get("session"),
                                                   body.get("item_id"), body.get("out_of"))
                    return self.reply({"ok": True, "block_no": block_no})

                if url.path == "/api/teach/marks":
                    done = []
                    for e in body.get("entries", []):
                        try:
                            block_no = contract.enter_score(
                                tid, body.get("course_id"), body.get("session"), e.get("roll"),
                                e.get("item_id"), e.get("value"), bool(e.get("absent")),
                                e.get("reason", ""))
                            done.append({"roll": e.get("roll"), "item_id": e.get("item_id"),
                                         "ok": True, "block_no": block_no})
                        except (Refused, KeyError) as why:
                            done.append({"roll": e.get("roll"), "item_id": e.get("item_id"),
                                         "ok": False, "why": str(why)})
                    return self.reply({"ok": all(d["ok"] for d in done), "results": done})

                if url.path == "/api/teach/request":
                    asked = contract.request_class(tid, body.get("course_id"), body.get("session"))
                    return self.reply({"ok": True, "request_id": asked})
                if user["role"] != "office":
                    return self.reply({"ok": False, "why": "The office only."}, 403)

                if url.path == "/api/office/batch":
                    block_no = contract.add_batch(user["email"], body.get("name"),
                                                  body.get("semester"))
                    return self.reply({"ok": True, "block_no": block_no})

                if url.path == "/api/office/student":
                    doing = body.get("doing")
                    if doing == "add":
                        block_no = contract.add_student(
                            user["email"], body.get("session"), body.get("roll"), body.get("name"),
                            body.get("student_id"), body.get("father_en"), body.get("father_bn"),
                            body.get("mother_en"), body.get("mother_bn"))
                    elif doing == "change":
                        block_no = contract.update_student(user["email"], body.get("roll"),
                                                           body.get("fields") or {})
                    elif doing == "remove":
                        block_no = contract.remove_student(user["email"], body.get("roll"),
                                                           body.get("reason", ""))
                    else:
                        return self.reply({"ok": False, "why": "Unknown action."}, 400)
                    return self.reply({"ok": True, "block_no": block_no})

                block_no = contract.decide_class(user["email"], body.get("request_id"),
                                                 bool(body.get("approve")), body.get("note", ""))
                return self.reply({"ok": True, "block_no": block_no})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if user["role"] != "student":
            return self.reply({"ok": False, "why": "Students only."}, 403)
        # uploads arrive as raw bytes, not JSON
        if url.path == "/api/locker/upload":
            try:
                if length > contract.LOCKER_FILE:
                    raise Refused("That file is over 30 MB.")
                data = self.rfile.read(length)
                locker_save(roll, one("course_id"), unquote(self.headers.get("X-Filename", "")), data)
                return self.reply({"ok": True})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if url.path == "/api/complaint/photo":
            try:
                if length > contract.MAX_UPLOAD:
                    raise Refused("The photo must be under 5 MB.")
                data = self.rfile.read(length)
                complaints.add_photo(roll, int(one("id") or 0), unquote(self.headers.get("X-Filename", "")), data)
                return self.reply({"ok": True})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        if url.path == "/api/upload":
            try:
                if length > contract.MAX_UPLOAD:
                    raise Refused("That file is over 5 MB.")
                data = self.rfile.read(length)
                name = unquote(self.headers.get("X-Filename", ""))
                link = save_upload(roll, one("kind"), name, data, one("project_id"))
                return self.reply({"ok": True, "url": link})
            except Refused as why:
                return self.reply({"ok": False, "why": str(why)}, 400)

        body = json.loads(self.rfile.read(length) or "{}")

        try:
            if url.path == "/api/locker/delete":
                path = owned_file(roll, locker_id=body.get("id"))
                if not path:
                    raise Refused("Not found.")
                os.remove(path)
                con = connect()
                con.execute("DELETE FROM locker WHERE id=? AND roll=?", (body.get("id"), roll))
                con.commit()
                con.close()
                return self.reply({"ok": True})

            if url.path == "/api/complaint":
                cid = complaints.file(roll, body.get("what"), body.get("why"), body.get("fix"))
                return self.reply({"ok": True, "id": cid})

            if url.path == "/api/project":
                new_id = contract.add_project(roll, body.get("title"),
                                              body.get("summary"), body.get("year"))
                return self.reply({"ok": True, "id": new_id})

            if url.path == "/api/object":
                oid = contract.raise_objection(roll, body["course_id"],
                                               body["item_id"], body.get("note", ""))
                return self.reply({"ok": True, "objection_id": oid})

            if url.path == "/api/correct":
                block_no, _ = contract.correct_mark("teacher:" + user["roll"], body["course_id"],
                                                    body["roll"], body["item_id"],
                                                    body["value"], body.get("reason", ""))
                return self.reply({"ok": True, "block_no": block_no})

        except Refused as why:
            return self.reply({"ok": False, "why": str(why)}, 400)

        return self.reply({"ok": False, "why": "No such endpoint."}, 404)

    def log_message(self, *args):
        pass


init_locker()
contract.init_teaching()
complaints.init()
resources.init()
faculty.apply_course_teachers(connect)

def my_address():
    """This laptop's address on the Wi-Fi, so other people can be told it.
    Nothing is sent anywhere — the socket only asks Windows which card it
    would use to reach the internet."""
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


if __name__ == "__main__":
    auth.init_auth()
    every = notices.start()
    here = my_address()
    print(f"\n  On this laptop : http://localhost:{PORT}/landing.html")
    if here:
        print(f"  On the Wi-Fi   : http://{here}:{PORT}/landing.html")
        print("                   (give that one to anyone on the same network)")
    else:
        print("  Not on a network right now, so only this laptop can open it.")
    print(f"\n  Email: {mailer.method() or 'off'} · watchdog checks the chain every {every:g} min")
    print("\n  Press Ctrl+C to stop.\n")

    # 0.0.0.0 means every network card, not just this laptop
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
