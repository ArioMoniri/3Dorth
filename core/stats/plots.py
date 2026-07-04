"""Article-style Fig 3/4/5 plots (matplotlib, 300 DPI, crisp non-overlapping fonts).

Each function saves a PNG and returns its Path. Framework-agnostic: no UI.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from core.stats._core import _as_array  # noqa: E402

# One clean, reused theme — matches core.viz look.
_THEME = {
    "font.family": "DejaVu Sans",
    "font.size": 12,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.6,
    "figure.dpi": 100,
}

# Muted, print-friendly palette.
_PALETTE = ["#3b6ea5", "#c0504d", "#4f9d69", "#8064a2", "#e8a33d", "#5a5a5a"]


def _colors(n: int) -> list[str]:
    return [_PALETTE[i % len(_PALETTE)] for i in range(n)]


def _save(fig, out_png: str | Path, dpi: int) -> Path:
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def fig3_column_line(
    groups: dict,
    out_png: str | Path,
    *,
    ylabel: str = "Cortical thickness (mm)",
    title: str = "",
    dpi: int = 300,
) -> Path:
    """Fig-3 style: mean +/- SD columns with a connecting trend line."""
    names = list(groups.keys())
    means = [float(np.mean(_as_array(v))) for v in groups.values()]
    arrs = [_as_array(v) for v in groups.values()]
    sds = [float(np.std(a, ddof=1)) if a.size > 1 else 0.0 for a in arrs]
    xpos = np.arange(len(names))
    cols = _colors(len(names))

    with plt.rc_context(_THEME):
        fig, ax = plt.subplots(figsize=(max(5, 1.4 * len(names)), 4.2))
        ax.bar(xpos, means, yerr=sds, capsize=5, width=0.6, color=cols,
               edgecolor="black", linewidth=0.7, alpha=0.9, zorder=2)
        ax.plot(xpos, means, "-o", color="#222222", linewidth=1.6,
                markersize=6, markerfacecolor="white", zorder=3)
        ax.set_xticks(xpos)
        ax.set_xticklabels(names, rotation=0)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)
        ax.set_axisbelow(True)
        ax.margins(x=0.08)
        return _save(fig, out_png, dpi)


def fig4_boxplots(
    groups: dict,
    out_png: str | Path,
    *,
    ylabel: str = "Cortical thickness (mm)",
    title: str = "",
    dpi: int = 300,
) -> Path:
    """Fig-4 style: box plots with overlaid jittered raw points."""
    names = list(groups.keys())
    data = [_as_array(v) for v in groups.values()]
    cols = _colors(len(names))

    with plt.rc_context(_THEME):
        fig, ax = plt.subplots(figsize=(max(5, 1.4 * len(names)), 4.2))
        bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                        medianprops=dict(color="black", linewidth=1.4),
                        showmeans=True,
                        meanprops=dict(marker="D", markerfacecolor="white",
                                       markeredgecolor="black", markersize=5))
        for patch, c in zip(bp["boxes"], cols):
            patch.set_facecolor(c)
            patch.set_alpha(0.55)
            patch.set_edgecolor("black")
        rng = np.random.default_rng(0)
        for i, arr in enumerate(data, start=1):
            jitter = rng.normal(0.0, 0.04, arr.size)
            ax.scatter(np.full(arr.size, i) + jitter, arr, s=12,
                       color=cols[i - 1], edgecolor="black", linewidth=0.3,
                       alpha=0.7, zorder=3)
        ax.set_xticks(np.arange(1, len(names) + 1))
        ax.set_xticklabels(names)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)
        ax.set_axisbelow(True)
        return _save(fig, out_png, dpi)


def fig5_regression_scatter(
    x,
    y,
    fit: dict,
    out_png: str | Path,
    *,
    xlabel: str = "x",
    ylabel: str = "y",
    title: str = "",
    dpi: int = 300,
) -> Path:
    """Fig-5 style: scatter + fit line with equation and R^2 annotation.

    ``fit`` is the dict returned by linear_regression (slope/intercept) or
    nonlinear_regression (coeffs); its ``equation_str`` and ``r2`` are shown.
    """
    xa = np.asarray(x, dtype=np.float64).ravel()
    ya = np.asarray(y, dtype=np.float64).ravel()
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    xs = np.linspace(float(np.min(xa)), float(np.max(xa)), 200)
    if "slope" in fit:
        ys = fit["slope"] * xs + fit["intercept"]
    elif "coeffs" in fit:
        ys = np.polyval(fit["coeffs"], xs)
    else:
        raise ValueError("fit must contain 'slope'/'intercept' or 'coeffs'")

    with plt.rc_context(_THEME):
        fig, ax = plt.subplots(figsize=(5.4, 4.4))
        ax.scatter(xa, ya, s=26, color=_PALETTE[0], edgecolor="black",
                   linewidth=0.4, alpha=0.8, zorder=2, label="data")
        ax.plot(xs, ys, "-", color=_PALETTE[1], linewidth=2.0, zorder=3,
                label="fit")
        eq = fit.get("equation_str", "")
        r2 = fit.get("r2")
        txt = eq if r2 is None else f"{eq}\n$R^2$ = {r2:.4f}"
        ax.text(0.04, 0.96, txt, transform=ax.transAxes, va="top", ha="left",
                fontsize=11,
                bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                          edgecolor="#999999", alpha=0.9))
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)
        ax.legend(loc="lower right", frameon=True, framealpha=0.9)
        ax.set_axisbelow(True)
        return _save(fig, out_png, dpi)
