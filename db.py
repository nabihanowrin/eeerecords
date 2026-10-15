"""
Where the records are kept.

Two places, picked automatically:

1. Postgres (Supabase), when the setting DATABASE_URL is present.
   This is what the online site uses: the records stay when the site
   restarts or sleeps.
2. The file records.db (SQLite), when DATABASE_URL is not set.
   This is what a laptop uses, with no setup at all.

The rest of the code was written for SQLite, so this file translates
SQLite's way of writing a few things into Postgres's way:
    ?                      ->  %s
    INSERT OR REPLACE      ->  INSERT ... ON CONFLICT (key) DO UPDATE
    INSERT OR IGNORE       ->  INSERT ... ON CONFLICT DO NOTHING
    AUTOINCREMENT          ->  SERIAL
    REAL                   ->  DOUBLE PRECISION   (keeps 10.35 exactly 10.35)
    PRAGMA table_info(t)   ->  a look in information_schema
    cursor.lastrowid       ->  INSERT ... RETURNING id

Opening a new connection to Supabase takes a moment, so connections are
kept in a small pool and reused.
"""

import os
import re
import queue
import sqlite3
import threading
from decimal import Decimal

DB_FILE = "records.db"
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()


def using_postgres():
    return bool(DATABASE_URL)


def connect():
    if DATABASE_URL:
        return _PgConnection(_take())
    return sqlite3.connect(DB_FILE)


# ------------------------------------------------------------------
# a small pool of open Postgres connections
# ------------------------------------------------------------------
_POOL = queue.LifoQueue()
_POOL_MAX = 5


def _open():
    import psycopg
    # ClientCursor fills the values into the SQL text itself (like SQLite
    # does), and prepare_threshold=None never asks the server to remember
    # a query — both make it work through Supabase's connection pooler.
    return psycopg.connect(DATABASE_URL, cursor_factory=psycopg.ClientCursor,
                           prepare_threshold=None, connect_timeout=15)


def _take():
    while True:
        try:
            conn = _POOL.get_nowait()
        except queue.Empty:
            return _open()
        if not conn.closed and not conn.broken:
            return conn


def _give_back(conn):
    import psycopg
    try:
        if conn.closed or conn.broken:
            return
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()                      # like SQLite: closing without commit discards
        if _POOL.qsize() < _POOL_MAX:
            _POOL.put(conn)
        else:
            conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


# ------------------------------------------------------------------
# what Postgres knows about a table (cached)
# ------------------------------------------------------------------
_INFO = {}
_INFO_LOCK = threading.Lock()


def _table_info(raw, table):
    table = table.lower()
    with _INFO_LOCK:
        if table in _INFO:
            return _INFO[table]
    cur = raw.cursor()
    cur.execute("SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s "
                "ORDER BY ordinal_position", (table,))
    cols = cur.fetchall()
    cur.execute("SELECT kcu.column_name FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                "WHERE tc.table_schema = current_schema() AND tc.table_name = %s "
                "  AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position", (table,))
    keys = [r[0] for r in cur.fetchall()]
    info = {"columns": [c[0] for c in cols], "keys": keys,
            "serial_id": any(c[0] == "id" and (c[1] or "").startswith("nextval") for c in cols)}
    if cols:                                     # only remember tables that exist
        with _INFO_LOCK:
            _INFO[table] = info
    return info


def forget_tables():
    with _INFO_LOCK:
        _INFO.clear()


# ------------------------------------------------------------------
# turning SQLite's SQL into Postgres's
# ------------------------------------------------------------------
_CREATE = re.compile(r"^\s*CREATE\s+TABLE", re.I)
_OR_REPLACE = re.compile(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*(\(([^)]*)\))?\s*VALUES", re.I)
_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", re.I)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)
_PRAGMA = re.compile(r"^\s*PRAGMA\s+table_info\((\w+)\)\s*$", re.I)


def _placeholders(sql, has_args):
    """? -> %s outside quotes. With values given, every % must be doubled."""
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append("%%" if (ch == "%" and has_args) else ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%" and has_args:
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


def create_table_sql(sql):
    """A SQLite CREATE TABLE in Postgres words."""
    sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    sql = re.sub(r"^\s*CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", "CREATE TABLE IF NOT EXISTS ", sql, flags=re.I)
    return sql


def translate(raw, sql, has_args):
    """Returns (postgres_sql, wants_returning_id)."""
    m = _PRAGMA.match(sql)
    if m:
        return ("SELECT ordinal_position - 1, column_name FROM information_schema.columns "
                f"WHERE table_schema = current_schema() AND table_name = '{m.group(1).lower()}' "
                "ORDER BY ordinal_position"), False

    # SQLite numbers every row behind the scenes ("rowid"); Postgres's
    # nearest thing is the row's physical place, which keeps insert order
    # for the small tables that use it.
    sql = re.sub(r"\bORDER\s+BY\s+rowid\b", "ORDER BY ctid", sql, flags=re.I)

    if _CREATE.match(sql):
        return _placeholders(create_table_sql(sql), has_args), False

    m = _OR_REPLACE.match(sql)
    if m:
        table = m.group(1)
        info = _table_info(raw, table)
        cols = [c.strip() for c in m.group(3).split(",")] if m.group(3) else info["columns"]
        rest = sql[m.end():]
        keys = info["keys"]
        updates = [c for c in cols if c not in keys]
        if keys and updates:
            tail = (f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET "
                    + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates))
        else:
            tail = " ON CONFLICT DO NOTHING"
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES{rest.rstrip().rstrip(';')}{tail}"
        return _placeholders(sql, has_args), False

    if _OR_IGNORE.match(sql):
        sql = _OR_IGNORE.sub("INSERT INTO ", sql).rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return _placeholders(sql, has_args), False

    m = _INSERT.match(sql)
    if m and "RETURNING" not in sql.upper() and _table_info(raw, m.group(1))["serial_id"]:
        return _placeholders(sql.rstrip().rstrip(";") + " RETURNING id", has_args), True

    return _placeholders(sql, has_args), False


def _plain(value):
    """Postgres hands back a few types SQLite never did; turn them back."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, memoryview):
        return bytes(value)
    return value


def _args(args):
    if not args:
        return None
    return tuple(int(a) if isinstance(a, bool) else a for a in args)


# ------------------------------------------------------------------
# connection and cursor that behave like sqlite3's
# ------------------------------------------------------------------
class _PgCursor:
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.raw.cursor()
        self.lastrowid = None
        self.rowcount = -1
        self._pending = None

    def execute(self, sql, args=()):
        args = _args(args)
        text, returning = translate(self._conn.raw, sql, args is not None)
        self._cur.execute(text, args)
        self.rowcount = self._cur.rowcount
        self._pending = None
        if returning:
            row = self._cur.fetchone()
            self.lastrowid = row[0] if row else None
        elif _CREATE.match(sql) or re.match(r"^\s*ALTER\s+TABLE", sql, re.I):
            forget_tables()
        return self

    def executemany(self, sql, seq):
        for args in seq:
            self.execute(sql, args)
        return self

    def fetchone(self):
        if self._cur.description is None:
            return None
        row = self._cur.fetchone()
        return None if row is None else tuple(_plain(v) for v in row)

    def fetchall(self):
        if self._cur.description is None:
            return []
        return [tuple(_plain(v) for v in row) for row in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()


class _PgConnection:
    def __init__(self, raw):
        self.raw = raw
        self._open = True

    def cursor(self):
        return _PgCursor(self)

    def execute(self, sql, args=()):
        return self.cursor().execute(sql, args)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        if self._open:
            self._open = False
            _give_back(self.raw)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        # sqlite3's "with con:" commits on success and rolls back on error
        if kind is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ------------------------------------------------------------------
# first start on an empty Postgres: copy in the demo database
# ------------------------------------------------------------------
def bootstrap_postgres(seed_file="demo_records.db"):
    """If Postgres has no chain yet, copy every table and row from the demo
    SQLite file, all in one go: either everything arrives, or nothing does."""
    if not DATABASE_URL:
        return "sqlite"
    raw = _open()
    try:
        cur = raw.cursor()
        cur.execute("SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = 'blocks'")
        if cur.fetchone():
            return "already there"
        if not os.path.exists(seed_file):
            return "no demo file"

        src = sqlite3.connect(seed_file)
        tables = src.execute("SELECT name, sql FROM sqlite_master WHERE type='table' "
                             "AND name != 'sqlite_sequence' AND sql IS NOT NULL").fetchall()
        copied = 0
        for name, create in tables:
            cur.execute(create_table_sql(create))
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({name})")]
            rows = src.execute(f"SELECT {', '.join(cols)} FROM {name}").fetchall()
            if rows:
                marks = ", ".join(["%s"] * len(cols))
                cur.executemany(f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({marks})",
                                [tuple(int(v) if isinstance(v, bool) else v for v in r) for r in rows])
                copied += len(rows)
            if "id" in cols and re.search(r"AUTOINCREMENT", create, re.I):
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false)")
        src.close()
        raw.commit()
        forget_tables()
        return f"copied {len(tables)} tables, {copied} rows"
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


# ------------------------------------------------------------------
# uploaded files (photos, PDFs) and the demo's backup file
# ------------------------------------------------------------------
# Render's disk is wiped on every restart. Online, every saved file is
# also kept in Postgres, and put back on disk when the site starts.
_FILES_TABLE = ("CREATE TABLE IF NOT EXISTS stored_files ("
                "path TEXT PRIMARY KEY, data BYTEA NOT NULL, saved_at TEXT)")


def save_file(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as f:                  # wb = write bytes
        f.write(data)
    if DATABASE_URL:
        import datetime as dt
        con = connect()
        con.raw.execute(_FILES_TABLE)
        con.raw.execute("INSERT INTO stored_files (path, data, saved_at) VALUES (%s, %s, %s) "
                        "ON CONFLICT (path) DO UPDATE SET data = EXCLUDED.data, saved_at = EXCLUDED.saved_at",
                        (path, data, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
        con.commit()
        con.close()


def delete_file(path):
    if os.path.isfile(path):
        os.remove(path)
    if DATABASE_URL:
        con = connect()
        con.raw.execute(_FILES_TABLE)
        con.raw.execute("DELETE FROM stored_files WHERE path = %s", (path,))
        con.commit()
        con.close()


def restore_files():
    """Put every stored file back on disk. Returns how many were written."""
    if not DATABASE_URL:
        return 0
    con = connect()
    con.raw.execute(_FILES_TABLE)
    con.commit()
    found = con.raw.execute("SELECT path, data FROM stored_files").fetchall()
    con.close()
    written = 0
    for path, data in found:
        path = os.path.normpath(path)
        if path.startswith("..") or os.path.isabs(path) or os.path.isfile(path):
            continue                             # never write outside the site's folder
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as f:
            f.write(bytes(data))
        written += 1
    return written
