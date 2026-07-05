"""Publication-style STATISTICS FIGURES for a single computed result.

Renders a computed session's scalar field (thickness_mm / deviation_mm) and its
region list into publication-quality matplotlib figures, returned as encoded
image bytes (PNG / TIFF / JPG) at a caller-chosen DPI — mirroring
``core.export.figure.export_figure`` for the 3D-figure export.

Honesty rail: this is SINGLE-SUBJECT descriptive statistics. Figures are always
labelled as a per-subject distribution / per-region breakdown — never as a
group comparison or inferential result. ``fig4_boxplots`` / ``fig5_regression_scatter``
(true across-group / correlation plots) are only produced when the underlying
data actually supports them (>=2 regions, or an explicit x/y pair); otherwise
those figures are omitted rather than fabricating groups.

Design: one restrained, consistent matplotlib theme (readable DejaVu Sans,
11-13 pt, thin spines with the top/right removed, faint gridlines, a muted
print palette — never matplotlib defaults), constrained_layout, descriptive
titles, units on every axis, mean/median annotated, no chartjunk.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from core.stats.plots import fig4_boxplots, fig5_regression_scatter  # noqa: E402

_RASTER_FORMATS = ("png", "tiff", "jpg")
_PIL_FORMAT = {"png": "PNG", "tiff": "TIFF", "jpg": "JPEG"}

_SCALAR_LABELS = {
    "thickness_mm": "Cortical thickness (mm)",
    "deviation_mm": "Signed deviation (mm)",
}

# --------------------------------------------------------------------------- #
# Publication theme + palette (local to this module; the shared core.stats.plots
# theme is intentionally left untouched so Fig 3/4/5 keep their current look).
# --------------------------------------------------------------------------- #
_THEME_PUB = {
    "font.family": "DejaVu Sans",       # the one sans guaranteed to ship with matplotlib
    "font.size": 12,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.labelsize": 12,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 10.5,
    "axes.linewidth": 0.8,
    "axes.edgecolor": "#4d4d4d",
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": "#c9c9c9",
    "grid.alpha": 0.45,
    "grid.linewidth": 0.6,
    "xtick.color": "#4d4d4d",
    "ytick.color": "#4d4d4d",
    "xtick.direction": "out",
    "ytick.direction": "out",
    "figure.dpi": 100,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
}

_INK = "#22303c"        # near-black axis/annotation ink
_MEAN_C = "#c0392b"     # warm red for the mean rule
_MEDIAN_C = "#2c3e50"   # dark slate for the median rule
_HIST_FILL = "#7fb0d3"  # soft blue histogram fill
_HIST_EDGE = "#2c6e9b"
_KDE_C = "#1f4e79"      # deep blue KDE curve
_PCTL_C = "#6b7b8c"     # muted grey percentile markers


def _style_axes(ax) -> None:
    """Remove the top/right spines and keep the remaining ones thin — the single
    consistent 'clean article' frame used by every figure in this module."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#4d4d4d")
    ax.spines["bottom"].set_color("#4d4d4d")
    ax.tick_params(length=3.5, width=0.8)
    ax.set_axisbelow(True)


def _fig_to_bytes(fig, *, fmt: str = "png", dpi: int = 300) -> bytes:
    """Render a matplotlib Figure to encoded bytes at ``dpi`` and close it.

    Uses the same PIL round-trip as ``core.export.figure`` so PNG / TIFF / JPG
    all embed the DPI consistently (TIFF's ResolutionUnit included).
    """
    fmt = fmt.lower()
    if fmt not in _RASTER_FORMATS:
        raise ValueError(f"fmt must be one of {_RASTER_FORMATS}, got {fmt!r}")

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)

    from PIL import Image

    pim = Image.fromarray(buf, mode="RGB")
    out = io.BytesIO()
    save_kwargs = {"dpi": (float(dpi), float(dpi))}
    if fmt == "tiff":
        save_kwargs["compression"] = "tiff_deflate"
    pim.save(out, format=_PIL_FORMAT[fmt], **save_kwargs)
    return out.getvalue()


def _reencode_png_path(p, *, fmt: str, dpi: int) -> bytes:
    """Read a matplotlib-written PNG and re-encode to ``fmt`` with embedded DPI.

    Shared by the ``fig4``/``fig5`` wrappers so TIFF/JPG behave like the rest of
    this module (native PNG bytes pass through untouched).
    """
    if fmt == "png":
        return p.read_bytes()
    from PIL import Image

    im = Image.open(p).convert("RGB")
    out = io.BytesIO()
    save_kwargs = {"dpi": (float(dpi), float(dpi))}
    if fmt == "tiff":
        save_kwargs["compression"] = "tiff_deflate"
    im.save(out, format=_PIL_FORMAT[fmt], **save_kwargs)
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Descriptive statistics (pure data) — the JSON stat block the analyze/figures
# responses expose, and the numbers the Table-1 figure renders.
# --------------------------------------------------------------------------- #
def descriptive_stats(values, *, scalar_name: str = "thickness_mm") -> dict:
    """Single-subject descriptive statistics for one scalar field.

    Returns a JSON-safe dict: ``n, mean, median, sd, rms, min, max``, the
    percentiles ``p5/p25/p50/p75/p95``, ``iqr``, and threshold fractions
    ``pct_over_1mm`` / ``pct_over_2mm`` (percent of vertices whose |value| exceeds
    the threshold — magnitude, so it is meaningful for the signed deviation field
    too). Descriptive only; never an inferential / group claim.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise ValueError("descriptive_stats needs at least one finite value")

    p5, p25, p50, p75, p95 = (float(x) for x in np.percentile(v, [5, 25, 50, 75, 95]))
    n = int(v.size)
    absv = np.abs(v)
    return {
        "scalar": scalar_name,
        "n": n,
        "mean": round(float(np.mean(v)), 4),
        "median": round(p50, 4),
        "sd": round(float(np.std(v, ddof=1)) if n > 1 else 0.0, 4),
        "rms": round(float(np.sqrt(np.mean(v ** 2))), 4),
        "min": round(float(np.min(v)), 4),
        "max": round(float(np.max(v)), 4),
        "p5": round(p5, 4),
        "p25": round(p25, 4),
        "p50": round(p50, 4),
        "p75": round(p75, 4),
        "p95": round(p95, 4),
        "iqr": round(p75 - p25, 4),
        "pct_over_1mm": round(100.0 * float(np.count_nonzero(absv > 1.0)) / n, 2),
        "pct_over_2mm": round(100.0 * float(np.count_nonzero(absv > 2.0)) / n, 2),
    }


def _gaussian_kde(v: np.ndarray, grid: np.ndarray) -> np.ndarray | None:
    """Gaussian KDE evaluated on ``grid``; ``None`` when it can't be fit
    (degenerate/zero-variance input) so callers can gracefully skip the curve."""
    if v.size < 2 or float(np.std(v)) == 0.0:
        return None
    try:
        from scipy.stats import gaussian_kde

        return gaussian_kde(v)(grid)
    except Exception:  # noqa: BLE001 - never let a KDE hiccup break the figure
        return None


# --------------------------------------------------------------------------- #
# (a) Distribution histogram + KDE + mean/median/percentile markers
# --------------------------------------------------------------------------- #
def distribution_histogram_bytes(
    values,
    *,
    scalar_name: str = "thickness_mm",
    label: str | None = None,
    n_bins: int = 40,
    fmt: str = "png",
    dpi: int = 300,
    title: str | None = None,
    kde: bool = True,
) -> bytes:
    """Publication-quality histogram of the active scalar.

    Density histogram with a Gaussian-KDE overlay, the mean (solid) and median
    (dashed) marked, and the p5/p95 percentile band shaded. Single-subject
    descriptive only: no group comparison is implied.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    label = label or _SCALAR_LABELS.get(scalar_name, scalar_name)
    if v.size == 0:
        raise ValueError("distribution_histogram_bytes needs at least one finite value")

    mean = float(np.mean(v))
    median = float(np.median(v))
    p5, p95 = (float(x) for x in np.percentile(v, [5, 95]))

    with plt.rc_context(_THEME_PUB):
        # constrained_layout keeps the title/labels/legend inside the canvas —
        # essential because _fig_to_bytes reads the raw canvas buffer (no
        # bbox_inches="tight").
        fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=dpi, constrained_layout=True)

        counts, edges, _ = ax.hist(
            v, bins=n_bins, density=True, color=_HIST_FILL, edgecolor=_HIST_EDGE,
            linewidth=0.5, alpha=0.9, zorder=2)
        ymax = float(counts.max()) if counts.size else 1.0

        # p5-p95 central band (context, not a claim)
        ax.axvspan(p5, p95, color=_PCTL_C, alpha=0.08, zorder=1,
                   label=f"p5–p95 [{p5:.2f}, {p95:.2f}]")

        if kde:
            grid = np.linspace(float(v.min()), float(v.max()), 256)
            dens = _gaussian_kde(v, grid)
            if dens is not None:
                ax.plot(grid, dens, color=_KDE_C, linewidth=1.8, zorder=4, label="KDE")

        ax.axvline(mean, color=_MEAN_C, linewidth=2.0, linestyle="-",
                   zorder=5, label=f"mean = {mean:.3f}")
        ax.axvline(median, color=_MEDIAN_C, linewidth=1.6, linestyle="--",
                   zorder=5, label=f"median = {median:.3f}")

        ax.set_xlabel(label)
        ax.set_ylabel("Probability density (1/mm)")
        ax.set_ylim(0, ymax * 1.18)
        ax.set_title(title or f"Distribution — {label.lower()}\n(n = {v.size:,}; single subject)",
                     fontsize=12.5)
        ax.legend(loc="upper right", frameon=True, framealpha=0.92,
                  edgecolor="#cccccc", fontsize=10)
        _style_axes(ax)
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


# --------------------------------------------------------------------------- #
# (b) ECDF / cumulative %
# --------------------------------------------------------------------------- #
def ecdf_bytes(
    values,
    *,
    scalar_name: str = "thickness_mm",
    label: str | None = None,
    fmt: str = "png",
    dpi: int = 300,
    title: str | None = None,
) -> bytes:
    """Empirical cumulative distribution (ECDF) with quartile guide-lines.

    Answers 'what fraction of the surface is below x mm?' directly — the median
    and IQR are read off as horizontal guides. Single-subject descriptive only.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    label = label or _SCALAR_LABELS.get(scalar_name, scalar_name)
    if v.size == 0:
        raise ValueError("ecdf_bytes needs at least one finite value")

    xs = np.sort(v)
    ys = np.arange(1, xs.size + 1) / xs.size * 100.0
    p25, p50, p75 = (float(x) for x in np.percentile(v, [25, 50, 75]))

    with plt.rc_context(_THEME_PUB):
        fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=dpi, constrained_layout=True)
        ax.step(xs, ys, where="post", color=_KDE_C, linewidth=2.0, zorder=3)
        ax.fill_between(xs, ys, step="post", color=_HIST_FILL, alpha=0.18, zorder=1)

        for q, name, c in ((p25, "p25", _PCTL_C), (p50, "median", _MEDIAN_C),
                           (p75, "p75", _PCTL_C)):
            frac = 100.0 * float(np.count_nonzero(v <= q)) / v.size
            ax.plot([q, q], [0, frac], color=c, linewidth=1.1, linestyle=":", zorder=2)
            ax.plot([xs.min(), q], [frac, frac], color=c, linewidth=1.1,
                    linestyle=":", zorder=2)
            ax.annotate(f"{name} = {q:.2f}", xy=(q, frac), xytext=(4, -12),
                        textcoords="offset points", fontsize=9, color=_INK)

        ax.set_xlabel(label)
        ax.set_ylabel("Cumulative percentage of vertices (%)")
        ax.set_ylim(0, 100)
        ax.margins(x=0.02)
        ax.set_title(title or f"Cumulative distribution — {label.lower()}\n(ECDF; single subject)",
                     fontsize=12.5)
        _style_axes(ax)
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


# --------------------------------------------------------------------------- #
# (c) Per-region volume bar chart (the one array-oriented per-region quantity
#     computed for EVERY region) — honesty-preserving.
# --------------------------------------------------------------------------- #
def per_region_summary_bytes(
    regions: list[dict],
    *,
    fmt: str = "png",
    dpi: int = 300,
    title: str = "Per-region summary (descriptive, single subject)",
) -> bytes:
    """Per connected bone region: a volume bar chart coloured by dense-cortex
    fraction ('boneness').

    ``regions`` is the ``[{label, volume_cm3, boneness}]`` list the analyze/
    compare pipeline already returns. Only the ACTIVE region's mesh carries
    per-vertex thickness (each analyze call crops to one region), so a genuine
    mean+/-SD-thickness-per-region comparison would require re-running the
    pipeline per region — out of scope for a light, cached figures endpoint.
    Instead this plots the one per-region quantity computed for every region:
    segmented volume (cm^3), with boneness both annotated and encoded as bar
    colour via a green->red map — still descriptive, still per-region, never a
    fabricated group comparison. Raises ValueError when fewer than 2 regions
    exist so the caller can fall back to the histogram alone.
    """
    if not regions or len(regions) < 2:
        raise ValueError("per_region_summary_bytes needs >= 2 regions")

    names = [f"R{r['label']}" for r in regions]
    vols = [float(r["volume_cm3"]) for r in regions]
    bones = [float(r.get("boneness", 0.0)) for r in regions]
    xpos = np.arange(len(names))

    import matplotlib as mpl
    from matplotlib import cm
    from matplotlib.colors import Normalize

    norm = Normalize(vmin=0.0, vmax=1.0)
    cmap = mpl.colormaps["RdYlGn"]  # low boneness red -> high boneness green
    cols = [cmap(norm(b)) for b in bones]

    with plt.rc_context(_THEME_PUB):
        fig, ax = plt.subplots(figsize=(max(5.2, 1.25 * len(names)), 4.5), dpi=dpi,
                               constrained_layout=True)
        bars = ax.bar(xpos, vols, width=0.62, color=cols, edgecolor=_INK,
                      linewidth=0.7, zorder=2)
        for bar, b in zip(bars, bones):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{b:.2f}", ha="center", va="bottom", fontsize=9, color=_INK)
        ax.set_xticks(xpos)
        ax.set_xticklabels(names)
        ax.set_ylabel("Segmented volume (cm$^3$)")
        ax.set_title(title)
        ax.margins(y=0.14)
        _style_axes(ax)

        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, pad=0.02, fraction=0.045)
        cb.set_label("Dense-cortex fraction (boneness)", fontsize=10)
        cb.outline.set_linewidth(0.6)
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


# --------------------------------------------------------------------------- #
# (d) Table-1-style descriptive panel
# --------------------------------------------------------------------------- #
def descriptive_table_bytes(
    values,
    *,
    scalar_name: str = "thickness_mm",
    label: str | None = None,
    fmt: str = "png",
    dpi: int = 300,
    title: str | None = None,
) -> bytes:
    """Clean 'Table 1' descriptive panel rendered as a figure.

    Two columns (statistic, value) covering n, mean +/- SD, median, IQR,
    min/max, the p5/p25/p75/p95 percentiles and the %>1 mm / %>2 mm threshold
    fractions — the same numbers exposed in the analyze/figures JSON. Single
    subject; no inferential content.
    """
    st = descriptive_stats(values, scalar_name=scalar_name)
    label = label or _SCALAR_LABELS.get(scalar_name, scalar_name)
    unit = "mm"

    rows = [
        ("n (vertices)", f"{st['n']:,}"),
        ("Mean ± SD", f"{st['mean']:.3f} ± {st['sd']:.3f} {unit}"),
        ("Median (p50)", f"{st['median']:.3f} {unit}"),
        ("IQR (p25–p75)", f"{st['iqr']:.3f} {unit}  [{st['p25']:.3f}, {st['p75']:.3f}]"),
        ("Min / Max", f"{st['min']:.3f} / {st['max']:.3f} {unit}"),
        ("RMS", f"{st['rms']:.3f} {unit}"),
        ("p5 / p95", f"{st['p5']:.3f} / {st['p95']:.3f} {unit}"),
        ("% > 1 mm", f"{st['pct_over_1mm']:.1f} %"),
        ("% > 2 mm", f"{st['pct_over_2mm']:.1f} %"),
    ]

    with plt.rc_context(_THEME_PUB):
        fig, ax = plt.subplots(figsize=(6.4, 0.52 * len(rows) + 1.3), dpi=dpi,
                               constrained_layout=True)
        ax.axis("off")
        ax.set_title(title or f"Table 1. Descriptive statistics — {label.lower()}\n"
                     "(single subject; not for diagnostic use)",
                     fontsize=12.5, fontweight="bold", loc="left", pad=10)

        tbl = ax.table(
            cellText=[[k, val] for k, val in rows],
            colLabels=["Statistic", "Value"],
            colWidths=[0.46, 0.54],
            cellLoc="left", colLoc="left", loc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(11)
        tbl.scale(1, 1.5)

        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#d0d0d0")
            cell.set_linewidth(0.6)
            if r == 0:  # header row
                cell.set_facecolor("#2c6e9b")
                cell.get_text().set_color("white")
                cell.get_text().set_fontweight("bold")
            else:
                cell.set_facecolor("#f4f7fa" if r % 2 else "#ffffff")
                if c == 0:  # statistic-name column
                    cell.get_text().set_color(_INK)
                    cell.get_text().set_fontweight("bold")
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


# --------------------------------------------------------------------------- #
# Optional true-multi-region plots (only when per-vertex values ARE available
# for >1 region) — thin wrappers over the shared Fig-4/Fig-5 renderers.
# --------------------------------------------------------------------------- #
def region_boxplot_bytes(
    values_by_region: dict,
    *,
    ylabel: str = "Cortical thickness (mm)",
    fmt: str = "png",
    dpi: int = 300,
    title: str = "Per-region distribution (descriptive, single subject)",
) -> bytes:
    """Box-per-region plot when per-vertex values ARE available for >1 region."""
    if not values_by_region or len(values_by_region) < 2:
        raise ValueError("region_boxplot_bytes needs >= 2 regions with values")
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = fig4_boxplots(values_by_region,
                          Path(td) / f"fig.{'png' if fmt == 'jpg' else fmt}",
                          ylabel=ylabel, title=title, dpi=dpi)
        return _reencode_png_path(p, fmt=fmt, dpi=dpi)


def regression_scatter_bytes(
    x,
    y,
    fit: dict,
    *,
    xlabel: str = "x",
    ylabel: str = "y",
    fmt: str = "png",
    dpi: int = 300,
    title: str = "Regression (descriptive, single subject)",
) -> bytes:
    """Thin wrapper over ``fig5_regression_scatter`` returning encoded bytes."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = fig5_regression_scatter(x, y, fit,
                                    Path(td) / f"fig.{'png' if fmt == 'jpg' else fmt}",
                                    xlabel=xlabel, ylabel=ylabel, title=title, dpi=dpi)
        return _reencode_png_path(p, fmt=fmt, dpi=dpi)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
# All figure names the endpoints know about (kept in sync with the API's
# _FIGURE_NAMES). "by_region" only applies when >1 bone region exists.
FIGURE_NAMES = ("histogram", "ecdf", "table", "by_region")


def render_result_figures(
    *,
    scalar_values,
    scalar_name: str = "thickness_mm",
    regions: list[dict] | None = None,
    which: list[str] | None = None,
    fmt: str = "png",
    dpi: int = 300,
) -> dict[str, bytes]:
    """Render the requested (or all-that-apply) figures for one computed result.

    ``which`` filters to a subset of ``FIGURE_NAMES``
    (``histogram``, ``ecdf``, ``table``, ``by_region``); omitted/None renders
    every figure the data supports. Figures that don't apply (e.g. ``by_region``
    with a single region) are silently skipped — never fabricated. Returns
    ``{name: png/tiff/jpg bytes}``.
    """
    want = set(which) if which else set(FIGURE_NAMES)
    out: dict[str, bytes] = {}

    if "histogram" in want:
        out["histogram"] = distribution_histogram_bytes(
            scalar_values, scalar_name=scalar_name, fmt=fmt, dpi=dpi)

    if "ecdf" in want:
        out["ecdf"] = ecdf_bytes(
            scalar_values, scalar_name=scalar_name, fmt=fmt, dpi=dpi)

    if "table" in want:
        out["table"] = descriptive_table_bytes(
            scalar_values, scalar_name=scalar_name, fmt=fmt, dpi=dpi)

    if "by_region" in want and regions and len(regions) > 1:
        out["by_region"] = per_region_summary_bytes(regions, fmt=fmt, dpi=dpi)

    return out
