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
