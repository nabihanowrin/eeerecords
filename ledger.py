import hashlib
import json
from datetime import datetime, timezone

# connect() opens Postgres (Supabase) when DATABASE_URL is set, otherwise
# the records.db file — see db.py
from db import connect, DB_FILE, using_postgres  # noqa: F401


def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            roll TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id   TEXT PRIMARY KEY,
            code        TEXT NOT NULL,
            title       TEXT NOT NULL,
            semester    INTEGER NOT NULL,
            session     TEXT NOT NULL,
            full_marks  REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS enrollments (
            course_id TEXT NOT NULL,
            roll      TEXT NOT NULL,
            PRIMARY KEY (course_id, roll)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_id   TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            label     TEXT NOT NULL,
            weight    REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS class_sessions (
            session_id TEXT PRIMARY KEY,
            course_id  TEXT NOT NULL,
            held_on    TEXT NOT NULL,
            topic      TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            block_no   INTEGER PRIMARY KEY,
            entry_type TEXT NOT NULL,
            payload    TEXT NOT NULL,
            actor      TEXT NOT NULL,
            created_at TEXT NOT NULL,
            prev_hash  TEXT NOT NULL,
            hash       TEXT NOT NULL
        )
    """)

    con.commit()
    con.close()


def compute_hash(block_no, entry_type, payload, actor, created_at, prev_hash):
    material = json.dumps(
        {
            "block_no": block_no,
            "entry_type": entry_type,
            "payload": payload,
            "actor": actor,
            "created_at": created_at,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


# functions to call after a block is written (the watchdog uses this to
# remember every record the moment the website saves it)
ON_ADD = []


def add_entry(entry_type, payload, actor):
    con = connect()
    cur = con.cursor()

    cur.execute("SELECT block_no, hash FROM blocks ORDER BY block_no DESC LIMIT 1")
    last = cur.fetchone()

    if last is None:
        block_no = 0
        prev_hash = "0" * 64
    else:
        block_no = last[0] + 1
        prev_hash = last[1]

    created_at = datetime.now(timezone.utc).isoformat()
    block_hash = compute_hash(
        block_no, entry_type, payload, actor, created_at, prev_hash
    )

    cur.execute(
        "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            block_no,
            entry_type,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            actor,
            created_at,
            prev_hash,
            block_hash,
        ),
    )

    con.commit()
    con.close()
    for hook in ON_ADD:
        try:
            hook(block_no, json.dumps(payload, sort_keys=True, separators=(",", ":")))
        except Exception:
            pass
    return block_no, block_hash


def verify_chain():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM blocks ORDER BY block_no")
    rows = cur.fetchall()
    con.close()

    expected_prev = "0" * 64

    for row in rows:
        block_no, entry_type, payload_text, actor, created_at, prev_hash, stored = row

        if prev_hash != expected_prev:
            return False, f"Block {block_no}: previous hash does not match"

        recomputed = compute_hash(
            block_no,
            entry_type,
            json.loads(payload_text),
            actor,
            created_at,
            prev_hash,
        )

        if recomputed != stored:
            return False, f"Block {block_no}: contents were altered"

        expected_prev = stored

    return True, f"Chain is valid ({len(rows)} blocks)"
