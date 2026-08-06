import sqlite3


def save_thread_context(conn: sqlite3.Connection, thread_id: int, question: str, sql: str | None, answer: str) -> None:
    next_order = conn.execute(
        "SELECT COALESCE(MAX(turn_order), -1) + 1 FROM thread_context WHERE thread_id = ?", (thread_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO thread_context (thread_id, question, sql, answer, turn_order) VALUES (?, ?, ?, ?, ?)",
        (thread_id, question, sql, answer, next_order),
    )
    conn.commit()


def get_thread_context(conn: sqlite3.Connection, thread_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT question, sql, answer FROM thread_context WHERE thread_id = ? ORDER BY turn_order",
        (thread_id,),
    ).fetchall()
    return [{"question": r[0], "sql": r[1], "answer": r[2]} for r in rows]


# A thread holds at most one query awaiting a `confirm` reply: the SQL whose dry-run
# estimate came in over the cost threshold. It is cleared the moment the thread does
# anything else, so a stale slot can never be executed by a later, unrelated "confirm".


def save_pending_query(conn: sqlite3.Connection, thread_id: int, question: str, sql: str) -> None:
    conn.execute(
        "INSERT INTO pending_query (thread_id, question, sql) VALUES (?, ?, ?) "
        "ON CONFLICT(thread_id) DO UPDATE SET question = excluded.question, sql = excluded.sql",
        (thread_id, question, sql),
    )
    conn.commit()


def get_pending_query(conn: sqlite3.Connection, thread_id: int) -> dict | None:
    row = conn.execute(
        "SELECT question, sql FROM pending_query WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    return None if row is None else {"question": row[0], "sql": row[1]}


def clear_pending_query(conn: sqlite3.Connection, thread_id: int) -> None:
    conn.execute("DELETE FROM pending_query WHERE thread_id = ?", (thread_id,))
    conn.commit()
