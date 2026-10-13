# Notes

Plain-English notes on what changed and why. Newest at the top.

## 2026-09-24 — Three laptops, three copies

**What happens now.** The other two laptops each run `peer.py`. Every ten
seconds it asks this laptop for the whole chain — the records, not just their
fingerprints — checks every record itself, and saves its own copy. Each copy
also serves what it holds, so the laptops ask *each other*, not only the writer.

**It does not trust what it is given.** It recomputes every fingerprint from
the record itself, and it never overwrites a record it already holds. If a
record it saved yesterday comes back different, it keeps its own copy, says
REFUSED, and writes it in its diary.

**Nobody gets sent the file twice.** `peer.py` updates itself from this laptop
each time it starts. To set a laptop up the first time, one line:

    iwr http://10.43.199.128:8000/api/peer-code -OutFile peer.py; py peer.py najah

**Watching it.** Each copy shows itself at http://localhost:8100 — how many
records it holds, its last fingerprint, and whether the other laptops match.
The office's Chain check page lists the copies from this side.

**Tested, both ways:** with a clean chain the copy took all 26 records and said
so. With one mark changed straight inside the database, the copy refused it and
named the record — without ever being told anything was wrong.

## 2026-09-24 — The office keeps the register: batches and students

**Office sidebar** now has Home, Class requests, Chain check, then a list of
batches, then "Add a new batch".

**Add a new batch** — a name like 2026–27 and which semester it is in now.

**Inside a batch** — add a student (roll number, name, student ID, and the
parents' names), change any of those details on the spot, or remove someone
from the register with a reason.

A new student is automatically enrolled in every course up to the semester
their batch has reached, so their courses appear straight away. A roll number
is digits only, because it becomes their email: roll@std.cu.ac.bd.

**On the chain:** adding a batch, adding a student, changing a student, and
removing one. The parents' names are *not* written to the chain — it records
that a record was added or changed, not what is inside it. Removing a student
deletes their row and their sign-in, but anything already on the chain stays
there for good, with the reason for the removal beside it.

## 2026-09-23 — Class tests, CATM and the class chart

**Class tests tab.** The same grid shape as attendance: students down the side,
tests across the top. Type a number, or `A` for absent, or leave it blank.
Enter jumps to the next student. Nothing saves until you press "Save to the
chain", which first shows you the list of what is about to change. A mark that
is already in cannot be changed without a reason, and the review screen asks
for one on that line.

**Out-of.** Each test's out-of sits in its column header and can be edited
until that test's first mark is saved. After that it is fixed, because changing
it later would silently change everyone's percentage.

**CATM tab.** Pick a student and see it top to bottom: attendance percent,
attendance marks, each test with counted or dropped, the best-n rule, and the
total out of 21. A lab shows quiz and viva, practical and reports, attendance,
and the lab total instead.

**Class chart.** One chart, 0 to 100, across the term: the class average in
each test in maroon, and how much of the class was present in green.

**Teachers still never see final exam marks** — the rules refuse a final item,
and the teacher views leave finals out entirely.

## 2026-09-23 — Attendance: the register is one block

**The rule (contract.py).** A register is what a teacher signs on paper: the
whole class in one entry. `save_register` writes one `attendance_register`
block per class. It refuses a class that hasn't happened, a student who isn't
on the class list, a lab group that doesn't come that day, and a second
register for the same class. Changing a tick afterwards is
`correct_attendance`: its own block, with a reason the student can read, and it
records what the tick was before.

Space was the worry, and it isn't one: about 7,600 per-student ticks a term
would be 2.4 MB, and one block per class instead of one per student makes the
chain about 50 times shorter, which keeps the pages fast — every page replays
the chain to work its numbers out.

**The grid (teacher.html).** Students down the left in a sticky column, class
dates across the top. A cell cycles blank → present → absent → blank, and
nothing is written until you press Save on that date. "✓ all" fills a column.
A saved column turns read-only; clicking a saved cell asks for a reason and
writes a correction. Future dates are locked, and on a paired lab the group
that isn't due that day shows dashes.

**Worth knowing:** the seed only wrote attendance for the four demo students,
so on the nine already-saved classes the other 50 students show "–", meaning
they were never on that register.

## 2026-09-23 — All four roles can sign in, and four tabs at once

**What you see:** the landing page now has three doors — Student, Teacher and
Admin. Office and examiner both use Admin, and the server sends each to its own
page. Two new pages exist: `teacher.html` (her classes) and `office.html`
(approvals and a chain check).

**Signing in hands the page to a new tab.** After a sign-in with "Remember me"
unticked, a button appears: "Open my records in a new tab". You click it, the
new tab gets its own copy of the ticket, and the landing tab goes back to being
a plain sign-in form. That is how four roles stay open side by side on one
laptop. The button exists because a browser only allows a new tab during a real
click, not after a reply comes back from the server.

- Each page now reads *its own tab's* ticket first, and a remembered one only as
  a fallback, so the four tabs never fight over one sign-in.
- "Use this tab for another sign-in" lets go of the ticket here only.
  "Sign out" ends that ticket everywhere it was opened from here.

**Classes are approved on the chain.** A teacher asks for a class (a course plus
a session — there is no student count to type, it is counted from the class
list). The office approves or turns it down. Both the asking and the answer are
blocks, because who is allowed to enter marks is part of the record.

**New files:** `teacher.html`, `office.html`, `seed_staff.py` (add-only: it
creates the teacher and office demo accounts and never deletes anything).

**Demo logins:** student 24702045@std.cu.ac.bd / eee-demo-2026 · teacher
sabrina.demo@cu.ac.bd / teacher-demo-2026 · office office.demo@cu.ac.bd /
office-demo-2026 · examiner examiner.demo@cu.ac.bd / exam-demo-2026

## 2026-09-23 — The sidebar is a flat list again

**What you see:** The sidebar no longer has an expanding tree of all eight
semesters. It now shows: Home, a "SEMESTER n" label, Timetable, Courses, the
course codes for that semester, and Payment. You switch semesters from the
cards on the Home page, the same as before.

**Why:** The tree grew taller than the screen and was fiddly to use. The flat
list fits without scrolling.

**What changed in `app.html`:**
- `drawNav()` was rewritten to draw one flat list for the semester in
  `VIEW_SEM`, instead of a fold-out row for each of the eight semesters.
- `toggleSem()` is gone, and so are the `OPEN` and `COURSES_OPEN` variables
  that remembered what was unfolded. Nothing unfolds anymore.
- The CSS for the tree (`.nav .sub`, `.nav .sub.deep`, `.nav .semrow`,
  `.nav .caret`) was replaced by one rule, `.nav .code`, for the course-code
  buttons.
- The line under your name now reads "Semester 5 · Lab group B".

**A bug this also fixed:** the sidebar rows used the class name `semrow`, which
the Home page's semester-card strip also uses. The Home page style leaked into
the sidebar and gave every row its own tiny scrollbar arrows.

## 2026-09-22 — The sidebar keeps its colour and scrolls inside itself

**What you see:** With many items in the sidebar, the list now scrolls inside
the dark panel instead of spilling onto the cream page.

**Why:** The sidebar is exactly one screen tall (`height:100vh`). A taller list
had nowhere to go, so it overflowed.

**What changed in `app.html`:** the nav list got `min-height:0` (so it is
allowed to shrink) and `overflow-y:auto` (so it scrolls), plus 22px of space
above and below, because the curved cream corners of the selected tab stick out
that far and a scrolling box cuts off anything outside it.
