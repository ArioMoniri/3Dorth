"""Multi-format figure export of a coloured result surface.

Reuses ``core.viz``'s render style (pyvista off-screen bone render + a crisp
discrete matplotlib colorbar) but adds:

* a **pose adjuster** — an optional ``camera`` dict (azimuth / elevation / roll /
  zoom) applied on top of the standardized view;
* multiple raster formats (``png`` / ``tiff`` / ``jpg``) at a requested DPI, with
  TIFF embedding the DPI so the physical size is preserved;
* a ``diverging`` switch that centres a symmetric Mode-B colorbar (deviation) vs
  the sequential Mode-A colorbar (thickness), reading the matching registry
  parameters automatically.
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
from PIL import Image  # noqa: E402

from core.viz.colormap import discrete_colors, get_cmap  # noqa: E402

_RASTER_FORMATS = ("png", "tiff", "jpg")
_PIL_FORMAT = {"png": "PNG", "tiff": "TIFF", "jpg": "JPEG"}


def _colorbar_config(params, diverging: bool):
    """Resolve (vmin, vmax, steps, cmap_name, reverse, label) for the requested mode."""
    if diverging:
        center = params.mode_b_center
        rng = params.mode_b_range_abs
        return (
            center - rng, center + rng, params.mode_b_colorbar_steps,
            params.mode_b_colormap, False, "Signed deviation (mm)",
        )
    return (
        params.mode_a_range_min, params.mode_a_range_max, params.mode_a_colorbar_steps,
        params.mode_a_colormap, params.mode_a_colormap_reverse, "Cortical thickness (mm)",
    )


def _apply_camera(pl, camera: dict | None) -> None:
    """Apply the optional pose-adjuster dict to the plotter camera.

    Keys (all optional): ``azimuth`` / ``elevation`` / ``roll`` in degrees and
    ``zoom`` as a scale factor. Missing keys leave that axis untouched.
    """
    if not camera:
        return
    cam = pl.camera
    if camera.get("azimuth") is not None:
        cam.azimuth = float(camera["azimuth"])
    if camera.get("elevation") is not None:
        cam.elevation = float(camera["elevation"])
    if camera.get("roll") is not None:
        cam.roll = float(camera["roll"])
    if camera.get("zoom") is not None:
        cam.zoom(float(camera["zoom"]))


def _render_surface(mesh, scalar_name, cmap_name, reverse, steps, vmin, vmax,
                    view, window, camera) -> np.ndarray:
    """Off-screen render of the coloured surface -> an RGBA uint8 image array."""
    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=window)
    pl.set_background("white")
    pl.add_mesh(mesh, scalars=scalar_name, cmap=get_cmap(cmap_name, reverse),
                n_colors=steps, clim=[vmin, vmax], smooth_shading=True,
                show_scalar_bar=False)
    pl.add_axes(line_width=3)
    pl.camera_position = view
    pl.enable_parallel_projection()
    _apply_camera(pl, camera)
    img = pl.screenshot(return_img=True, transparent_background=True)
    pl.close()
    return img


def _compose(img, cmap_name, reverse, steps, vmin, vmax, label, dpi):
    """Compose the render + discrete colorbar into a matplotlib Figure."""
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
    return fig


def export_figure(
    mesh, scalar_name, params, out_path, *,
    fmt: str = "png", dpi: int = 300, camera: dict | None = None,
    diverging: bool = False, label: str | None = None,
    view: str = "xz", window=(950, 1150),
) -> Path:
    """Render ``mesh`` coloured by ``scalar_name`` and save as png/tiff/jpg.

    ``fmt`` is one of ``'png'`` / ``'tiff'`` / ``'jpg'``. ``dpi`` sets the raster
    resolution and, for TIFF/JPG, is embedded so the file reports the requested
    DPI. ``camera`` is an optional pose-adjuster ``{azimuth, elevation, roll,
    zoom}`` applied after the base view. ``diverging=True`` uses the Mode-B
    (deviation) colorbar; otherwise the Mode-A (thickness) colorbar.
    """
    fmt = fmt.lower()
    if fmt not in _RASTER_FORMATS:
        raise ValueError(f"fmt must be one of {_RASTER_FORMATS}, got {fmt!r}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vmin, vmax, steps, cmap_name, reverse, default_label = _colorbar_config(params, diverging)
    label = label if label is not None else default_label

    img = _render_surface(mesh, scalar_name, cmap_name, reverse, steps,
                          vmin, vmax, view, window, camera)
    fig = _compose(img, cmap_name, reverse, steps, vmin, vmax, label, dpi)

    # Render the composed figure to an RGB buffer, then save through PIL so we can
    # embed DPI consistently across PNG / TIFF (incl. TIFF ResolutionUnit) / JPEG.
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)

    pim = Image.fromarray(buf, mode="RGB")
    save_kwargs = {"dpi": (float(dpi), float(dpi))}
    if fmt == "tiff":
        save_kwargs["compression"] = "tiff_deflate"
    pim.save(str(out_path), format=_PIL_FORMAT[fmt], **save_kwargs)
    return out_path
