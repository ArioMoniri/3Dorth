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
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from core.stats.plots import _PALETTE, _THEME, fig4_boxplots, fig5_regression_scatter  # noqa: E402

_RASTER_FORMATS = ("png", "tiff", "jpg")
_PIL_FORMAT = {"png": "PNG", "tiff": "TIFF", "jpg": "JPEG"}

_SCALAR_LABELS = {
    "thickness_mm": "Cortical thickness (mm)",
    "deviation_mm": "Signed deviation (mm)",
}


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


def distribution_histogram_bytes(
    values,
    *,
    scalar_name: str = "thickness_mm",
    label: str | None = None,
    n_bins: int = 40,
    fmt: str = "png",
    dpi: int = 300,
    title: str | None = None,
) -> bytes:
    """Publication-quality histogram of the active scalar with the mean marked.

    Mirrors the in-app distribution histogram (see ``StatsPanel`` / trame's
    ``_render_histogram_png``) but at print quality / caller DPI. Single-subject
    descriptive only: no group comparison is implied.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    label = label or _SCALAR_LABELS.get(scalar_name, scalar_name)
    if v.size == 0:
        raise ValueError("distribution_histogram_bytes needs at least one finite value")

    mean = float(np.mean(v))
    median = float(np.median(v))

    with plt.rc_context(_THEME):
        # constrained_layout keeps the title/axis-labels/legend inside the canvas —
        # without it, and because _fig_to_bytes reads the raw canvas buffer (no
        # bbox_inches="tight"), long labels clip at the lower-left edge.
        fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=dpi, constrained_layout=True)
        ax.hist(v, bins=n_bins, color=_PALETTE[0], edgecolor="black",
                linewidth=0.4, alpha=0.85, zorder=2)
        ax.axvline(mean, color=_PALETTE[1], linewidth=2.0, linestyle="-",
                   zorder=3, label=f"mean = {mean:.3f}")
        ax.axvline(median, color="#333333", linewidth=1.4, linestyle="--",
                   zorder=3, label=f"median = {median:.3f}")
        ax.set_xlabel(label)
        ax.set_ylabel("Vertex count")
        ax.set_title(title or f"Distribution — {label} (n={v.size}, single subject)")
        ax.legend(loc="upper right", frameon=True, framealpha=0.9, fontsize=10)
        ax.set_axisbelow(True)
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


def per_region_summary_bytes(
    regions: list[dict],
    *,
    fmt: str = "png",
    dpi: int = 300,
    title: str = "Per-region summary (descriptive, single subject)",
) -> bytes:
    """Per connected bone region: a volume bar chart annotated with boneness.

    ``regions`` is the ``[{label, volume_cm3, boneness}]`` list the analyze/
    compare pipeline already returns (see ``core.pipeline.analyze_thickness``).
    Only the ACTIVE region's mesh carries per-vertex thickness in this codebase
    (each analyze call crops to one region), so a genuine mean+/-SD-thickness-
    per-region comparison would require re-running the pipeline per region —
    out of scope for a "light, cached" figures endpoint. Instead this plots the
    one array-oriented per-region quantity already computed for every region:
    segmented volume (cm^3), with dense-cortex fraction ("boneness") annotated
    on each bar — still descriptive, still per-region, never a fabricated group
    comparison. Raises ValueError when fewer than 2 regions exist (nothing to
    compare) so the caller can fall back to the histogram alone.
    """
    if not regions or len(regions) < 2:
        raise ValueError("per_region_summary_bytes needs >= 2 regions")

    names = [f"R{r['label']}" for r in regions]
    vols = [float(r["volume_cm3"]) for r in regions]
    bones = [float(r.get("boneness", 0.0)) for r in regions]
    xpos = np.arange(len(names))
    cols = [_PALETTE[i % len(_PALETTE)] for i in range(len(names))]

    with plt.rc_context(_THEME):
        fig, ax = plt.subplots(figsize=(max(5, 1.2 * len(names)), 4.4), dpi=dpi,
                               constrained_layout=True)
        bars = ax.bar(xpos, vols, width=0.6, color=cols, edgecolor="black",
                      linewidth=0.7, alpha=0.9, zorder=2)
        for bar, b in zip(bars, bones):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                   f"bone {b:.2f}", ha="center", va="bottom", fontsize=9)
        ax.set_xticks(xpos)
        ax.set_xticklabels(names)
        ax.set_ylabel("Segmented volume (cm$^3$)")
        ax.set_title(title)
        ax.set_axisbelow(True)
        ax.margins(y=0.12)
        return _fig_to_bytes(fig, fmt=fmt, dpi=dpi)


def region_boxplot_bytes(
    values_by_region: dict,
    *,
    ylabel: str = "Cortical thickness (mm)",
    fmt: str = "png",
    dpi: int = 300,
    title: str = "Per-region distribution (descriptive, single subject)",
) -> bytes:
    """Box-per-region plot when per-vertex values ARE available for >1 region.

    Thin wrapper over ``fig4_boxplots`` that returns encoded bytes instead of
    writing a file, and requires >= 2 regions (else raises so the caller omits
    this figure rather than showing a meaningless single box).
    """
    if not values_by_region or len(values_by_region) < 2:
        raise ValueError("region_boxplot_bytes needs >= 2 regions with values")
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = fig4_boxplots(values_by_region, Path(td) / f"fig.{fmt if fmt != 'jpg' else 'png'}",
                          ylabel=ylabel, title=title, dpi=dpi)
        # fig4_boxplots always writes via matplotlib's own savefig (not the PIL
        # round-trip other figures here use); re-encode through PIL only when a
        # non-PNG/dpi-embedding format is needed so behaviour matches the rest
        # of this module (TIFF/JPG with embedded DPI).
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
    """Thin wrapper over ``fig5_regression_scatter`` returning encoded bytes.

    Only meaningful when there are enough (x, y) pairs to fit — callers should
    catch the underlying ``ValueError`` (from ``core.stats.linear_regression``/
    ``nonlinear_regression``) and omit this figure rather than fabricate a fit.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = fig5_regression_scatter(x, y, fit, Path(td) / "fig.png",
                                    xlabel=xlabel, ylabel=ylabel, title=title, dpi=dpi)
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

    ``which`` filters to a subset of {"histogram", "by_region"}; omitted/None
    renders every figure that the data supports. Figures that don't apply (e.g.
    ``by_region`` with a single region) are silently skipped — never fabricated.
    Returns ``{name: png/tiff/jpg bytes}``.
    """
    want = set(which) if which else {"histogram", "by_region"}
    out: dict[str, bytes] = {}

    if "histogram" in want:
        out["histogram"] = distribution_histogram_bytes(
            scalar_values, scalar_name=scalar_name, fmt=fmt, dpi=dpi)

    if "by_region" in want and regions and len(regions) > 1:
        out["by_region"] = per_region_summary_bytes(regions, fmt=fmt, dpi=dpi)

    return out
