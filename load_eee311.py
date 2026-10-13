"""
Loads EEE 311 : 2025 (2) into the ledger.

WARNING: the marks below were transcribed by eye from screenshots.
Check them against the real sheet before using this in a demo.
"""

from ledger import init_db, add_entry, connect

COURSE_ID = "EEE311-2025-2"

# (roll, name)
STUDENTS = [
    ("24702001", "Ayesha Akter"),
    ("24702002", "Lipy Barua"),
    ("24702004", "Mosroor Shakib Ahanaf"),
    ("24702005", "Sunjida Yeasmin Usha"),
    ("24702006", "Umme Azmira Liza"),
    ("24702007", "Md. Hossain Al-Mehedi Evon"),
    ("24702008", "Khalid Saifullah"),
    ("24702009", "Insha An Nahar"),
    ("24702010", "Habiba Sultana"),
    ("24702012", "Imdadul Haque Milon"),
    ("23702045", "Ayesha Nusrat"),
    ("23702051", "Nabiha Nowrin"),
    ("23702055", "Sadia Sifat Rifa"),
]

# (item_id, label, weight)  -- weight is the "out of" shown in the sheet header
ITEMS = [
    ("EEE311-VIVA1", "Viva 1", 10),
    ("EEE311-CT1", "CT1", 30),
    ("EEE311-CT2", "CT2", 30),
    ("EEE311-CT3", "CT3", 30),
]

# roll -> {item_id: value}   blank cell = key simply absent
SCORES = {
    "24702001": {"EEE311-VIVA1": 0, "EEE311-CT1": 40, "EEE311-CT2": 35, "EEE311-CT3": 100},
    "24702002": {"EEE311-VIVA1": 50, "EEE311-CT1": 50, "EEE311-CT2": 75, "EEE311-CT3": 80},
    "24702004": {"EEE311-VIVA1": 50, "EEE311-CT1": 40, "EEE311-CT2": 35, "EEE311-CT3": 95},
    "24702005": {"EEE311-VIVA1": 0, "EEE311-CT2": 5, "EEE311-CT3": 25},
    "24702006": {"EEE311-VIVA1": 80, "EEE311-CT1": 80, "EEE311-CT2": 75, "EEE311-CT3": 100},
    "24702007": {"EEE311-VIVA1": 50, "EEE311-CT1": 20, "EEE311-CT2": 95, "EEE311-CT3": 60},
    "24702008": {"EEE311-VIVA1": 50, "EEE311-CT1": 30, "EEE311-CT2": 35, "EEE311-CT3": 55},
    "24702009": {"EEE311-VIVA1": 0, "EEE311-CT1": 50, "EEE311-CT2": 95, "EEE311-CT3": 50},
    "24702010": {"EEE311-VIVA1": 0, "EEE311-CT1": 45, "EEE311-CT2": 40, "EEE311-CT3": 60},
    "24702012": {"EEE311-VIVA1": 0, "EEE311-CT1": 80, "EEE311-CT2": 75, "EEE311-CT3": 120},
    "23702045": {"EEE311-VIVA1": 75, "EEE311-CT1": 40, "EEE311-CT2": 90, "EEE311-CT3": 110},
    "23702051": {"EEE311-CT1": 65, "EEE311-CT2": 65, "EEE311-CT3": 100},
    "23702055": {"EEE311-VIVA1": 25, "EEE311-CT1": 75, "EEE311-CT2": 100, "EEE311-CT3": 120},
}

TEACHER = "teacher:eee311"


def seed_reference():
    """Reference tables only. These are not facts about a student's performance,
    so they do not go on the chain."""
    con = connect()
    cur = con.cursor()

    cur.execute(
        "INSERT OR REPLACE INTO courses VALUES (?, ?, ?, ?, ?, ?)",
        (COURSE_ID, "EEE 311", "Electronics II (CATM)", 3, "2025 (2)", 21),
    )

    for roll, name in STUDENTS:
        cur.execute("INSERT OR REPLACE INTO students VALUES (?, ?)", (roll, name))
        cur.execute(
            "INSERT OR REPLACE INTO enrollments VALUES (?, ?)", (COURSE_ID, roll)
        )

    for item_id, label, weight in ITEMS:
        cur.execute(
            "INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?)",
            (item_id, COURSE_ID, label, weight),
        )

    con.commit()
    con.close()


def load_scores():
    """Every mark becomes one block on the chain."""
    written = 0
    for roll, marks in SCORES.items():
        for item_id, value in marks.items():
            add_entry(
                "score",
                {
                    "course_id": COURSE_ID,
                    "roll": roll,
                    "item_id": item_id,
                    "value": value,
                },
                TEACHER,
            )
            written += 1
    return written


if __name__ == "__main__":
    init_db()
    seed_reference()
    count = load_scores()
    print(f"Seeded {len(STUDENTS)} students, {len(ITEMS)} items.")
    print(f"Wrote {count} score entries to the chain.")
