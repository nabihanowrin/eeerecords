"""
The staff demo accounts: one teacher, one office.

This script only adds. It never deletes anything, so it is safe to run on
a database you are already using. seed_sem5.py calls it too, so a freshly
built database has all four roles from the start.

The teacher's two classes are not inserted into the teaching table by hand.
They go through the real rules — the teacher asks, the office approves — so
the approvals are blocks on the chain like every other record.

Run it with:   python seed_staff.py
"""

import auth
import contract
from ledger import connect

TEACHER = ("sabrina.demo@cu.ac.bd", "teacher-demo-2026")
OFFICE = ("office.demo@cu.ac.bd", "office-demo-2026")

# Sabrina Ma'am teaches Communication Systems and its lab (seed_sem5.TEACHERS)
HER_CLASSES = [("EEE513-2026", "2023–24"), ("EEE514-2026", "2023–24")]


def teacher_id(email):
    """teacher:<the part before the @> — the name that signs a block."""
    return "teacher:" + email.split("@")[0]


def account(email, role, password):
    con = connect()
    found = con.execute("SELECT role FROM accounts WHERE email=?", (email,)).fetchone()
    con.close()
    if found:
        print(f"  {email} is already there ({found[0]})")
        return
    auth.create_staff_account(email, role, password)
    print(f"  {email} created as {role}")


def approve(tid, course_id, session):
    if contract.teacher_teaches(tid, course_id, session):
        print(f"  {course_id} · {session} is already approved")
        return
    asked = contract.request_class(tid, course_id, session)
    contract.decide_class(OFFICE[0], asked, True, "Pre-approved for the demo")
    print(f"  {course_id} · {session} requested (#{asked}) and approved")


def build():
    auth.init_auth()
    contract.init_teaching()

    print("Staff accounts")
    account(TEACHER[0], "teacher", TEACHER[1])
    account(OFFICE[0], "office", OFFICE[1])

    print("Her classes")
    tid = teacher_id(TEACHER[0])
    for course_id, session in HER_CLASSES:
        approve(tid, course_id, session)


if __name__ == "__main__":
    build()
    print()
    print("Demo logins")
    print(f"  student   24702045@std.cu.ac.bd / eee-demo-2026")
    print(f"  teacher   {TEACHER[0]} / {TEACHER[1]}")
    print(f"  office    {OFFICE[0]} / {OFFICE[1]}")
    print(f"  examiner  examiner.demo@cu.ac.bd / exam-demo-2026")
