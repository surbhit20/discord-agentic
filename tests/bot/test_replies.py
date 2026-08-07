from analystbot.bot.replies import format_refusal, format_clarify, format_caution, format_cost_warning


def test_format_refusal_includes_missing_reason():
    assert "session end" in format_refusal("you don't log session end")


def test_format_clarify_passes_message_through():
    assert format_clarify("did you mean X or Y?") == "did you mean X or Y?"


def test_format_caution_appends_reason_after_answer():
    result = format_caution("38%", "unsure which param")
    assert result.startswith("38%")
    assert "unsure which param" in result


def test_format_cost_warning_converts_bytes_to_gb_and_asks_to_confirm():
    msg = format_cost_warning(2 * 1024 ** 3, threshold_bytes=1024 ** 3, price_per_tib_usd=6.25)
    assert "2.00 GB" in msg
    assert "confirm" in msg


def test_format_cost_warning_includes_estimated_dollar_cost():
    # 2 GiB at $6.25/TiB = 2/1024 TiB * 6.25 ≈ $0.0122
    msg = format_cost_warning(2 * 1024 ** 3, threshold_bytes=1024 ** 3, price_per_tib_usd=6.25)
    assert "$0.0122" in msg


def test_format_cost_warning_includes_multiple_of_threshold():
    msg = format_cost_warning(2 * 1024 ** 3, threshold_bytes=1024 ** 3, price_per_tib_usd=6.25)
    assert "2.0x" in msg


def test_format_cost_warning_mentions_the_free_tier():
    msg = format_cost_warning(2 * 1024 ** 3, threshold_bytes=1024 ** 3, price_per_tib_usd=6.25)
    assert "free" in msg.lower()
