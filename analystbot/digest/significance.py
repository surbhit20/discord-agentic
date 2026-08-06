import math


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
