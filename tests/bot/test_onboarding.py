from analystbot.bot.onboarding import build_onboarding_report, find_schema_gaps


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


def test_report_tells_the_user_to_mention_the_bot_when_confirming():
    # NEW_QUESTION only fires on an @mention, so a bare "confirm" posted in the
    # channel would never reach the bot — the instruction has to say so.
    schema = {"events": {"level_start": []}, "date_range": ("20180101", "20180419"), "player_count": 5000}
    report = build_onboarding_report(schema)
    assert "mention" in report.lower()


def test_report_names_concrete_gaps():
    schema = {
        "events": {"level_start": ["level_number"], "session_start": []},
        "date_range": ("20180101", "20180419"),
        "player_count": 5000,
    }
    report = build_onboarding_report(schema)
    assert "Notable gaps:" in report
    assert "fail rates" in report


def test_start_event_without_a_completion_event_is_a_gap():
    gaps = find_schema_gaps({"level_start": [], "user_engagement": []})
    assert any("level_start" in gap and "completion" in gap for gap in gaps)


def test_start_event_with_a_completion_event_is_not_a_gap():
    gaps = find_schema_gaps({"level_start": [], "level_complete": [], "user_engagement": []})
    assert not any("level_start" in gap for gap in gaps)


def test_missing_session_close_is_reported_as_a_session_length_gap():
    gaps = find_schema_gaps({"session_start": [], "user_engagement": []})
    assert any("session length" in gap for gap in gaps)


def test_no_engagement_signal_at_all_is_a_gap():
    gaps = find_schema_gaps({"level_start": [], "level_complete": []})
    assert any("playtime" in gap for gap in gaps)


def test_schema_with_no_detectable_gaps_reports_none():
    events = {"level_start": [], "level_complete": [], "session_start": [], "session_end": [], "user_engagement": []}
    assert find_schema_gaps(events) == []
    report = build_onboarding_report(
        {"events": events, "date_range": ("20180101", "20180419"), "player_count": 10}
    )
    assert "Notable gaps:" not in report


def test_at_most_three_gaps_are_reported():
    events = {f"thing{i}_start": [] for i in range(10)}
    assert len(find_schema_gaps(events)) == 3
