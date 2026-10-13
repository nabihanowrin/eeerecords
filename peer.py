"""
A copy of the records, on your laptop.

Three laptops, three copies. This program keeps one of them.

Every few seconds it asks the writer's laptop for the chain, checks every
record's fingerprint itself, and saves its own copy. It never trusts what it
is given: it recomputes the fingerprints from the records, and it refuses to
overwrite anything it already holds. If a record it saved yesterday comes back
different today, it keeps its own and shouts.

It also serves its copy to the other laptops, so any of you can ask the others
"what do you hold?" and compare, without going through the writer.

    py peer.py najah            give this copy a name
    py peer.py najah 8100       and a port, if 8100 is taken

Open http://localhost:8100 in a browser to watch it.

It updates itself from the writer's laptop each time it starts, so nobody has
to be sent this file twice. Start it with --frozen to stop that.
"""

import hashlib
import json
import os
import socket
import sys
import threading
import time
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen, Request
from urllib.error import URLError

WRITER = "http://10.43.199.128:8000"     # the laptop that accepts new records
EVERY = 10                               # seconds between looks

NAME = "copy"
PORT = 8100
COPY_FILE = "copy_of_the_chain.json"     # our own full copy
DIARY = "diary.json"                     # what the chain looked like, each time we looked

STATE = {"count": 0, "head": None, "ok": True, "note": "starting up",
         "last_look": None, "alarm": None, "others": []}


# ------------------------------------------------------------------
# the fingerprint, worked out the same way the writer works it out
# ------------------------------------------------------------------
def fingerprint(block):
    material = json.dumps(
        {"block_no": block["block_no"], "entry_type": block["type"],
         "payload": block["payload"], "actor": block["actor"],
         "created_at": block["at"], "prev_hash": block["prev_hash"]},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


def check_all(blocks):
    """Is this a real chain? Every record's own fingerprint, and the line
    of them. Returns (ok, what went wrong, where)."""
    expected = "0" * 64
    for b in blocks:
        if "payload" not in b:
            return False, "the writer sent fingerprints without the records", b["block_no"]
        if b["prev_hash"] != expected:
            return False, "a record does not follow the one before it", b["block_no"]
        if fingerprint(b) != b["hash"]:
            return False, "a record does not match its own fingerprint", b["block_no"]
        expected = b["hash"]
    return True, "every record checks out", None


# ------------------------------------------------------------------
# our copy on disk
# ------------------------------------------------------------------
def load(path, empty):
    if not os.path.exists(path):
        return empty
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return empty


def save(path, what):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(what, f)


def write_diary(count, head, note):
    diary = load(DIARY, [])
    diary.append({"when": dt.datetime.now().isoformat(timespec="seconds"),
                  "count": count, "head": head, "note": note})
    save(DIARY, diary[-500:])


# ------------------------------------------------------------------
# taking a copy
# ------------------------------------------------------------------
def fetch(where, path, timeout=15):
    with urlopen(where.rstrip("/") + path, timeout=timeout) as answer:
        return json.loads(answer.read().decode())


def take_a_copy():
    """Ask the writer for the chain, check it, and keep it — but never
    let it overwrite a record we already hold."""
    given = fetch(WRITER, "/api/chain?full=1")
    blocks = given.get("blocks", [])

    ok, note, where = check_all(blocks)
    if not ok:
        STATE.update(ok=False, note=f"{note} (record {where})",
                     alarm=f"The writer's chain does not hold together: {note}, at record {where}.")
        write_diary(len(blocks), given.get("head"), "REFUSED: " + note)
        return

    ours = load(COPY_FILE, {"blocks": []})
    kept = {b["block_no"]: b["hash"] for b in ours["blocks"]}
    changed = [b["block_no"] for b in blocks
               if b["block_no"] in kept and kept[b["block_no"]] != b["hash"]]
    gone = sorted(set(kept) - {b["block_no"] for b in blocks})

    if changed or gone:
        trouble = []
        if changed:
            trouble.append("record " + ", ".join(str(n) for n in changed[:5]) + " was changed")
        if gone:
            trouble.append("record " + ", ".join(str(n) for n in gone[:5]) + " has disappeared")
        STATE.update(ok=False, note=" and ".join(trouble),
                     alarm="Our copy is older and we are keeping it. " + " and ".join(trouble) + ".")
        write_diary(len(ours["blocks"]), ours["blocks"][-1]["hash"] if ours["blocks"] else None,
                    "REFUSED: " + " and ".join(trouble))
        return                                    # our copy stays as it was

    new = len(blocks) - len(ours["blocks"])
    save(COPY_FILE, {"blocks": blocks})
    head = blocks[-1]["hash"] if blocks else None
    STATE.update(count=len(blocks), head=head, ok=True, alarm=None,
                 note=f"{new} new record{'s' if new != 1 else ''}" if new else "nothing new",
                 last_look=dt.datetime.now().strftime("%H:%M:%S"))
    if new or not load(DIARY, []):
        write_diary(len(blocks), head, f"{new} new")


def say_hello():
    """Tell the writer we are here, so the other laptops can find us."""
    body = json.dumps({"name": NAME, "port": PORT, "count": STATE["count"],
                       "head": STATE["head"], "ok": STATE["ok"], "note": STATE["note"]}).encode()
    ask = Request(WRITER.rstrip("/") + "/api/peers/hello", data=body,
                  headers={"Content-Type": "application/json"})
    with urlopen(ask, timeout=10) as answer:
        answer.read()


def ask_the_others():
    """Go straight to the other copies and compare, without the writer
    telling us what they said."""
    try:
        known = fetch(WRITER, "/api/peers", timeout=10)
    except Exception:
        return
    out = []
    for other in known.get("copies", []):
        if other["name"] == NAME:
            continue
        try:
            theirs = fetch(other["url"], "/chain", timeout=8)
            out.append({"name": other["name"], "count": theirs["count"], "head": theirs["head"],
                        "agrees": theirs["head"] == STATE["head"], "reached": True})
        except Exception:
            out.append({"name": other["name"], "count": other.get("count"),
                        "head": other.get("head"),
                        "agrees": other.get("head") == STATE["head"], "reached": False})
    writer = known.get("writer", {})
    out.append({"name": "writer", "count": writer.get("count"), "head": writer.get("head"),
                "agrees": writer.get("head") == STATE["head"], "reached": True})
    STATE["others"] = out


def keep_looking():
    while True:
        try:
            take_a_copy()
        except URLError:
            STATE.update(note="cannot reach the writer's laptop", last_look=dt.datetime.now().strftime("%H:%M:%S"))
        except Exception as why:
            STATE.update(note=f"something went wrong: {type(why).__name__}")
        for step in (say_hello, ask_the_others):
            try:
                step()
            except Exception:
                pass
        time.sleep(EVERY)


# ------------------------------------------------------------------
# what we show the others, and what we show you
# ------------------------------------------------------------------
PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Copy on {name}</title>
<style>
body{{background:#F6F2EE;color:#1C1A19;font-family:Segoe UI,system-ui,sans-serif;margin:0;padding:40px 24px}}
.wrap{{max-width:760px;margin:0 auto}}
h1{{font-size:30px;font-weight:600;margin:0}}
.sub{{color:#6E6764;margin-top:6px;font-size:14px}}
.card{{background:#fff;border:1px solid #E4DCD6;border-radius:18px;padding:22px 24px;margin-top:18px}}
.big{{font-size:40px;font-family:ui-monospace,monospace}}
.k{{font-size:12px;color:#6E6764}}
.hash{{font-family:ui-monospace,monospace;font-size:12.5px;word-break:break-all;color:#6E6764}}
.good{{background:#E3EFE7;color:#3F6A52;border-radius:12px;padding:14px 16px;font-weight:600}}
.bad{{background:#F8E3E5;color:#A4343F;border-radius:12px;padding:14px 16px;font-weight:600}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
td,th{{text-align:left;padding:9px 8px;border-bottom:1px solid #F0EAE5;font-size:14px}}
th{{font-size:11.5px;color:#6E6764;letter-spacing:.05em}}
.yes{{color:#3F6A52;font-weight:600}} .no{{color:#A4343F;font-weight:600}}
</style></head><body><div class="wrap">
<h1>Copy on {name}</h1>
<div class="sub">Watching {writer} · checked at {last_look} · refreshes by itself</div>
<div class="card">
  <div class="k">Records held here</div><div class="big">{count}</div>
  <div class="k" style="margin-top:14px">Last fingerprint</div><div class="hash">{head}</div>
  <div style="margin-top:16px" class="{klass}">{headline}</div>
  <div class="sub">{note}</div>
</div>
<div class="card">
  <h2 style="font-size:16px;margin:0">The other laptops</h2>
  <table><tr><th>Laptop</th><th>Records</th><th>Same as ours?</th></tr>{others}</table>
</div>
</div></body></html>"""


class Serve(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/chain"):
            ours = load(COPY_FILE, {"blocks": []})
            return self.send(json.dumps({
                "name": NAME, "count": len(ours["blocks"]), "head": STATE["head"],
                "ok": STATE["ok"], "note": STATE["note"],
                "hashes": [b["hash"] for b in ours["blocks"]]}))
        if self.path.startswith("/full"):
            return self.send(json.dumps(load(COPY_FILE, {"blocks": []})))
        if self.path.startswith("/diary"):
            return self.send(json.dumps(load(DIARY, [])))

        others = "".join(
            f"<tr><td>{o['name']}</td><td>{o['count'] if o['count'] is not None else '—'}</td>"
            f"<td class=\"{'yes' if o['agrees'] else 'no'}\">"
            f"{'same' if o['agrees'] else 'DIFFERENT'}{'' if o['reached'] else ' (not answering)'}</td></tr>"
            for o in STATE["others"]) or "<tr><td colspan=3>Nobody else yet.</td></tr>"
        return self.send(PAGE.format(
            name=NAME, writer=WRITER, count=STATE["count"], head=STATE["head"] or "—",
            last_look=STATE["last_look"] or "—", note=STATE["note"], others=others,
            klass="bad" if STATE["alarm"] else "good",
            headline=STATE["alarm"] or "Everything we hold is unchanged."), "text/html; charset=utf-8")

    def log_message(self, *args):
        pass


# ------------------------------------------------------------------
# keeping this file up to date, so nobody has to send it again
# ------------------------------------------------------------------
def update_myself():
    mine = os.path.abspath(__file__)
    try:
        with urlopen(WRITER.rstrip("/") + "/api/peer-code", timeout=10) as answer:
            theirs = answer.read()
    except Exception:
        return False
    with open(mine, "rb") as f:
        if f.read() == theirs:
            return False
    with open(mine, "wb") as f:
        f.write(theirs)
    print("  This program was out of date. It has updated itself — starting again.\n")
    os.execv(sys.executable, [sys.executable, mine] + sys.argv[1:] + ["--frozen"])


if __name__ == "__main__":
    words = [w for w in sys.argv[1:] if not w.startswith("--")]
    if words:
        NAME = words[0]
    else:
        NAME = socket.gethostname().split(".")[0].lower()
    if len(words) > 1:
        PORT = int(words[1])
    COPY_FILE = f"copy_{NAME}.json"
    DIARY = f"diary_{NAME}.json"

    if "--frozen" not in sys.argv:
        update_myself()

    print(f"\n  This laptop is called : {NAME}")
    print(f"  Copying from          : {WRITER}")
    print(f"  Watch it at           : http://localhost:{PORT}")
    print(f"  Others reach us at    : http://<this laptop>:{PORT}/chain")
    print("\n  Leave this window open. Ctrl+C to stop.\n")

    threading.Thread(target=keep_looking, daemon=True).start()
    try:
        HTTPServer(("0.0.0.0", PORT), Serve).serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped. Your copy is saved.\n")
