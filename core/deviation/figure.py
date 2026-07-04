"""Mode-B deviation figure export.

Colours the target mesh by its signed deviation with the diverging
``blue_white_red`` map, centred at ``params.mode_b_center`` and symmetric over
``+/- params.mode_b_range_abs``, using a discrete band count. The colorbar is
composed in matplotlib for crisp, non-overlapping labels at 300 DPI — mirroring
:func:`core.viz.figure.render_thickness_figure`.
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

from core.viz import discrete_colors, get_cmap  # noqa: E402

_SCALAR_NAME = "deviation_mm"


def deviation_figure(
    mesh,
    dev_scalar: np.ndarray,
    params,
    out_png: str | Path,
    *,
    steps: int = 11,
    view: str = "xz",
    window: tuple[int, int] = (950, 1150),
    dpi: int = 300,
    label: str = "Signed deviation (mm)",
) -> Path:
    """Render ``mesh`` coloured by ``dev_scalar`` with a discrete diverging bar.

    The range is centred at ``params.mode_b_center`` and spans
    ``+/- params.mode_b_range_abs``; ``steps`` (default 11) sets the number of
    discrete bands (there is no ``mode_b_colorbar_steps`` registry knob yet — see
    ``new_params_needed``). Returns the written PNG path.
    """
    center = float(params.mode_b_center)
    rng = float(params.mode_b_range_abs)
    vmin, vmax = center - rng, center + rng
    cmap_name = params.mode_b_colormap

    mesh = pv.wrap(mesh) if not isinstance(mesh, pv.PolyData) else mesh
    dev = np.asarray(dev_scalar, dtype=np.float32).ravel()
    mesh = mesh.copy()
    mesh[_SCALAR_NAME] = dev

    # 1) offscreen bone render, no VTK legend, transparent bg
    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=window)
    pl.set_background("white")
    pl.add_mesh(
        mesh, scalars=_SCALAR_NAME, cmap=get_cmap(cmap_name),
        n_colors=steps, clim=[vmin, vmax], smooth_shading=True,
        show_scalar_bar=False,
    )
    pl.add_axes(line_width=3)
    pl.camera_position = view
    pl.enable_parallel_projection()
    img = pl.screenshot(return_img=True, transparent_background=True)
    pl.close()

    # 2) crisp discrete diverging colorbar
    fig, (ax_img, ax_cb) = plt.subplots(
        1, 2, figsize=(7.6, 8.6), dpi=dpi,
        gridspec_kw={"width_ratios": [8, 1], "wspace": 0.05},
    )
    ax_img.imshow(img)
    ax_img.axis("off")

    cmap = ListedColormap(discrete_colors(cmap_name, steps))
    sm = ScalarMappable(cmap=cmap, norm=Normalize(vmin, vmax))
    ticks = np.linspace(vmin, vmax, steps)
    cb = fig.colorbar(sm, cax=ax_cb, ticks=ticks)
    cb.set_label(label, fontsize=15, labelpad=12)
    cb.ax.set_yticklabels([f"{t:+.2f}" for t in ticks], fontsize=11)
    cb.outline.set_linewidth(0.6)
    cb.ax.tick_params(length=3, width=0.6)

    out_png = Path(out_png)
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png
