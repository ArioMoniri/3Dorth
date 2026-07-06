"""Shared pyvista scene builders for the trame frontend.

Kept separate from the trame wiring so the exact viewport content can be
screenshot-tested headlessly. Both the interactive app (``app_trame/app.py``) and
QA renders call these builders.

The scene is now driven by *live* geometry produced on demand by
``core.pipeline`` (analyze_thickness / compare_sides) with the CURRENT parameter
values — so every side-panel knob applies once the user hits Apply / Recompute.

Two content modes:
  * ``build_thickness_scene`` — Mode A (single side) and the per-side thickness
    view of Mode B: a surface colored by ``thickness_mm`` with the sequential
    Mode-A colormap.
  * ``build_deviation_scene`` — Mode B two-side comparison: the reference surface
    colored by signed ``deviation_mm`` with the diverging ``blue_white_red`` map.
"""

from __future__ import annotations

from pathlib import Path

import pyvista as pv

import core.parameters as P
from core.viz import get_cmap
from core.meshing.surface import smooth_point_scalar_display

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "outputs" / "demo"


# --------------------------------------------------------------------------- #
# Legacy demo loader (kept so precomputed-bundle callers/tests still work).
# --------------------------------------------------------------------------- #
def load_demo():
    """Load the demo manifest + region/thickness meshes (world mm)."""
    import json

    manifest = json.loads((DEMO / "manifest.json").read_text())
    regions = {}
    for r in manifest["regions"]:
        regions[r["label"]] = pv.read(str(DEMO / r["file"]))
    thickness = pv.read(str(DEMO / manifest["thickness"]["file"]))
    return manifest, regions, thickness


def _apply_view(plotter: pv.Plotter, params) -> None:
    plotter.add_axes(line_width=3, color="black")
    plotter.camera_position = "xz"


def build_thickness_scene(plotter: pv.Plotter, mesh, *, params=None, side_label="",
                          second_mesh=None):
    """Render a cortical-thickness surface (Mode A, or one side of Mode B).

    ``mesh`` is a live ``pyvista`` surface carrying a ``thickness_mm`` point
    scalar (as returned by ``core.pipeline.analyze_thickness``).

    When ``second_mesh`` is given (the bilateral "Both" view), a SECOND thickness
    surface is added in the same scene, coloured by its own ``thickness_mm`` with
    the identical LUT/clim, and only one shared scalar bar is shown — so left and
    right read on one legend. Each mesh keeps its own per-vertex thickness.
    """
    params = params or P.default_parameters()
    plotter.clear()
    plotter.clear_actors()
    plotter.set_background("white")

    title = "Cortical thickness (mm)"
    if side_label:
        title = f"{side_label} — cortical thickness (mm)"

    cmap = get_cmap(params.mode_a_colormap, params.mode_a_colormap_reverse)
    clim = [params.mode_a_range_min, params.mode_a_range_max]
    # DISPLAY-ONLY colour smoothing (raw thickness untouched; stats stay honest).
    csi = int(getattr(params, "color_smooth_iters", 0) or 0)
    color_scalar = smooth_point_scalar_display(mesh, "thickness_mm", csi)
    plotter.add_mesh(
        mesh,
        scalars=color_scalar,
        cmap=cmap,
        n_colors=params.mode_a_colorbar_steps,
        clim=clim,
        smooth_shading=True,
        scalar_bar_args=dict(
            title=title, vertical=True,
            position_x=0.82, position_y=0.10, height=0.78, width=0.05,
            n_labels=params.mode_a_colorbar_steps, fmt="%.2f",
            title_font_size=16, label_font_size=13, color="black",
            italic=False, bold=False, font_family="arial",
        ),
    )
    if second_mesh is not None:
        # Second bone, same LUT; suppress its scalar bar (the first one covers
        # both since the clim/colormap are shared).
        plotter.add_mesh(
            second_mesh,
            scalars=smooth_point_scalar_display(second_mesh, "thickness_mm", csi),
            cmap=cmap,
            n_colors=params.mode_a_colorbar_steps,
            clim=clim,
            smooth_shading=True,
            show_scalar_bar=False,
        )
    _apply_view(plotter, params)
    return plotter


def build_deviation_scene(plotter: pv.Plotter, mesh, *, params=None):
    """Render the Mode B signed-deviation surface with a diverging colormap.

    ``mesh`` carries a ``deviation_mm`` point scalar (from
    ``core.pipeline.compare_sides``). Colorbar is symmetric about the center.
    """
    params = params or P.default_parameters()
    plotter.clear()
    plotter.clear_actors()
    plotter.set_background("white")

    center = params.mode_b_center
    span = params.mode_b_range_abs
    csi = int(getattr(params, "color_smooth_iters", 0) or 0)
    dev_scalar = smooth_point_scalar_display(mesh, "deviation_mm", csi)
    plotter.add_mesh(
        mesh,
        scalars=dev_scalar,
        cmap=get_cmap(params.mode_b_colormap),
        n_colors=params.mode_b_colorbar_steps,
        clim=[center - span, center + span],
        smooth_shading=True,
        scalar_bar_args=dict(
            title="Surface difference (mm): +out / -in", vertical=True,
            position_x=0.82, position_y=0.10, height=0.78, width=0.05,
            n_labels=min(params.mode_b_colorbar_steps, 11), fmt="%+.2f",
            title_font_size=16, label_font_size=13, color="black",
            italic=False, bold=False, font_family="arial",
        ),
    )
    _apply_view(plotter, params)
    return plotter


def build_group_scene(plotter: pv.Plotter, mesh, ghosts=None, *, params=None):
    """Render the N-way "all visits at once" scene: ONE coloured surface (the
    aggregate ``deviation_mm`` from ``core.pipeline.compare_series_group``) plus the
    other visits as faint grey, non-pickable ghost shells behind it."""
    build_deviation_scene(plotter, mesh, params=params)  # colours the primary + colorbar
    for g in (ghosts or []):
        try:
            if getattr(g, "n_points", 0):
                plotter.add_mesh(g, color="#9ea0a8", opacity=0.22, smooth_shading=True,
                                 pickable=False, show_scalar_bar=False, name=None)
        except Exception:  # noqa: BLE001 — a ghost must never break the primary view
            pass
    return plotter


# --------------------------------------------------------------------------- #
# Backward-compatible wrapper for the old precomputed-bundle scene.
# --------------------------------------------------------------------------- #
def build_scene(plotter: pv.Plotter, manifest=None, regions=None, thickness=None, *,
                show_thickness: bool = True, visible_labels=None, highlight_label=None,
                params=None, mesh=None):
    """Compatibility shim.

    Preferred usage passes a live ``mesh`` (Mode A thickness surface) and renders
    via :func:`build_thickness_scene`. The legacy signature (manifest / regions /
    thickness precomputed bundle) is still honored for existing QA callers.
    """
    if mesh is not None:
        return build_thickness_scene(plotter, mesh, params=params)

    params = params or P.default_parameters()
    plotter.clear()
    plotter.clear_actors()
    plotter.set_background("white")
    if show_thickness and thickness is not None:
        return build_thickness_scene(plotter, thickness, params=params)
    for lb in (visible_labels or []):
        m = (regions or {}).get(lb)
        if m is None or m.n_points == 0:
            continue
        color = "#ff8c1a" if lb == highlight_label else "#3a3f7a"
        plotter.add_mesh(m, color=color, smooth_shading=True)
    _apply_view(plotter, params)
    return plotter
