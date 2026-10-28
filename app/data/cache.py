"""Tiny SQLite key-value cache, so a company is fetched at most once a day (and AI output is reused)."""
import json
import sqlite3
import time

from app.config import DATA_DIR

DB_PATH = DATA_DIR / "cache" / "cache.sqlite"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, saved_at REAL)")
    return conn


def get(key: str, max_age_hours: float = 24):
    with _connect() as conn:
        row = conn.execute("SELECT value, saved_at FROM cache WHERE key = ?", (key,)).fetchone()
    if row and time.time() - row[1] < max_age_hours * 3600:
        return json.loads(row[0])
    return None


def put(key: str, value) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, json.dumps(value), time.time()))
