import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    digest_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS digest_history (
    week_start TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER NOT NULL,
    preference TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_question_history (
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    asked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_query (
    thread_id INTEGER PRIMARY KEY,
    question TEXT NOT NULL,
    sql TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_context (
    thread_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    sql TEXT,
    answer TEXT NOT NULL,
    turn_order INTEGER NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
