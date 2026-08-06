import sqlite3
from analystbot.storage import db, digest_history, schema_cache, config_store, user_memory, threads


def _conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_digest_history_round_trip():
    conn = _conn()
    assert digest_history.load_last_digest(conn) is None
    digest_history.save_digest(conn, {"tutorial_step_3": (780, 1000)}, "2026-08-03")
    last = digest_history.load_last_digest(conn)
    assert last["week_start"] == "2026-08-03"
    assert last["metrics"]["tutorial_step_3"] == (780, 1000)


def test_schema_cache_round_trip():
    conn = _conn()
    assert schema_cache.load_schema(conn) is None
    schema_cache.save_schema(
        conn,
        {"events": {"level_start": ["level_number"]}, "date_range": ("20180101", "20180419"), "player_count": 500},
    )
    loaded = schema_cache.load_schema(conn)
    assert loaded["player_count"] == 500
    assert loaded["events"]["level_start"] == ["level_number"]


def test_config_store_digest_channel_round_trip():
    conn = _conn()
    assert config_store.get_digest_channel(conn) is None
    config_store.set_digest_channel(conn, 12345)
    assert config_store.get_digest_channel(conn) == 12345
    config_store.set_digest_channel(conn, 999)
    assert config_store.get_digest_channel(conn) == 999


def test_user_memory_preferences_and_history():
    conn = _conn()
    user_memory.add_preference(conn, 1, "always show D7 not D1")
    assert user_memory.get_preferences(conn, 1) == ["always show D7 not D1"]
    user_memory.add_question_history(conn, 1, "what is D1", "38%")
    history = user_memory.get_recent_history(conn, 1, limit=5)
    assert history[0]["question"] == "what is D1"
    assert history[0]["answer"] == "38%"


def test_thread_context_round_trip():
    conn = _conn()
    assert threads.get_thread_context(conn, 999) == []
    threads.save_thread_context(conn, 999, "where do players quit", "SELECT 1", "tutorial step 3 loses 22%")
    threads.save_thread_context(conn, 999, "what about level 5", "SELECT 2", "level 5 loses 31%")
    ctx = threads.get_thread_context(conn, 999)
    assert len(ctx) == 2
    assert ctx[0]["question"] == "where do players quit"
    assert ctx[1]["question"] == "what about level 5"
