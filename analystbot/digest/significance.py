import math

# Column-name hints used to read a (count, total) pair out of a result row. Kept
# deliberately small and structural: this is a pragmatic reader for the common
# two-group comparison shape ("before/after", "control/variant"), not a
# general-purpose query-intent classifier.
_TOTAL_HINTS = ("total", "denominator", "sample", "cohort", "base", "eligible", "n_all")
_BOOLISH = (bool,)


def is_significant(count_a: int, n_a: int, count_b: int, n_b: int, z_threshold: float = 1.96) -> bool:
    if n_a == 0 or n_b == 0:
        return False
    p_a = count_a / n_a
    p_b = count_b / n_b
    p_pool = (count_a + count_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return False
    z = abs(p_a - p_b) / se
    return z >= z_threshold


def _row_count_total(row: dict) -> tuple[int, int] | None:
    """Read a (count, total) pair out of one result row, or None if it isn't that shape.

    A row qualifies only when it carries exactly two non-negative integer columns AND one
    of them is named like an actual denominator ("total", "sample", ...). There is no
    fallback that guesses count/total from relative magnitude alone — two arbitrary int
    columns (e.g. a `level_number`/`day` label next to an unrelated count) are NOT a
    count/total pair just because one happens to be smaller, and treating them as one
    would fabricate a statistic about numbers that were never a rate. Rows with a count
    above the total are also rejected — that's not a rate either.
    """
    ints = [
        (key, value)
        for key, value in row.items()
        if isinstance(value, int) and not isinstance(value, _BOOLISH) and value >= 0
    ]
    if len(ints) != 2:
        return None

    total_key = next((k for k, _ in ints if any(hint in k.lower() for hint in _TOTAL_HINTS)), None)
    if total_key is None:
        return None
    total = next(v for k, v in ints if k == total_key)
    count = next(v for k, v in ints if k != total_key)

    if total == 0 or count > total:
        return None
    return count, total


def _row_label(row: dict, fallback: str) -> str:
    label = next((v for v in row.values() if isinstance(v, str) and v.strip()), None)
    return label.strip() if label else fallback


def significance_note(rows: list[dict]) -> str | None:
    """Describe whether a two-group comparison in `rows` is statistically meaningful.

    Returns None unless the result looks like exactly two comparable groups, each with a
    readable (count, total) pair — the shape a before/after or A/B question produces.
    The returned sentence is handed to answer formatting so the reply states whether the
    gap means anything given sample size, rather than just quoting the raw difference.
    """
    if len(rows) != 2:
        return None
    pairs = [_row_count_total(row) for row in rows]
    if any(pair is None for pair in pairs):
        return None

    (count_a, n_a), (count_b, n_b) = pairs
    label_a = _row_label(rows[0], "group 1")
    label_b = _row_label(rows[1], "group 2")
    rate_a = count_a / n_a
    rate_b = count_b / n_b
    gap = abs(rate_a - rate_b)

    verdict = (
        "statistically significant at 95% confidence"
        if is_significant(count_a, n_a, count_b, n_b)
        else "NOT statistically significant at 95% confidence — it is within what sample noise "
        "alone could produce, so do not report it as a real change"
    )
    return (
        f"Comparison: {label_a} is {rate_a:.1%} ({count_a}/{n_a}), {label_b} is {rate_b:.1%} "
        f"({count_b}/{n_b}); the {gap:.1%} gap is {verdict}."
    )
