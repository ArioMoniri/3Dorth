"""Article-quality statistics + Fig 3/4/5 plots (synthetic, KNOWN answers)."""
import math

import numpy as np
import pandas as pd
import pytest

from core.stats import (
    Summary,
    correlation,
    fig3_column_line,
    fig4_boxplots,
    fig5_regression_scatter,
    group_summary,
    is_inferential_valid,
    linear_regression,
    nonlinear_regression,
    one_way_anova,
    paired_test,
    posthoc_tukey,
    summarize,
)


def test_summarize_known_values():
    s = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert isinstance(s, Summary)
    assert s.n == 5
    assert abs(s.mean - 3.0) < 1e-9
    assert abs(s.median - 3.0) < 1e-9
    # sample SD of 1..5 = sqrt(2.5)
    assert abs(s.sd - math.sqrt(2.5)) < 1e-9
    # rms = sqrt(mean of squares) = sqrt(55/5) = sqrt(11)
    assert abs(s.rms - math.sqrt(11.0)) < 1e-9
    assert s.min == 1.0 and s.max == 5.0


def test_summarize_ci_brackets_true_mean():
    rng = np.random.default_rng(42)
    true_mean = 10.0
    data = rng.normal(true_mean, 1.0, size=200)
    s = summarize(data)
    assert s.ci95_low < true_mean < s.ci95_high
    assert s.ci95_low < s.mean < s.ci95_high


def test_summarize_single_value_ci_nan():
    s = summarize([7.0])
    assert s.n == 1
    assert s.mean == 7.0
    assert math.isnan(s.ci95_low) and math.isnan(s.ci95_high)


def test_group_summary_returns_table():
    groups = {"A": [1.0, 2.0, 3.0], "B": [10.0, 11.0, 12.0]}
    per_group, table = group_summary(groups)
    assert set(per_group.keys()) == {"A", "B"}
    assert isinstance(per_group["A"], Summary)
    assert isinstance(table, pd.DataFrame)
    assert len(table) == 2
    assert "mean" in table.columns and "group" in table.columns


def test_anova_three_different_groups():
    rng = np.random.default_rng(0)
    groups = {
        "g1": rng.normal(0.0, 1.0, 30),
        "g2": rng.normal(5.0, 1.0, 30),
        "g3": rng.normal(10.0, 1.0, 30),
    }
    res = one_way_anova(groups)
    assert res["p"] < 0.001
    assert res["F"] > 10.0


def test_anova_identical_groups_high_p():
    rng = np.random.default_rng(1)
    base = rng.normal(0.0, 1.0, 50)
    groups = {"a": base.copy(), "b": base.copy(), "c": base.copy()}
    res = one_way_anova(groups)
    assert res["p"] > 0.05


def test_posthoc_tukey_separates_groups():
    rng = np.random.default_rng(2)
    groups = {
        "low": rng.normal(0.0, 1.0, 25),
        "high": rng.normal(20.0, 1.0, 25),
    }
    tk = posthoc_tukey(groups)
    assert isinstance(tk, pd.DataFrame)
    assert bool(tk["reject"].iloc[0]) is True


def test_paired_test_t_and_wilcoxon():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = a + 3.0  # consistent shift
    rt = paired_test(a, b, method="t")
    assert rt["p"] < 0.001
    rw = paired_test(a, b, method="wilcoxon")
    assert "p" in rw and rw["p"] < 0.1


def test_correlation_pearson_and_spearman():
    x = np.arange(1.0, 21.0)
    y = 2.0 * x + 1.0
    rp = correlation(x, y, method="pearson")
    assert abs(rp["r"] - 1.0) < 1e-9
    assert rp["p"] < 1e-6
    rs = correlation(x, y, method="spearman")
    assert abs(rs["r"] - 1.0) < 1e-9


def test_linear_regression_recovers_slope():
    x = np.linspace(0.0, 10.0, 50)
    y = 3.5 * x - 2.0  # noiseless
    res = linear_regression(x, y)
    assert abs(res["slope"] - 3.5) < 1e-6
    assert abs(res["intercept"] - (-2.0)) < 1e-6
    assert abs(res["r2"] - 1.0) < 1e-9
    assert "equation_str" in res and "y" in res["equation_str"]


def test_nonlinear_regression_quadratic():
    x = np.linspace(-5.0, 5.0, 60)
    y = 2.0 * x**2 - 3.0 * x + 1.0
    res = nonlinear_regression(x, y, degree=2)
    assert abs(res["r2"] - 1.0) < 1e-9
    # highest-degree coeff first
    assert abs(res["coeffs"][0] - 2.0) < 1e-4
    assert "equation_str" in res


def test_is_inferential_valid():
    assert is_inferential_valid(3) is True
    assert is_inferential_valid(2) is False
    assert is_inferential_valid(1, min_n=3) is False
    assert is_inferential_valid(5, min_n=5) is True


def test_fig3_writes_png(tmp_path):
    rng = np.random.default_rng(3)
    groups = {
        "Anterior": rng.normal(2.0, 0.3, 20),
        "Medial": rng.normal(3.0, 0.4, 20),
        "Posterior": rng.normal(4.0, 0.5, 20),
    }
    out = fig3_column_line(groups, tmp_path / "fig3.png")
    assert out.exists() and out.stat().st_size > 5000


def test_fig4_writes_png(tmp_path):
    rng = np.random.default_rng(4)
    groups = {
        "A": rng.normal(2.0, 0.5, 30),
        "B": rng.normal(3.5, 0.6, 30),
    }
    out = fig4_boxplots(groups, tmp_path / "fig4.png")
    assert out.exists() and out.stat().st_size > 5000


def test_fig5_writes_png(tmp_path):
    x = np.linspace(0.0, 10.0, 40)
    y = 1.5 * x + 0.5 + np.random.default_rng(5).normal(0, 0.2, 40)
    fit = linear_regression(x, y)
    out = fig5_regression_scatter(x, y, fit, tmp_path / "fig5.png")
    assert out.exists() and out.stat().st_size > 5000


def test_empty_input_raises():
    with pytest.raises(ValueError):
        summarize([])
