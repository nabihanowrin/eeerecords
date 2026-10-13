"""
Notifications and objections.

Both become chain entries, for the same reason marks do:
if a student later says "nobody told me", the record answers it.
"""

import json
from ledger import connect, add_entry
from corrections import history


def record_notification(course_id, roll, item_id, channel, about, actor="system"):
    """Written when an email actually goes out, not when it is queued."""
    return add_entry(
        "notification",
        {
            "course_id": course_id,
            "roll": roll,
            "item_id": item_id,
            "channel": channel,
            "about": about,
        },
        actor,
    )


def raise_objection(course_id, roll, item_id, note):
    """The student disputes a mark. The actor is the student, nobody else."""
    return add_entry(
        "objection",
        {
            "course_id": course_id,
            "roll": roll,
            "item_id": item_id,
            "note": note,
            "status": "open",
        },
        f"student:{roll}",
    )


def close_objection(course_id, roll, item_id, outcome, actor):
    """Resolved by the teacher or the office. The open entry stays where it is."""
    return add_entry(
        "objection",
        {
            "course_id": course_id,
            "roll": roll,
            "item_id": item_id,
            "note": outcome,
            "status": "closed",
        },
        actor,
    )


def timeline(course_id, roll, item_id):
    """Everything that ever happened to one mark, oldest first."""
    con = connect()
    cur = con.cursor()
    cur.execute(
        """SELECT block_no, entry_type, payload, actor, created_at
           FROM blocks ORDER BY block_no"""
    )
    rows = cur.fetchall()
    con.close()

    events = []
    for block_no, entry_type, payload_text, actor, created_at in rows:
        entry = json.loads(payload_text)
        if (
            entry.get("course_id") == course_id
            and entry.get("roll") == roll
            and entry.get("item_id") == item_id
        ):
            events.append(
                {
                    "block_no": block_no,
                    "type": entry_type,
                    "actor": actor,
                    "at": created_at,
                    "detail": entry,
                }
            )
    return events


def open_objections(course_id):
    """Objections raised and not yet closed. What the office needs to see."""
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT payload FROM blocks WHERE entry_type = 'objection' ORDER BY block_no"
    )
    rows = cur.fetchall()
    con.close()

    latest = {}
    for (payload_text,) in rows:
        entry = json.loads(payload_text)
        if entry.get("course_id") != course_id:
            continue
        latest[(entry["roll"], entry["item_id"])] = entry["status"]

    return [key for key, status in latest.items() if status == "open"]


def describe(event):
    detail = event["detail"]
    if event["type"] == "score":
        return f"mark entered: {detail['value']}"
    if event["type"] == "correction":
        return f"mark corrected to {detail['value']} — {detail.get('reason', '')}"
    if event["type"] == "notification":
        return f"{detail['channel']} sent about {detail['about']}"
    if event["type"] == "objection":
        return f"objection {detail['status']} — {detail['note']}"
    return event["type"]


if __name__ == "__main__":
    COURSE = "EEE311-2025-2"
    ROLL = "23702051"
    ITEM = "EEE311-CT1"

    record_notification(COURSE, ROLL, ITEM, "email", "mark changed from 65 to 85")
    raise_objection(COURSE, ROLL, ITEM, "I think page 2 still was not counted")

    print("Open objections:", open_objections(COURSE))

    close_objection(
        COURSE, ROLL, ITEM, "Script re-checked with the student present, 85 stands",
        "teacher:eee311",
    )
    record_notification(COURSE, ROLL, ITEM, "email", "objection closed")

    print("Open objections after closing:", open_objections(COURSE))
    print()
    print(f"Timeline for roll {ROLL}, {ITEM}")
    for event in timeline(COURSE, ROLL, ITEM):
        print(f"  block {event['block_no']:<4} {event['actor']:<18} {describe(event)}")
