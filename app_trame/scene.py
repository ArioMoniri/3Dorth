"""Shared pyvista scene for the trame frontend.

Kept separate from the trame wiring so the exact viewport content can be
screenshot-tested headlessly. Both the interactive app (app_trame/app.py) and
QA renders call ``build_scene``.
"""

from __future__ import annotations

from pathlib import Path

import pyvista as pv

import core.parameters as P
from core.viz import get_cmap

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "outputs" / "demo"

NEUTRAL = "#3a3f7a"
HIGHLIGHT = "#ff8c1a"


def load_demo():
    """Load the demo manifest + region/thickness meshes (world mm)."""
    import json

    manifest = json.loads((DEMO / "manifest.json").read_text())
    regions = {}
    for r in manifest["regions"]:
        regions[r["label"]] = pv.read(str(DEMO / r["file"]))
    thickness = pv.read(str(DEMO / manifest["thickness"]["file"]))
    return manifest, regions, thickness


def build_scene(plotter: pv.Plotter, manifest, regions, thickness, *,
                show_thickness: bool, visible_labels, highlight_label=None,
                params=None):
    """Populate ``plotter`` for the current UI state."""
    params = params or P.default_parameters()
    plotter.clear()
    plotter.set_background("white")

    if show_thickness:
        th = manifest["thickness"]
        plotter.add_mesh(
            thickness, scalars="thickness_mm",
            cmap=get_cmap(params.mode_a_colormap, params.mode_a_colormap_reverse),
            n_colors=params.mode_a_colorbar_steps,
            clim=[params.mode_a_range_min, params.mode_a_range_max],
            smooth_shading=True,
            scalar_bar_args=dict(
                title="Cortical thickness (mm)", vertical=True,
                position_x=0.86, position_y=0.08, height=0.82, width=0.07,
                n_labels=params.mode_a_colorbar_steps, fmt="%.4f", color="black",
            ),
        )
    else:
        for lb in visible_labels:
            mesh = regions.get(lb)
            if mesh is None or mesh.n_points == 0:
                continue
            color = HIGHLIGHT if lb == highlight_label else NEUTRAL
            plotter.add_mesh(mesh, color=color, smooth_shading=True)

    plotter.add_axes(line_width=3)
    plotter.camera_position = "xz"
    return plotter
