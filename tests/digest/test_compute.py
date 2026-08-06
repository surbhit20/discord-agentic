import sqlite3
from analystbot.storage import db, digest_history
from analystbot.digest.compute import run_digest


def _conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_first_run_with_no_history_reports_no_movement():
    conn = _conn()
    result = run_digest(conn, "2026-08-03", {"tutorial_step_3": (780, 1000), "level_4_start": (690, 1000)})
    assert "nothing moved significantly" in result.summary
    assert result.metrics["tutorial_step_3"] == 0.78


def test_second_run_flags_significant_movement():
    conn = _conn()
    digest_history.save_digest(conn, {"tutorial_step_3": (3600, 10000)}, "2026-07-27")
    result = run_digest(conn, "2026-08-03", {"tutorial_step_3": (4000, 10000)})
    assert "tutorial_step_3" in result.summary
    assert "significant" in result.summary


def test_worst_leak_is_the_lowest_completion_rate():
    conn = _conn()
    result = run_digest(
        conn, "2026-08-03", {"tutorial_step_3": (780, 1000), "level_4_start": (690, 1000)}
    )
    assert "level_4_start" in result.summary


def test_run_digest_persists_current_metrics_for_next_comparison():
    conn = _conn()
    run_digest(conn, "2026-08-03", {"tutorial_step_3": (780, 1000)})
    last = digest_history.load_last_digest(conn)
    assert last["week_start"] == "2026-08-03"
    assert last["metrics"]["tutorial_step_3"] == (780, 1000)
