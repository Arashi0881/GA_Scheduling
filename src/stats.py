"""Statistics for comparing stochastic solvers over many seeds (standard library only)."""
import math
from collections import Counter


def wilson_interval(successes, n, z=1.96):
    """95% Wilson score interval for a success rate; stays sensible at 0% and 100%."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def quantile(values, q):
    """Linear-interpolation quantile (numpy's default). `inf` marks a censored value."""
    data = sorted(values)
    if not data:
        return math.nan
    position = q * (len(data) - 1)
    low = math.floor(position)
    high = min(low + 1, len(data) - 1)
    weight = position - low
    if weight == 0 or data[low] == data[high]:
        return data[low]
    if math.isinf(data[high]):
        return math.inf
    return data[low] + weight * (data[high] - data[low])


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def mann_whitney(x, y):
    """Two-sided Mann–Whitney U test: returns (U of x, p-value).

    Normal approximation with tie and continuity correction, as in
    scipy.stats.mannwhitneyu(method="asymptotic"). Adequate for 10+ runs each.
    Infinite values (runs that never reached a target) rank last together.
    """
    n1, n2 = len(x), len(y)
    combined = list(x) + list(y)
    ranks = _ranks(combined)
    u = sum(ranks[:n1]) - n1 * (n1 + 1) / 2
    n = n1 + n2
    ties = sum(t ** 3 - t for t in Counter(combined).values())
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if variance <= 0:
        return u, 1.0
    z = (abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(variance)
    return u, min(1.0, math.erfc(max(z, 0) / math.sqrt(2)))


def prob_better(x, y):
    """Probability that a random value of x is lower (better) than one of y; ties count ½.

    This is the Vargha–Delaney A effect size for minimisation: 0.5 means no difference.
    """
    wins = sum((a < b) + 0.5 * (a == b) for a in x for b in y)
    return wins / (len(x) * len(y))


def fisher_exact(a, n1, b, n2):
    """Two-sided Fisher exact test for success rates a/n1 versus b/n2."""
    total, successes = n1 + n2, a + b

    def probability(k):
        return math.comb(n1, k) * math.comb(n2, successes - k) / math.comb(total, successes)

    observed = probability(a)
    ks = range(max(0, successes - n2), min(n1, successes) + 1)
    return min(1.0, sum(p for p in map(probability, ks) if p <= observed * (1 + 1e-7)))
