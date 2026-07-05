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

from core.measurement.annotate import AnnotationOverlays, plan_annotations  # noqa: E402
from core.viz.colormap import discrete_colors, get_cmap  # noqa: E402

_RASTER_FORMATS = ("png", "tiff", "jpg")
_PIL_FORMAT = {"png": "PNG", "tiff": "TIFF", "jpg": "JPEG"}

# Fig-2 overlay styling (world-space actors drawn on top of the coloured bone).
_LINE_COLOR = "#111111"        # sampling line + triangular markers (panel A)
_BRACKET_COLOR = "#111111"     # height bracket (panel B)


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


def _add_overlays(pl, overlays: AnnotationOverlays | None) -> None:
    """Draw the Fig-2 sampling line + height bracket as world-space actors.

    Actors are added in the SAME off-screen render (same camera / view / pose)
    as the coloured bone, so the annotations project onto exactly the pixels
    they measure. Drawn on top (no lighting) so they stay crisp and black.
    """
    if overlays is None or not overlays.any:
        return
    if overlays.line is not None and overlays.line.n_points >= 2:
        pl.add_mesh(overlays.line, color=_LINE_COLOR, line_width=4,
                    lighting=False, render_lines_as_tubes=True)
    if overlays.line_markers is not None and overlays.line_markers.n_points > 0:
        pl.add_mesh(overlays.line_markers, color=_LINE_COLOR, lighting=False,
                    show_scalar_bar=False)
    if overlays.bracket is not None and overlays.bracket.n_points >= 2:
        pl.add_mesh(overlays.bracket, color=_BRACKET_COLOR, line_width=3,
                    lighting=False, render_lines_as_tubes=True)


def _render_surface(mesh, scalar_name, cmap_name, reverse, steps, vmin, vmax,
                    view, window, camera, overlays: AnnotationOverlays | None = None) -> np.ndarray:
    """Off-screen render of the coloured surface -> an RGBA uint8 image array."""
    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=window)
    pl.set_background("white")
    pl.add_mesh(mesh, scalars=scalar_name, cmap=get_cmap(cmap_name, reverse),
                n_colors=steps, clim=[vmin, vmax], smooth_shading=True,
                show_scalar_bar=False)
    _add_overlays(pl, overlays)
    pl.add_axes(line_width=3)
    pl.camera_position = view
    pl.enable_parallel_projection()
    _apply_camera(pl, camera)
    img = pl.screenshot(return_img=True, transparent_background=True)
    pl.close()
    return img


def _compose(img, cmap_name, reverse, steps, vmin, vmax, label, dpi,
             caption: str | None = None):
    """Compose the render + discrete colorbar into a matplotlib Figure.

    ``caption`` (optional) is a small annotation legend drawn under the image —
    e.g. ``"Cortical thickness · Height"`` for the Fig-2 panels.
    """
    fig, (ax_img, ax_cb) = plt.subplots(
        1, 2, figsize=(7.6, 8.6), dpi=dpi,
        gridspec_kw={"width_ratios": [8, 1], "wspace": 0.05},
    )
    ax_img.imshow(img)
    ax_img.axis("off")
    if caption:
        ax_img.text(0.5, -0.02, caption, transform=ax_img.transAxes,
                    ha="center", va="top", fontsize=12, color="#111111")

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
    annotate: dict | None = None,
) -> Path:
    """Render ``mesh`` coloured by ``scalar_name`` and save as png/tiff/jpg.

    ``fmt`` is one of ``'png'`` / ``'tiff'`` / ``'jpg'``. ``dpi`` sets the raster
    resolution and, for TIFF/JPG, is embedded so the file reports the requested
    DPI. ``camera`` is an optional pose-adjuster ``{azimuth, elevation, roll,
    zoom}`` applied after the base view. ``diverging=True`` uses the Mode-B
    (deviation) colorbar; otherwise the Mode-A (thickness) colorbar.

    ``annotate`` (optional) overlays the Fig-2 measurement annotations on the
    render: ``{"sampling_line": True|{p0?,p1?,n?}, "height": True|{axis?,lower?,
    upper?,band?}}``. Either panel is auto-placed at the surgical-neck / lesser-
    tuberosity base when coordinates are omitted. The sampled thickness values
    are read from the mesh scalar (never fabricated); the resulting figure is a
    descriptive, single-subject annotation. See
    :func:`core.measurement.plan_annotations`.
    """
    fmt = fmt.lower()
    if fmt not in _RASTER_FORMATS:
        raise ValueError(f"fmt must be one of {_RASTER_FORMATS}, got {fmt!r}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vmin, vmax, steps, cmap_name, reverse, default_label = _colorbar_config(params, diverging)
    label = label if label is not None else default_label

    overlays = plan_annotations(mesh, scalar_name, annotate, params)
    caption = " · ".join(overlays.captions) if overlays.captions else None

    img = _render_surface(mesh, scalar_name, cmap_name, reverse, steps,
                          vmin, vmax, view, window, camera, overlays)
    fig = _compose(img, cmap_name, reverse, steps, vmin, vmax, label, dpi, caption)

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
