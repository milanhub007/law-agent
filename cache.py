import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "cl_cache.sqlite")


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    return conn


def get(key: str):
    conn = _get_connection()
    row = conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def set(key: str, value) -> None:
    conn = _get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)",
        (key, json.dumps(value)),
    )
    conn.commit()
    conn.close()