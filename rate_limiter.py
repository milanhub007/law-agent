import os
import sqlite3
import threading
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rate_limit.sqlite")

REAL_LIMITS = [
    (60, 5),        # 5 calls per minute
    (3600, 50),     # 50 calls per hour
    (86400, 125),   # 125 calls per day
]

# Parallel tool calls run in separate threads. The lock makes "check the count,
# then reserve a slot" one step, so several threads can't all slip through.
_lock = threading.Lock()


def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS calls (timestamp REAL NOT NULL)")
    return conn


def wait_if_needed(limits=REAL_LIMITS) -> None:
    """Blocks until a request is allowed, then records it immediately,
    before the request is sent."""
    with _lock:
        while True:
            conn = _get_connection()
            now = time.time()
            wait = 0
            for window, limit in limits:
                rows = conn.execute(
                    "SELECT timestamp FROM calls WHERE timestamp > ? ORDER BY timestamp",
                    (now - window,),
                ).fetchall()
                if len(rows) >= limit:
                    free_at = rows[len(rows) - limit][0] + window
                    if window > 3600:
                        conn.close()
                        raise RuntimeError(
                            f"Daily limit of {limit} CourtListener calls reached. "
                            f"Next slot in about {(free_at - now) / 3600:.1f} hours."
                        )
                    wait = max(wait, free_at - now + 1)

            if wait <= 0:
                conn.execute("INSERT INTO calls (timestamp) VALUES (?)", (now,))
                conn.commit()
                conn.close()
                return

            conn.close()
            print(f"  [rate limit reached, waiting {wait:.1f}s]")
            time.sleep(wait)


def record_call() -> None:
    """No longer needed: wait_if_needed() now records the call itself.
    Kept empty so existing calls to it don't break."""
    pass


if __name__ == "__main__":
    # 8 parallel calls against a fake limit of 3 per 10 seconds.
    from concurrent.futures import ThreadPoolExecutor
    test_limits = [(10, 3)]
    start = time.time()

    def fake_call(i):
        wait_if_needed(test_limits)
        print(f"call {i} allowed at +{time.time() - start:.1f}s")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fake_call, range(8)))