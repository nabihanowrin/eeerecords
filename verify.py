"""
The replica's watchdog.

Run this on a laptop that is NOT the one holding the records. It asks the
writer's laptop for the chain's fingerprints, keeps its own saved copy, and
says whether anything that was already written has since been changed.

It never sees a mark. A fingerprint changes if its record changes, which is
all a watchdog needs — and it means nobody's marks travel across the room.

Run it with:    py verify.py
Or point it somewhere else:   py verify.py http://10.43.199.128:8000

What the answers mean:
  all good      — everything you saw before is still exactly the same
  grown         — new records were added since last time, nothing changed
  CHANGED       — a record you already saw is different now. That is tampering.
  chain broken  — the writer's own check failed: the links no longer match
"""

import json
import sys
import os
import datetime as dt
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

WRITER = "http://10.43.199.128:8000"          # the laptop that holds the records
COPY = "chain_copy.json"                      # our own saved copy, next to this file


def fetch(writer):
    with urlopen(writer.rstrip("/") + "/api/chain", timeout=15) as answer:
        return json.loads(answer.read().decode())


def load_copy():
    if not os.path.exists(COPY):
        return None
    with open(COPY, encoding="utf-8") as f:
        return json.load(f)


def save_copy(seen):
    with open(COPY, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1)


def links_hold(blocks):
    """Every block names the one before it. Walk the whole line."""
    expected = "0" * 64
    for b in blocks:
        if b["prev_hash"] != expected:
            return False, b["block_no"]
        expected = b["hash"]
    return True, None


def compare(old, new):
    """What changed between the copy we kept and what we were just handed."""
    was = {b["block_no"]: b["hash"] for b in old["blocks"]}
    now = {b["block_no"]: b["hash"] for b in new["blocks"]}

    changed = sorted(n for n in was if n in now and was[n] != now[n])
    missing = sorted(n for n in was if n not in now)
    added = sorted(n for n in now if n not in was)
    return changed, missing, added


def main():
    writer = sys.argv[1] if len(sys.argv) > 1 else WRITER
    stamp = dt.datetime.now().strftime("%d %b %Y, %H:%M")
    print(f"\n  Watching {writer}")
    print(f"  {stamp}\n")

    try:
        new = fetch(writer)
    except HTTPError as why:
        print(f"  That laptop answered, but not with the chain ({why.code}).")
        if why.code in (401, 403, 404):
            print("\n  The server there is an older copy. Ask them to stop it with")
            print("  Ctrl+C and start it again, then run this.\n")
        else:
            print()
        return 1
    except URLError as why:
        print("  Could not reach that laptop.")
        print(f"  ({why.reason})")
        print("\n  Check it is switched on, the server is running, and you are")
        print("  both on the same Wi-Fi.\n")
        return 1
    except Exception as why:
        print(f"  Something came back that was not a chain: {type(why).__name__}\n")
        return 1

    print(f"  Records on the chain : {new['count']}")

    ok, where = links_hold(new["blocks"])
    if not ok:
        print(f"  CHAIN BROKEN         : block {where} does not follow the one before it")
    elif not new["ok"]:
        print(f"  CHAIN BROKEN         : {new['message']}")
    else:
        print("  Links                : every record still points at the one before it")

    old = load_copy()
    if old is None:
        save_copy(new)
        print(f"\n  First look. {new['count']} records saved as our copy.")
        print("  Run this again later and it will tell you what moved.\n")
        return 0

    changed, missing, added = compare(old, new)

    if changed or missing:
        print("\n  *** CHANGED ***")
        for n in changed:
            print(f"  Record {n} is not what it was when we last looked.")
        for n in missing:
            print(f"  Record {n} has disappeared.")
        print("\n  Records are only ever supposed to be added, never edited or")
        print("  removed. Keep this copy and tell the others.\n")
        return 2

    if added:
        print(f"\n  All good. {len(added)} new record{'s' if len(added) != 1 else ''} since last time,")
        print("  and nothing we had already seen was touched.\n")
    else:
        print("\n  All good. Nothing has changed since last time.\n")

    save_copy(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
