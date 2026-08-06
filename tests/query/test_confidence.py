from analystbot.query.confidence import score_risk, needs_caution, ConfidenceResult


def test_simple_query_is_not_risky():
    assert score_risk("SELECT COUNT(*) FROM events") is False


def test_multi_join_window_query_is_risky():
    sql = (
        "SELECT a.x, ROW_NUMBER() OVER (PARTITION BY a.x) FROM a "
        "JOIN b ON a.id = b.id JOIN c ON b.id = c.id"
    )
    assert score_risk(sql) is True


def test_needs_caution_when_risky_even_if_confident():
    assert needs_caution(ConfidenceResult(confident=True), risky=True) is True


def test_needs_caution_when_low_confidence_even_if_safe():
    assert needs_caution(ConfidenceResult(confident=False, reason="unsure which param"), risky=False) is True


def test_no_caution_when_confident_and_safe():
    assert needs_caution(ConfidenceResult(confident=True), risky=False) is False
