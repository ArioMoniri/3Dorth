"""Article-quality descriptive + inferential statistics.

Framework-agnostic: every function returns plain data (pydantic models, dicts,
pandas DataFrames). No UI, no plotting here (see plots.py).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel
from scipy import stats


def _as_array(values) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("empty input: need at least one finite value")
    return arr


class Summary(BaseModel):
    """Descriptive summary with a t-based 95% confidence interval on the mean."""

    n: int
    mean: float
    median: float
    sd: float
    rms: float
    min: float
    max: float
    ci95_low: float
    ci95_high: float


def summarize(values) -> Summary:
    """Descriptive statistics with a t-based 95% CI on the mean.

    SD is the sample (ddof=1) standard deviation. RMS is the quadratic mean.
    With n < 2 the CI is undefined and returned as NaN.
    """
    arr = _as_array(values)
    n = int(arr.size)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    rms = float(np.sqrt(np.mean(arr**2)))
    if n > 1:
        sem = sd / np.sqrt(n)
        tcrit = float(stats.t.ppf(0.975, df=n - 1))
        lo, hi = mean - tcrit * sem, mean + tcrit * sem
    else:
        lo = hi = float("nan")
    return Summary(
        n=n,
        mean=mean,
        median=float(np.median(arr)),
        sd=sd,
        rms=rms,
        min=float(np.min(arr)),
        max=float(np.max(arr)),
        ci95_low=lo,
        ci95_high=hi,
    )


def group_summary(groups: dict) -> tuple[dict, "object"]:
    """Per-group Summary plus a Table-1-style pandas DataFrame.

    Returns ``(per_group, table)`` where per_group maps name -> Summary and
    table has one row per group with the descriptive columns.
    """
    import pandas as pd

    per_group: dict = {}
    rows = []
    for name, vals in groups.items():
        s = summarize(vals)
        per_group[name] = s
        row = {"group": name, **s.model_dump()}
        rows.append(row)
    table = pd.DataFrame(rows, columns=["group", "n", "mean", "sd", "median",
                                        "rms", "min", "max",
                                        "ci95_low", "ci95_high"])
    return per_group, table


def one_way_anova(groups: dict) -> dict:
    """One-way ANOVA across >= 2 groups. Returns {'F', 'p'}."""
    arrays = [_as_array(v) for v in groups.values()]
    if len(arrays) < 2:
        raise ValueError("one_way_anova needs at least 2 groups")
    f, p = stats.f_oneway(*arrays)
    return {"F": float(f), "p": float(p)}


def posthoc_tukey(groups: dict) -> "object":
    """Tukey HSD post-hoc test (statsmodels). Returns a tidy DataFrame."""
    import pandas as pd
    from statsmodels.stats.multicomp import pairwise_tukeyhsd

    values, labels = [], []
    for name, vals in groups.items():
        arr = _as_array(vals)
        values.append(arr)
        labels.extend([name] * arr.size)
    data = np.concatenate(values)
    res = pairwise_tukeyhsd(data, labels)
    # res._results_table.data: header + rows
    tbl = res._results_table.data
    df = pd.DataFrame(tbl[1:], columns=tbl[0])
    df["reject"] = df["reject"].astype(bool)
    return df


def posthoc_snk(groups: dict, alpha: float = 0.05) -> "object":
    """Student-Newman-Keuls-style pairwise comparison.

    A pragmatic SNK: rank group means, compare each pair with the studentised
    range statistic across the number of means spanned. Returns a DataFrame with
    columns group1, group2, meandiff, q, reject.
    """
    import pandas as pd

    names = list(groups.keys())
    arrays = {n: _as_array(groups[n]) for n in names}
    means = {n: float(np.mean(arrays[n])) for n in names}
    ns = {n: arrays[n].size for n in names}
    # pooled within-group variance (MSE) and residual df
    k = len(names)
    grand_n = sum(ns.values())
    df_within = grand_n - k
    ss_within = sum(
        float(np.sum((arrays[n] - means[n]) ** 2)) for n in names
    )
    mse = ss_within / df_within if df_within > 0 else float("nan")
    order = sorted(names, key=lambda n: means[n])
    rank = {n: i for i, n in enumerate(order)}
    rows = []
    for i, g1 in enumerate(names):
        for g2 in names[i + 1 :]:
            span = abs(rank[g1] - rank[g2]) + 1
            se = np.sqrt(mse * 0.5 * (1.0 / ns[g1] + 1.0 / ns[g2]))
            diff = means[g1] - means[g2]
            q = float(abs(diff) / se) if se > 0 else float("inf")
            qcrit = float(stats.studentized_range.ppf(1 - alpha, span, df_within))
            rows.append({
                "group1": g1,
                "group2": g2,
                "meandiff": float(means[g2] - means[g1]),
                "q": q,
                "q_crit": qcrit,
                "reject": bool(q > qcrit),
            })
    return pd.DataFrame(rows)


def paired_test(a, b, method: str = "t") -> dict:
    """Paired difference test. method 't' (paired t) or 'wilcoxon'.

    Returns {'stat', 'p', 'method', 'n'}.
    """
    x = np.asarray(a, dtype=np.float64).ravel()
    y = np.asarray(b, dtype=np.float64).ravel()
    if x.shape != y.shape:
        raise ValueError("paired_test requires equal-length inputs")
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < 2:
        raise ValueError("paired_test needs at least 2 paired observations")
    if method == "t":
        stat, p = stats.ttest_rel(x, y)
    elif method == "wilcoxon":
        stat, p = stats.wilcoxon(x, y)
    else:
        raise ValueError(f"unknown method: {method!r}")
    return {"stat": float(stat), "p": float(p), "method": method, "n": int(x.size)}


def correlation(x, y, method: str = "pearson") -> dict:
    """Correlation coefficient and p-value. method 'pearson' or 'spearman'."""
    xa = np.asarray(x, dtype=np.float64).ravel()
    ya = np.asarray(y, dtype=np.float64).ravel()
    if xa.shape != ya.shape:
        raise ValueError("correlation requires equal-length inputs")
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    if method == "pearson":
        r, p = stats.pearsonr(xa, ya)
    elif method == "spearman":
        r, p = stats.spearmanr(xa, ya)
    else:
        raise ValueError(f"unknown method: {method!r}")
    return {"r": float(r), "p": float(p), "method": method, "n": int(xa.size)}


def _clean_xy(x, y) -> tuple[np.ndarray, np.ndarray]:
    xa = np.asarray(x, dtype=np.float64).ravel()
    ya = np.asarray(y, dtype=np.float64).ravel()
    if xa.shape != ya.shape:
        raise ValueError("x and y must have equal length")
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    if xa.size < 2:
        raise ValueError("need at least 2 points for regression")
    return xa, ya


def linear_regression(x, y) -> dict:
    """Ordinary least-squares linear fit.

    Returns {slope, intercept, r, r2, p, stderr, equation_str}.
    """
    xa, ya = _clean_xy(x, y)
    res = stats.linregress(xa, ya)
    slope = float(res.slope)
    intercept = float(res.intercept)
    r = float(res.rvalue)
    sign = "+" if intercept >= 0 else "-"
    eq = f"y = {slope:.4g}x {sign} {abs(intercept):.4g}"
    return {
        "slope": slope,
        "intercept": intercept,
        "r": r,
        "r2": r * r,
        "p": float(res.pvalue),
        "stderr": float(res.stderr),
        "equation_str": eq,
    }


def nonlinear_regression(x, y, degree: int = 2) -> dict:
    """Polynomial least-squares fit of the given degree.

    Returns {coeffs (highest-degree first), r2, equation_str, degree}.
    """
    xa, ya = _clean_xy(x, y)
    if degree < 1:
        raise ValueError("degree must be >= 1")
    coeffs = np.polyfit(xa, ya, degree)
    pred = np.polyval(coeffs, xa)
    ss_res = float(np.sum((ya - pred) ** 2))
    ss_tot = float(np.sum((ya - np.mean(ya)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    terms = []
    d = degree
    for c in coeffs:
        if d > 1:
            terms.append(f"{c:.4g}x^{d}")
        elif d == 1:
            terms.append(f"{c:.4g}x")
        else:
            terms.append(f"{c:.4g}")
        d -= 1
    eq = "y = " + " + ".join(terms)
    return {
        "coeffs": [float(c) for c in coeffs],
        "r2": float(r2),
        "equation_str": eq,
        "degree": int(degree),
    }


def is_inferential_valid(n_per_group: int, min_n: int = 3) -> bool:
    """Guard against single-subject over-claiming.

    Inferential statistics are only meaningful with enough replicates per group.
    """
    return int(n_per_group) >= int(min_n)
