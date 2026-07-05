"""Publication-quality figure export.

The interactive UIs use VTK's live scalar bar; for exported figures we render the
3D bone in pyvista (no VTK legend) and compose a crisp, well-spaced discrete
colorbar in matplotlib — no text overlap, controllable fonts, 300+ DPI. This is
the Fig-2 look for reports.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import ListedColormap, Normalize  # noqa: E402

from core.viz.colormap import get_cmap  # noqa: E402

# One clean theme reused everywhere.
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 14,
    "axes.linewidth": 0.8,
    "figure.dpi": 100,
})


def discrete_colors(name: str, steps: int, reverse: bool = False) -> np.ndarray:
    return get_cmap(name, reverse)(np.linspace(0.0, 1.0, steps))


def render_thickness_figure(
    mesh, scalar: str, params, out_png: str | Path, *,
    view: str = "xz", window=(950, 1150), dpi: int = 300,
    label: str = "Cortical thickness (mm)",
) -> Path:
    """Compose a pyvista bone render with a crisp discrete matplotlib colorbar."""
    vmin, vmax = params.mode_a_range_min, params.mode_a_range_max
    steps = params.mode_a_colorbar_steps
    cmap_name = params.mode_a_colormap
    reverse = params.mode_a_colormap_reverse

    # DISPLAY-ONLY colour smoothing so the export matches the on-screen render;
    # colours off a smoothed copy, statistics stay on the raw scalar.
    from core.meshing.surface import smooth_point_scalar_display
    color_scalar = smooth_point_scalar_display(
        mesh, scalar, int(getattr(params, "color_smooth_iters", 0) or 0)
    )

    # 1) render the coloured bone offscreen, no VTK legend, transparent bg
    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=window)
    pl.set_background("white")
    pl.add_mesh(mesh, scalars=color_scalar, cmap=get_cmap(cmap_name, reverse),
                n_colors=steps, clim=[vmin, vmax], smooth_shading=True,
                show_scalar_bar=False)
    pl.add_axes(line_width=3)
    pl.camera_position = view
    pl.enable_parallel_projection()
    img = pl.screenshot(return_img=True, transparent_background=True)
    pl.close()

    # 2) compose with a discrete, non-overlapping colorbar
    fig, (ax_img, ax_cb) = plt.subplots(
        1, 2, figsize=(7.6, 8.6), dpi=dpi,
        gridspec_kw={"width_ratios": [8, 1], "wspace": 0.05},
    )
    ax_img.imshow(img)
    ax_img.axis("off")

    cmap = ListedColormap(discrete_colors(cmap_name, steps, reverse))
    sm = ScalarMappable(cmap=cmap, norm=Normalize(vmin, vmax))
    ticks = np.linspace(vmin, vmax, steps)
    cb = fig.colorbar(sm, cax=ax_cb, ticks=ticks)
    cb.set_label(label, fontsize=15, labelpad=12)
    cb.ax.set_yticklabels([f"{t:.4f}" for t in ticks], fontsize=12)
    cb.outline.set_linewidth(0.6)
    cb.ax.tick_params(length=3, width=0.6)

    out_png = Path(out_png)
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png
