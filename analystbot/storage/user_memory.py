import sqlite3
from datetime import datetime, timezone


def add_preference(conn: sqlite3.Connection, user_id: int, preference: str) -> None:
    conn.execute("INSERT INTO user_preferences (user_id, preference) VALUES (?, ?)", (user_id, preference))
    conn.commit()


def get_preferences(conn: sqlite3.Connection, user_id: int) -> list[str]:
    rows = conn.execute("SELECT preference FROM user_preferences WHERE user_id = ?", (user_id,)).fetchall()
    return [r[0] for r in rows]


def add_question_history(conn: sqlite3.Connection, user_id: int, question: str, answer: str) -> None:
    conn.execute(
        "INSERT INTO user_question_history (user_id, question, answer, asked_at) VALUES (?, ?, ?, ?)",
        (user_id, question, answer, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_recent_history(conn: sqlite3.Connection, user_id: int, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        "SELECT question, answer, asked_at FROM user_question_history "
        "WHERE user_id = ? ORDER BY asked_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [{"question": r[0], "answer": r[1], "asked_at": r[2]} for r in rows]
