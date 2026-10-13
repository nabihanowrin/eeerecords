"""
Corrections and history.

A wrong mark is never edited or deleted. A new entry is added on top,
and the history of both stays readable forever.
"""

import json
from ledger import connect, add_entry


def correct_mark(course_id, roll, item_id, new_value, actor, reason):
    """Adds a correction entry. The original block is untouched."""
    return add_entry(
        "correction",
        {
            "course_id": course_id,
            "roll": roll,
            "item_id": item_id,
            "value": new_value,
            "reason": reason,
        },
        actor,
    )


def history(course_id, roll, item_id):
    """Every entry ever written for one student's one item, oldest first."""
    con = connect()
    cur = con.cursor()
    cur.execute(
        """SELECT block_no, entry_type, payload, actor, created_at
           FROM blocks
           WHERE entry_type IN ('score', 'correction')
           ORDER BY block_no"""
    )
    rows = cur.fetchall()
    con.close()

    found = []
    for block_no, entry_type, payload_text, actor, created_at in rows:
        entry = json.loads(payload_text)
        if (
            entry.get("course_id") == course_id
            and entry.get("roll") == roll
            and entry.get("item_id") == item_id
        ):
            found.append(
                {
                    "block_no": block_no,
                    "type": entry_type,
                    "value": entry["value"],
                    "actor": actor,
                    "at": created_at,
                    "reason": entry.get("reason", ""),
                }
            )
    return found


def current_value(course_id, roll, item_id):
    """The mark that counts today: the last entry written."""
    entries = history(course_id, roll, item_id)
    return entries[-1]["value"] if entries else None


if __name__ == "__main__":
    COURSE = "EEE311-2025-2"
    ROLL = "23702051"
    ITEM = "EEE311-CT1"

    print("Before the correction")
    print("  current value:", current_value(COURSE, ROLL, ITEM))

    correct_mark(
        COURSE,
        ROLL,
        ITEM,
        85,
        "teacher:eee311",
        "CT1 script re-checked, addition error on page 2",
    )

    print()
    print("After the correction")
    print("  current value:", current_value(COURSE, ROLL, ITEM))

    print()
    print("Full history for this mark:")
    for entry in history(COURSE, ROLL, ITEM):
        line = (
            f"  block {entry['block_no']:<4} {entry['type']:<11}"
            f" value={entry['value']:<5} by {entry['actor']}"
        )
        if entry["reason"]:
            line += f"\n       reason: {entry['reason']}"
        print(line)
