"""Paired-difference statistics and the pre-registered decision rule."""

from __future__ import annotations

import math

from .schemas import Analysis, DecisionRule, PairResult

# Two-sided 95% t critical values (0.975 quantile) for df = 1..30.
_T975 = [
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
]


def t_crit_975(df: int) -> float:
    if df < 1:
        raise ValueError("df must be >= 1")
    if df <= 30:
        return _T975[df - 1]
    z = 1.959963984540054  # Cornish-Fisher expansion, accurate to ~1e-3 for df > 30
    return z + (z**3 + z) / (4 * df) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)


def analyze(pairs: list[PairResult], metric: str, rule: DecisionRule) -> Analysis:
    d = [p.difference for p in pairs]
    n = len(d)
    if n < 2:
        raise ValueError("at least two pairs are required")
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    half = t_crit_975(n - 1) * sd / math.sqrt(n)
    lo, hi = mean - half, mean + half
    max_abs = max(abs(x) for x in d)

    if rule.kind == "paired_null":
        if max_abs <= rule.tolerance:
            outcome, why = "supported", (
                f"all {n} paired differences are within tolerance {rule.tolerance:g} "
                f"(max |d| = {max_abs:.3g}); the sham changed nothing")
        else:
            outcome, why = "contradicted", (
                f"max |d| = {max_abs:.6g} exceeds tolerance {rule.tolerance:g}; the sham changed the outcome")
    else:  # paired_mean_reduction: d = baseline - intervention, positive means less waiting
        m = rule.min_effect
        if mean >= m and lo > 0:
            outcome, why = "supported", (
                f"mean reduction {mean:.4f} >= min_effect {m:g} and 95% CI [{lo:.4f}, {hi:.4f}] excludes 0")
        elif hi < m:
            outcome, why = "contradicted", (
                f"95% CI upper bound {hi:.4f} < min_effect {m:g}: no practically meaningful reduction")
        else:
            outcome, why = "inconclusive", (
                f"95% CI [{lo:.4f}, {hi:.4f}] is compatible with both a meaningful reduction "
                f"(>= {m:g}) and none; collect more pairs under a new plan")

    return Analysis(
        metric=metric,
        n_pairs=n,
        mean_difference=mean,
        sd_difference=sd,
        ci_low=lo,
        ci_high=hi,
        min_difference=min(d),
        max_difference=max(d),
        max_abs_difference=max_abs,
        decision_kind=rule.kind,
        outcome=outcome,
        rationale=why,
    )
