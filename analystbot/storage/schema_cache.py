import json
import sqlite3
from datetime import datetime, timezone


def save_schema(conn: sqlite3.Connection, schema: dict) -> None:
    conn.execute(
        "INSERT INTO schema_cache (id, schema_json, discovered_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET schema_json = excluded.schema_json, discovered_at = excluded.discovered_at",
        (json.dumps(schema), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def load_schema(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT schema_json FROM schema_cache WHERE id = 1").fetchone()
    return json.loads(row[0]) if row else None
