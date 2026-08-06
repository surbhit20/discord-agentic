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


def test_worst_leak_is_the_lowest_completion_rate_among_genuine_funnel_pairs():
    conn = _conn()
    result = run_digest(
        conn,
        "2026-08-03",
        {
            "level_3_start": (1000, 5000), "level_3_complete": (780, 5000),
            "level_4_start": (1000, 5000), "level_4_complete": (690, 5000),
        },
    )
    # level_3 completion rate 780/1000 = 78%, level_4 is 690/1000 = 69% — level_4 is worse.
    assert "level_4" in result.summary
    assert "69%" in result.summary
    assert "worst leak" in result.summary


def test_worst_leak_ignores_rare_non_funnel_events():
    # Regression test: this used to rank "worst leak" by raw participation rate across
    # every tracked event, so a rare marketing/system event that almost nobody ever
    # triggers (not a funnel start/end pair at all) would win — caught during a live
    # end-to-end run where `dynamic_link_first_open` was reported as the "worst leak".
    conn = _conn()
    result = run_digest(
        conn,
        "2026-08-03",
        {
            "level_3_start": (1000, 5000), "level_3_complete": (900, 5000),
            "dynamic_link_first_open": (1, 5000),
        },
    )
    assert "dynamic_link_first_open" not in result.summary
    assert "level_3" in result.summary


def test_no_worst_leak_line_when_no_genuine_funnel_pairs_exist():
    conn = _conn()
    result = run_digest(conn, "2026-08-03", {"screen_view": (900, 1000), "ad_reward": (10, 1000)})
    assert "worst leak" not in result.summary


def test_run_digest_persists_current_metrics_for_next_comparison():
    conn = _conn()
    run_digest(conn, "2026-08-03", {"tutorial_step_3": (780, 1000)})
    last = digest_history.load_last_digest(conn)
    assert last["week_start"] == "2026-08-03"
    assert last["metrics"]["tutorial_step_3"] == (780, 1000)
