"""Article-quality statistics + Fig 3/4/5 plots for cortical-bone mapping.

Descriptive summaries, ANOVA/post-hoc, paired tests, correlation and regression
return plain data (pydantic models, dicts, pandas DataFrames). Plot helpers save
crisp 300-DPI PNGs and return their paths. All framework-agnostic.
"""

from core.stats._core import (
    Summary,
    correlation,
    group_summary,
    is_inferential_valid,
    linear_regression,
    nonlinear_regression,
    one_way_anova,
    paired_test,
    posthoc_snk,
    posthoc_tukey,
    summarize,
)
from core.stats.plots import (
    fig3_column_line,
    fig4_boxplots,
    fig5_regression_scatter,
)

__all__ = [
    "Summary",
    "summarize",
    "group_summary",
    "one_way_anova",
    "posthoc_tukey",
    "posthoc_snk",
    "paired_test",
    "correlation",
    "linear_regression",
    "nonlinear_regression",
    "is_inferential_valid",
    "fig3_column_line",
    "fig4_boxplots",
    "fig5_regression_scatter",
]
