import json
import sqlite3


def save_digest(conn: sqlite3.Connection, metrics: dict[str, tuple[int, int]], week_start: str) -> None:
    conn.execute(
        "INSERT INTO digest_history (week_start, metrics_json) VALUES (?, ?) "
        "ON CONFLICT(week_start) DO UPDATE SET metrics_json = excluded.metrics_json",
        (week_start, json.dumps(metrics)),
    )
    conn.commit()


def load_last_digest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT week_start, metrics_json FROM digest_history ORDER BY week_start DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    week_start, metrics_json = row
    metrics = {k: tuple(v) for k, v in json.loads(metrics_json).items()}
    return {"week_start": week_start, "metrics": metrics}
