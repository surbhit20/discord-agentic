from analystbot.digest.significance import significance_note


def test_two_labelled_groups_with_a_real_gap_are_called_significant():
    note = significance_note(
        [
            {"cohort": "before", "retained": 3600, "total": 10000},
            {"cohort": "after", "retained": 4000, "total": 10000},
        ]
    )
    assert note is not None
    assert "before" in note and "after" in note
    assert "NOT statistically significant" not in note
    assert "statistically significant" in note


def test_small_sample_gap_is_called_out_as_noise():
    note = significance_note(
        [
            {"build": "old", "converted": 6, "total": 20},
            {"build": "new", "converted": 8, "total": 20},
        ]
    )
    assert note is not None
    assert "NOT statistically significant" in note


def test_unlabelled_two_group_rows_still_produce_a_note():
    note = significance_note([{"n": 3600, "total": 10000}, {"n": 4000, "total": 10000}])
    assert note is not None
    assert "group 1" in note and "group 2" in note


def test_single_row_result_is_not_a_comparison():
    assert significance_note([{"n": 4213}]) is None


def test_three_row_breakdown_is_not_a_two_group_comparison():
    rows = [{"level": "1", "n": 10, "total": 20}, {"level": "2", "n": 8, "total": 20}, {"level": "3", "n": 6, "total": 20}]
    assert significance_note(rows) is None


def test_rows_without_a_readable_count_and_total_are_skipped():
    assert significance_note([{"before": 0.38}, {"after": 0.31}]) is None
    assert significance_note([{"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}]) is None


def test_count_above_total_is_not_treated_as_a_rate():
    # Two ints where the "total"-named column is the smaller one: not a rate, so no claim.
    assert significance_note([{"hits": 50, "total": 10}, {"hits": 40, "total": 10}]) is None


def test_empty_result_is_not_a_comparison():
    assert significance_note([]) is None


def test_label_like_columns_are_not_mistaken_for_a_count_total_pair():
    # level_number is a label, not a denominator — treating (level_number, n) as
    # (total, count) by magnitude alone fabricates a rate out of unrelated numbers.
    rows = [{"level_number": 1, "n": 500}, {"level_number": 2, "n": 400}]
    assert significance_note(rows) is None


def test_day_and_retained_columns_are_not_mistaken_for_a_count_total_pair():
    # day is a label (day 1, day 7), not a denominator for `retained` — same fabrication
    # shape as level_number/n above, just with different column names.
    rows = [{"day": 1, "retained": 3600}, {"day": 7, "retained": 1200}]
    assert significance_note(rows) is None
