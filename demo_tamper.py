"""
The cheat, for the demonstration.

This edits one record straight inside records.db, the way someone with
access to the database would: behind the system's back, without going
through contract.py, without a correction, without leaving a note.

That is exactly what the chain is built to expose. After running this:

  - the office's "Chain check" page turns red and names the block
  - verify.py on the other laptops says CHANGED, though they never
    held your data

Run it with:      py demo_tamper.py          raise a mark by 5
Put it back with: py demo_tamper.py undo     exactly as it was

Undo restores the old value, so the chain reads as valid again and you
can run the demonstration a second time.
"""

import json
import os
import sys

from ledger import connect

KEPT = "tamper_backup.json"


def latest_mark():
    """The most recent mark on the chain — the one a cheat would go for."""
    con = connect()
    cur = con.cursor()
    cur.execute("""SELECT block_no, payload FROM blocks
                   WHERE entry_type IN ('score','correction')
                   ORDER BY block_no DESC LIMIT 1""")
    row = cur.fetchone()
    con.close()
    return row


def cheat():
    if os.path.exists(KEPT):
        print("\n  A record is already tampered with. Put it back first:")
        print("      py demo_tamper.py undo\n")
        return 1

    row = latest_mark()
    if not row:
        print("\n  No marks on the chain yet. Enter one as the teacher first.\n")
        return 1

    block_no, text = row
    before = json.loads(text)
    after = dict(before)
    after["value"] = (before.get("value") or 0) + 5

    with open(KEPT, "w", encoding="utf-8") as f:
        json.dump({"block_no": block_no, "payload": text}, f)

    con = connect()
    con.execute("UPDATE blocks SET payload=? WHERE block_no=?",
                (json.dumps(after, sort_keys=True, separators=(",", ":")), block_no))
    con.commit()
    con.close()

    print(f"\n  Block {block_no}: {before['roll']}'s mark on {before['item_id']}")
    print(f"  changed from {before.get('value')} to {after['value']} — in the database,")
    print("  with no correction and no reason. Nothing on screen will admit it.\n")
    print("  Now:")
    print("    - open the office page and press Run the check")
    print("    - have the others run  py verify.py")
    print(f"\n  Put it back with:  py demo_tamper.py undo\n")
    return 0


def undo():
    if not os.path.exists(KEPT):
        print("\n  Nothing to put back.\n")
        return 1
    with open(KEPT, encoding="utf-8") as f:
        kept = json.load(f)

    con = connect()
    con.execute("UPDATE blocks SET payload=? WHERE block_no=?",
                (kept["payload"], kept["block_no"]))
    con.commit()
    con.close()
    os.remove(KEPT)

    from ledger import verify_chain
    ok, message = verify_chain()
    print(f"\n  Block {kept['block_no']} is back exactly as it was.")
    print(f"  {message}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(undo() if "undo" in sys.argv[1:] else cheat())
