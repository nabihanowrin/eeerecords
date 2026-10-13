"""
Reads the chain back and recomputes every derived number.
Nothing here is stored. Run it twice, get the same answer.
"""

import json
from ledger import connect, verify_chain


def read_scores(course_id):
    """Replay the chain. Later entries for the same student+item win,
    so a correction overrides the original without deleting it."""
    con = connect()
    cur = con.cursor()
    cur.execute(
        """SELECT payload FROM blocks
           WHERE entry_type IN ('score', 'correction')
           ORDER BY block_no"""
    )
    rows = cur.fetchall()
    con.close()

    scores = {}
    for (payload_text,) in rows:
        entry = json.loads(payload_text)
        if entry.get("course_id") != course_id:
            continue
        scores.setdefault(entry["roll"], {})[entry["item_id"]] = entry["value"]
    return scores


def load_items(course_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT item_id, label, weight FROM items WHERE course_id = ?", (course_id,)
    )
    items = cur.fetchall()
    con.close()
    return items


def load_names():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT roll, name FROM students")
    names = dict(cur.fetchall())
    con.close()
    return names


def class_items_percent(marks, items):
    """Weighted average over the items the student actually has a mark for.
    Missing item = counted as zero, which is how the sheet treats a blank."""
    total_weight = sum(weight for _, _, weight in items)
    if total_weight == 0:
        return 0.0

    earned = 0.0
    for item_id, _, weight in items:
        value = marks.get(item_id, 0)
        earned += (value / 100.0) * weight

    return earned / total_weight * 100.0


def build_table(course_id):
    scores = read_scores(course_id)
    items = load_items(course_id)
    names = load_names()

    rows = []
    for roll, marks in scores.items():
        rows.append(
            {
                "roll": roll,
                "name": names.get(roll, "?"),
                "class_items": round(class_items_percent(marks, items), 2),
            }
        )

    rows.sort(key=lambda r: r["class_items"], reverse=True)

    for position, row in enumerate(rows, start=1):
        row["rank"] = position

    return rows


if __name__ == "__main__":
    ok, message = verify_chain()
    print(message)
    if not ok:
        raise SystemExit("Chain is broken. Refusing to compute results.")

    print()
    print(f"{'Rank':<5}{'Roll':<11}{'Name':<30}{'Class items':>12}")
    for row in build_table("EEE311-2025-2"):
        print(
            f"{row['rank']:<5}{row['roll']:<11}{row['name']:<30}"
            f"{row['class_items']:>11.2f}%"
        )