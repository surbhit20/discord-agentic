from analystbot.digest.significance import is_significant


def test_large_gap_large_sample_is_significant():
    assert is_significant(count_a=3600, n_a=10000, count_b=4000, n_b=10000) is True


def test_small_gap_small_sample_is_not_significant():
    assert is_significant(count_a=6, n_a=20, count_b=8, n_b=20) is False


def test_zero_sample_is_not_significant():
    assert is_significant(count_a=0, n_a=0, count_b=5, n_b=20) is False


def test_identical_rates_are_not_significant():
    assert is_significant(count_a=500, n_a=1000, count_b=500, n_b=1000) is False
