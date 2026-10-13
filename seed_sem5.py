"""
Builds a fresh records.db for Semester 5.

Real, from your routine and curriculum:
  - the courses, credits and theory/lab pairs
  - the weekly timetable and rooms
  - the four CT dates for each theory course
  - the vacation gap in October

Made up, for the demo only:
  - every mark, every attendance tick, the CT out-of values
  - the three students other than you

Run it with:   python seed_sem5.py
It deletes records.db first, so it always starts clean.
"""

import os
import datetime as dt

from ledger import init_db, connect, add_entry, DB_FILE
from contract import lab_group, attends

TODAY = dt.date(2026, 9, 21)
TERM_START = dt.date(2026, 9, 1)
TERM_END = dt.date(2026, 11, 5)
VACATION = (dt.date(2026, 10, 16), dt.date(2026, 10, 25))
SESSION = "2026"

# ------------------------------------------------------------------
# courses — all eight semesters, from curriculum.py
# (semester, code, title, credits, kind, lab it pairs with, teacher)
# ------------------------------------------------------------------
from curriculum import COURSES as CURRICULUM, CLASS_2023_24

TEACHERS = {   # only Semester 5 is known, from the routine
    "EEE 511": "Tanvir Sir", "EEE 512": "Tanvir Sir / Arif Sir",
    "EEE 513": "Sabrina Ma'am", "EEE 514": "Sabrina Ma'am",
    "EEE 515": "Sarwar Sir", "EEE 516": "Sangita Ma'am / Sarwar Sir",
    "CSE 517": "Sadia Ma'am", "CSE 518": "Sadia Ma'am / Fazlul Sir",
    "EEE 519": "Fahim Sir", "EEE 510": "Murshad Sir",
}
COURSES = [(sem, code, title, credits, kind, lab, TEACHERS.get(code))
           for sem, code, title, credits, kind, lab in CURRICULUM]
CURRENT_SEM = 5

def cid(code):
    return code.replace(" ", "") + "-" + SESSION

# ------------------------------------------------------------------
# the weekly routine — (weekday, start, end, code, is_ct, room)
# weekday: 6=Sunday 0=Monday 1=Tuesday 2=Wednesday 3=Thursday
# ------------------------------------------------------------------
ROUTINE = [
    (6, "09:00", "09:45", "EEE 515", True,  "R-215"),
    (6, "09:45", "10:30", "EEE 515", False, "R-215"),
    (6, "10:30", "13:00", "EEE 514|EEE 516", False, "R-215"),
    (6, "14:00", "16:30", "EEE 519", False, "R-215"),

    (0, "09:00", "09:45", "EEE 519", True,  "R-215"),
    (0, "09:45", "10:30", "EEE 519", False, "R-215"),
    (0, "10:30", "13:00", "EEE 512|CSE 518", False, "R-215"),
    (0, "14:00", "16:30", "EEE 515", False, "R-215"),

    (1, "09:00", "09:45", "CSE 517", True,  "R-214/117"),
    (1, "09:45", "10:30", "CSE 517", False, "R-214"),
    (1, "10:30", "11:15", "EEE 513", False, "R-117"),
    (1, "11:30", "12:15", "EEE 511", False, "R-117"),
    (1, "12:15", "13:00", "EEE 515", False, "R-117"),

    (2, "09:00", "09:45", "EEE 511", True,  "R-215"),
    (2, "09:45", "10:30", "EEE 511", False, "R-215"),
    (2, "10:30", "11:15", "EEE 513", False, "R-215"),
    (2, "11:30", "12:15", "EEE 519", False, "R-215"),
    (2, "12:15", "13:00", "CSE 517", False, "R-215"),
    (2, "14:00", "16:30", "EEE 510", False, "R-215"),

    (3, "09:00", "09:45", "EEE 513", True,  "R-216"),
    (3, "10:30", "11:15", "EEE 513", False, "R-216"),
    (3, "11:30", "12:15", "CSE 517", False, "R-216"),
    (3, "12:15", "13:00", "EEE 511", False, "R-216"),
]

# ------------------------------------------------------------------
# CT dates, straight from the routine
# ------------------------------------------------------------------
CT_DATES = {
    "EEE 515": ["2026-09-13", "2026-09-27", "2026-10-11", "2026-11-01"],
    "EEE 519": ["2026-09-07", "2026-09-21", "2026-10-05", "2026-10-26"],
    "CSE 517": ["2026-09-01", "2026-09-15", "2026-09-29", "2026-11-03"],
    "EEE 511": ["2026-09-09", "2026-09-23", "2026-10-07", "2026-11-04"],
    "EEE 513": ["2026-09-03", "2026-09-17", "2026-10-01", "2026-10-15"],
}

# ------------------------------------------------------------------
# lab items — (label, category, out_of). Category drives the lab split:
# quiz_viva counts toward the 40%, practical toward the 50%.
# ------------------------------------------------------------------
LAB_ITEMS = [
    ("Quiz",           "quiz_viva", 10),
    ("Viva",           "quiz_viva", 10),
    ("Lab reports",    "practical", 20),
    ("Practical exam", "practical", 20),
]

# the whole 2023-24 class: names and rolls only
STUDENTS = CLASS_2023_24
# the four allow-listed rolls — real inboxes, and the only ones with sample marks
DEMO = ["23702051", "24702045", "24702035", "24702050"]

# sample lab marks for the demo four: (quiz /10, viva /10, reports /20, practical /20)
SAMPLE_LAB = {"23702051": (7, 8, 15, 14), "24702045": (9, 8, 17, 16),
              "24702035": (8, 9, 16, 17), "24702050": (9, 9, 18, 18)}
DEMO_SESSION = "2023–24"

# each session and the semester it is in now (demo mapping)
SESSIONS = [("2025–26", 1), ("2024–25", 3), ("2023–24", 5), ("2022–23", 7), ("2021–22", 8)]

EXAMINER = ("examiner.demo@cu.ac.bd", "exam-demo-2026")

# sample marks for CTs already held, out of each CT's out-of
SAMPLE_CT = {
    "23702051": {"CSE 517": [14, 17], "EEE 513": [12, 15], "EEE 519": [16],
                 "EEE 511": [11],     "EEE 515": [15]},
    "24702045": {"CSE 517": [18, 16], "EEE 513": [17, 18], "EEE 519": [19],
                 "EEE 511": [15],     "EEE 515": [17]},
    "24702035": {"CSE 517": [16, 19], "EEE 513": [14, 16], "EEE 519": [17],
                 "EEE 511": [18],     "EEE 515": [16]},
    "24702050": {"CSE 517": [19, 18], "EEE 513": [18, 17], "EEE 519": [18],
                 "EEE 511": [19],     "EEE 515": [18]},
}

CT_OUT_OF = 20      # sample — the teacher sets this per CT


# ------------------------------------------------------------------
# home page data
# ------------------------------------------------------------------
# Profile fields the office keeps. None means "not on file yet" —
# nothing here is guessed, so the parents' names are left empty.
PROFILES = {
    # the office's enrolment record — obviously fake demo names, in both scripts
    "23702051": {"father_en": "Md. Nasir Uddin Mollah",   "father_bn": "ডেমো বাবা এক",
                 "mother_en": "Monowara Pervin",   "mother_bn": "ডেমো মা এক"},
    "24702045": {"father_en": "Demo Father Two",   "father_bn": "ডেমো বাবা দুই",
                 "mother_en": "Demo Mother Two",   "mother_bn": "ডেমো মা দুই"},
    "24702035": {"father_en": "Demo Father Three", "father_bn": "ডেমো বাবা তিন",
                 "mother_en": "Demo Mother Three", "mother_bn": "ডেমো মা তিন"},
    "24702050": {"father_en": "Demo Father Four",  "father_bn": "ডেমো বাবা চার",
                 "mother_en": "Demo Mother Four",  "mother_bn": "ডেমো মা চার"},
}

# demo accounts already registered. 23702051 is left unregistered on
# purpose, so you can try the registration yourself.
DEMO_PASSWORD = "eee-demo-2026"
PREREGISTERED = ["24702045", "24702035", "24702050"]

# sample content the office would normally write
ACHIEVEMENTS = [
    ("Sample — award or competition result", "The office writes one short line about it here.", 2026),
    ("Sample — research paper accepted", "Title, venue and the students or teachers involved.", 2026),
    ("Sample — new laboratory equipment", "What arrived and which courses will use it.", 2025),
    ("Sample — alumni milestone", "Where a graduate is now and what they did.", 2025),
    ("Sample — workshop or seminar", "Who spoke, when, and a line on what it covered.", 2025),
]

# counters on the landing page. value None = the office hasn't filled it in yet.
STATS = [
    ("semesters", "semesters",       8,    "in the four-year B.Sc. Engineering programme"),
    ("credits",   "credits",         160,  "to graduate, across 40 units and 4000 marks"),
    ("faculty",   "faculty members", 26,   "listed in the department's booklet"),
    ("graduates", "graduates",       None, "since the department began"),
]

# gallery pictures — paths inside your photos folder; missing ones are skipped
GALLERY = [
    ("photos/class.jpg", ""),
    ("photos/building.webp", ""),
    ("photos/dept.jpg", ""),
    ("photos/hq720.jpg", ""),
    ("photos/OIP.webp", ""),
]


# published semester GPAs — sample numbers, 20 credits each semester
SEM_GPA = {
    "23702051": [3.31, 3.18, 3.42, 3.29],
    "24702045": [3.58, 3.66, 3.71, 3.62],
    "24702035": [3.45, 3.52, 3.60, 3.74],
    "24702050": [3.80, 3.77, 3.85, 3.90],
}

# self-reported projects — the student writes these, nobody verifies them yet
PROJECTS = [
    ("23702051", "Tamper-evident academic records",
     "A results system where every mark carries its own history, built on a hash chain.", 2026),
    ("23702051", "Smart Mini City",
     "A scale-model city with sensors and a live web dashboard.", 2025),
]


def in_term(day):
    if day < TERM_START or day > TERM_END:
        return False
    if VACATION[0] <= day <= VACATION[1]:
        return False
    return day.weekday() not in (4, 5)          # Friday, Saturday off


def build():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    import shutil
    shutil.rmtree("uploads", ignore_errors=True)
    init_db()

    con = connect()
    cur = con.cursor()

    cur.execute("""CREATE TABLE course_meta (
        course_id TEXT PRIMARY KEY, kind TEXT, credits REAL,
        lab_id TEXT, teacher TEXT)""")
    cur.execute("""CREATE TABLE item_meta (
        item_id TEXT PRIMARY KEY, category TEXT, held_on TEXT)""")
    cur.execute("""CREATE TABLE timetable (
        weekday INTEGER, start TEXT, finish TEXT,
        codes TEXT, is_ct INTEGER, room TEXT)""")
    cur.execute("""CREATE TABLE profile (
        roll TEXT PRIMARY KEY, student_id TEXT, session TEXT,
        father_en TEXT, father_bn TEXT, mother_en TEXT, mother_bn TEXT, photo TEXT)""")
    cur.execute("""CREATE TABLE achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, detail TEXT,
        year INTEGER, image TEXT, added_by TEXT)""")
    cur.execute("""CREATE TABLE academic_sessions (name TEXT PRIMARY KEY, current_semester INTEGER)""")
    for name, sem in SESSIONS:
        cur.execute("INSERT INTO academic_sessions VALUES (?,?)", (name, sem))
    cur.execute("""CREATE TABLE stats (
        key TEXT PRIMARY KEY, label TEXT, value INTEGER, note TEXT)""")
    cur.execute("""CREATE TABLE gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT, image TEXT, caption TEXT)""")
    cur.execute("""CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, roll TEXT, title TEXT,
        summary TEXT, year INTEGER, image TEXT,
        verified_by TEXT, verified_at TEXT)""")
    cur.execute("""CREATE TABLE teaching (
        teacher_id TEXT, course_id TEXT, PRIMARY KEY (teacher_id, course_id))""")

    # courses
    for sem, code, title, credits, kind, lab, teacher in COURSES:
        full = 25 * credits if credits else 0         # 25 marks per credit; 0 = credits unknown
        cur.execute("INSERT INTO courses VALUES (?,?,?,?,?,?)",
                    (cid(code), code, title, sem, SESSION, full))
        cur.execute("INSERT INTO course_meta VALUES (?,?,?,?,?)",
                    (cid(code), kind, credits, cid(lab) if lab else None, teacher))

    for row in ROUTINE:
        cur.execute("INSERT INTO timetable VALUES (?,?,?,?,?,?)",
                    (row[0], row[1], row[2], row[3], int(row[4]), row[5]))

    for roll, name in STUDENTS:
        cur.execute("INSERT INTO students VALUES (?,?)", (roll, name))
        p = PROFILES.get(roll, {})
        cur.execute("INSERT INTO profile VALUES (?,NULL,?,?,?,?,?,NULL)",
                    (roll, DEMO_SESSION, p.get("father_en"), p.get("father_bn"),
                     p.get("mother_en"), p.get("mother_bn")))
        for sem, code, *_ in COURSES:
            if sem <= CURRENT_SEM:                    # enrolled in every semester reached so far
                cur.execute("INSERT INTO enrollments VALUES (?,?)", (cid(code), roll))

    # theory items: four CTs each, dated
    for code, dates in CT_DATES.items():
        for n, day in enumerate(dates, start=1):
            item = f"{cid(code)}-CT{n}"
            cur.execute("INSERT INTO items VALUES (?,?,?,?)",
                        (item, cid(code), f"CT{n}", CT_OUT_OF))
            cur.execute("INSERT INTO item_meta VALUES (?,?,?)", (item, "ct", day))

    # final exam: one per theory course, out of 54, entered by examiners
    for sem, code, title, credits, kind, *_ in COURSES:
        if kind == "theory" and sem == CURRENT_SEM:
            item = f"{cid(code)}-FINAL"
            cur.execute("INSERT INTO items VALUES (?,?,?,?)", (item, cid(code), "Final", 54))
            cur.execute("INSERT INTO item_meta VALUES (?,?,?)", (item, "final", None))

    # lab items
    for sem, code, title, credits, kind, *_ in COURSES:
        if kind != "lab" or sem != CURRENT_SEM:
            continue
        for label, category, out_of in LAB_ITEMS:
            item = f"{cid(code)}-{label.replace(' ', '')}"
            cur.execute("INSERT INTO items VALUES (?,?,?,?)", (item, cid(code), label, out_of))
            cur.execute("INSERT INTO item_meta VALUES (?,?,?)", (item, category, None))

    # class sessions, generated from the routine across the whole term
    day = TERM_START
    while day <= TERM_END:
        if in_term(day):
            weekday = day.weekday()
            for wd, start, finish, codes, is_ct, room in ROUTINE:
                if wd != weekday or is_ct:
                    continue
                for code in codes.split("|"):
                    sid = f"{cid(code)}-{day.isoformat()}-{start}"
                    cur.execute("INSERT INTO class_sessions VALUES (?,?,?,?)",
                                (sid, cid(code), day.isoformat(), f"{start}–{finish} · {room}"))
        day += dt.timedelta(days=1)

    cur.execute("INSERT INTO teaching VALUES ('teacher:tanvir', ?)", (cid("EEE 511"),))
    for title, detail, year in ACHIEVEMENTS:
        cur.execute("INSERT INTO achievements (title, detail, year, added_by) VALUES (?,?,?,?)",
                    (title, detail, year, "office:sample"))
    for row in STATS:
        cur.execute("INSERT INTO stats VALUES (?,?,?,?)", row)
    for image, caption in GALLERY:
        cur.execute("INSERT INTO gallery (image, caption) VALUES (?,?)", (image, caption))
    for roll, title, summary, year in PROJECTS:
        cur.execute("INSERT INTO projects (roll, title, summary, year) VALUES (?,?,?,?)",
                    (roll, title, summary, year))
    con.commit()
    con.close()

    write_sample_records()

    from auth import init_auth, create_account, DOMAIN
    init_auth()
    for roll in PREREGISTERED:
        create_account(f"{roll}@{DOMAIN}", "student", DEMO_PASSWORD)
    from auth import create_staff_account
    create_staff_account(EXAMINER[0], "examiner", EXAMINER[1])

    import seed_staff                       # the teacher and the office, and her two classes
    seed_staff.build()

    for roll, gpas in SEM_GPA.items():
        for sem, gpa in enumerate(gpas, start=1):
            add_entry("semester_result",
                      {"roll": roll, "semester": sem, "gpa": gpa, "credits": 20},
                      "office:exam-controller")


def write_sample_records():
    """Nothing is written here any more.

    Attendance and marks used to be invented here for the four demo
    students. They are not, because the teacher page is where a tick or a
    mark belongs: a teacher signs in, takes the register, enters the class
    tests, and the student watches it appear. A mark nobody entered is a
    mark nobody can be asked about.

    What is still seeded is only what an office would really hold: the
    courses, the routine, the class dates, the class list, and the
    published GPAs of earlier semesters."""
    return


if __name__ == "__main__":
    build()
    from ledger import verify_chain
    import seed_staff
    print(f"\nSeeded: 8 semesters of courses, {len(STUDENTS)} students in 2023–24.")
    print("No attendance and no marks — the teacher enters those.\n")
    print("Demo logins")
    print(f"  student   24702045@std.cu.ac.bd / {DEMO_PASSWORD}")
    print(f"  teacher   {seed_staff.TEACHER[0]} / {seed_staff.TEACHER[1]}")
    print(f"  office    {seed_staff.OFFICE[0]} / {seed_staff.OFFICE[1]}")
    print(f"  examiner  {EXAMINER[0]} / {EXAMINER[1]}")
    print("\n23702051 is not registered yet — register it from the landing page.")
    print(verify_chain())
