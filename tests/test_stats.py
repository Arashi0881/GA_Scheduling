import math

import pytest

from src.stats import mann_whitney, prob_better, quantile, wilson_interval


def test_wilson_matches_known_values():
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)
    low, high = wilson_interval(10, 10)
    assert low == pytest.approx(0.7225, abs=1e-4) and high == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_quantile_interpolates_and_handles_infinity():
    values = [1, 2, 3, 4]
    assert quantile(values, 0.5) == 2.5
    assert quantile(values, 0.25) == 1.75
    assert quantile([5], 0.75) == 5
    assert quantile([1, 2, math.inf], 0.5) == 2
    assert quantile([1, math.inf, math.inf], 0.5) == math.inf
    assert quantile([1, 2, math.inf], 0.25) == 1.5


def test_mann_whitney_separated_samples():
    u, p = mann_whitney(list(range(10)), list(range(10, 20)))
    assert u == 0
    # Normal approximation with continuity correction: z = 49.5 / sqrt(175).
    assert p == pytest.approx(math.erfc(49.5 / math.sqrt(175) / math.sqrt(2)), rel=1e-9)


def test_mann_whitney_identical_samples_and_infinite_values():
    assert mann_whitney([3, 3, 3], [3, 3, 3]) == (4.5, 1.0)
    u, p = mann_whitney([1, 2, 3], [math.inf, math.inf, math.inf])
    assert u == 0 and p < 0.1


def test_prob_better_counts_ties_half():
    assert prob_better([1, 2], [3, 4]) == 1.0
    assert prob_better([3, 4], [1, 2]) == 0.0
    assert prob_better([1, 3], [1, 3]) == 0.5
