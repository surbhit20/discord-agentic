import sqlite3


def set_digest_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    conn.execute(
        "INSERT INTO bot_config (id, digest_channel_id) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET digest_channel_id = excluded.digest_channel_id",
        (channel_id,),
    )
    conn.commit()


def clear_digest_channel(conn: sqlite3.Connection) -> None:
    """Un-set the digest channel so onboarding runs again and a fresh `confirm` is needed."""
    conn.execute("UPDATE bot_config SET digest_channel_id = NULL WHERE id = 1")
    conn.commit()


def get_digest_channel(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT digest_channel_id FROM bot_config WHERE id = 1").fetchone()
    return row[0] if row else None
