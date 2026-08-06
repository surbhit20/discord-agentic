from analystbot.main import _confirm_locks_in_schema


def test_confirm_is_honored_once_schema_is_cached():
    assert _confirm_locks_in_schema("confirm", schema_cached=True) is True


def test_confirm_is_case_and_whitespace_insensitive_once_schema_is_cached():
    assert _confirm_locks_in_schema("  Confirm  ", schema_cached=True) is True


def test_confirm_is_ignored_before_a_schema_has_been_discovered():
    # A stray first message of "confirm" must not lock in the digest channel before
    # onboarding has ever run, or _deps() would be stuck on its empty-schema fallback.
    assert _confirm_locks_in_schema("confirm", schema_cached=False) is False


def test_non_confirm_message_is_never_treated_as_confirmation():
    assert _confirm_locks_in_schema("what happened this week?", schema_cached=True) is False
