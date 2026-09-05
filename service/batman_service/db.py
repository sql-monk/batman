"""SQLite: одне з'єднання на потік, WAL, міграції з migrations/*.sql."""
from __future__ import annotations
import sqlite3
import threading
import time
from pathlib import Path
from .config import CFG

_local = threading.local()
_lock = threading.RLock()
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def now_ms() -> int:
    return int(time.time() * 1000)


def _path() -> Path:
    p = Path(CFG.db.path)
    if not p.is_absolute():
        p = CFG.base_dir / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(_path(), check_same_thread=False, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.conn = c
    return c


def migrate() -> None:
    with _lock:
        c = conn()
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        have = int(row["value"]) if row else 0
        for f in sorted(MIGRATIONS.glob("*.sql")):
            n = int(f.name.split("_")[0])
            if n > have:
                c.executescript(f.read_text(encoding="utf-8"))
                c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema',?)", (str(n),))
        c.commit()


def q(sql: str, args=()) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, args=()):
    return conn().execute(sql, args).fetchone()


def x(sql: str, args=()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


def xmany(sql: str, rows) -> None:
    with _lock:
        conn().executemany(sql, rows)
        conn().commit()
