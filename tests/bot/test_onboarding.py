from analystbot.bot.onboarding import build_onboarding_report


def test_report_includes_event_count_date_range_and_player_count():
    schema = {
        "events": {"level_start": ["level_number"], "session_start": []},
        "date_range": ("20180101", "20180419"),
        "player_count": 5000,
    }
    report = build_onboarding_report(schema)
    assert "2 event types" in report
    assert "level_start" in report
    assert "session_start" in report
    assert "20180101" in report and "20180419" in report
    assert "5000 players" in report
    assert "confirm" in report
