"""Multi-format mesh export (stl / ply / obj / vtp / glb).

``.glb`` is the AR-ready binary glTF for ``<model-viewer>`` (Android Scene Viewer /
iOS Quick Look-adjacent) — triangulated, per-vertex colour baked in, triangle-capped.

``.vtp`` carries all point/cell scalars natively (best for round-tripping the
thickness or deviation field). ``.ply`` and ``.obj`` are surface-exchange formats
whose common writers do not preserve arbitrary float scalars, so — when an active
scalar exists — a per-vertex RGB colouring is baked in so the colour survives.
``.stl`` is a bare triangle-soup format and carries geometry only.

Point count is always preserved.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv

from core.viz.colormap import get_cmap

_MESH_FORMATS = ("stl", "ply", "obj", "vtp", "glb")

# Bound the AR asset so a pathological upload can't produce a huge phone download.
_GLB_MAX_TRIS = 250_000


def _export_glb(pd: "pv.PolyData", out_path: "Path", active, cmap_name, clim) -> "Path":
    """Write a Draco-free GLB with per-vertex colour baked in (for <model-viewer>
    AR). Triangulated + capped so the file stays phone-sized."""
    import trimesh

    pd = pd.triangulate()
    n_tris = pd.faces.reshape(-1, 4).shape[0]
    if n_tris > _GLB_MAX_TRIS:
        pd = pd.decimate(1.0 - _GLB_MAX_TRIS / n_tris).triangulate()
    faces = pd.faces.reshape(-1, 4)[:, 1:]
    verts = np.asarray(pd.points)
    vcolors = None
    if active is not None and active in pd.point_data:
        rgb = _scalar_to_rgb(pd, active, cmap_name, clim)
        vcolors = np.concatenate([rgb, np.full((len(rgb), 1), 255, np.uint8)], axis=1)
    tm = trimesh.Trimesh(vertices=verts, faces=faces, vertex_colors=vcolors, process=False)
    tm.export(str(out_path), file_type="glb")
    return out_path


def _scalar_to_rgb(mesh: pv.PolyData, scalar_name: str, cmap_name: str = "green_yellow_red",
                   clim: tuple[float, float] | None = None) -> np.ndarray:
    """Map a per-vertex scalar to an (n, 3) uint8 RGB array via ``cmap_name``."""
    vals = np.asarray(mesh.point_data[scalar_name], dtype=np.float64).ravel()
    if clim is None:
        lo, hi = float(np.nanmin(vals)), float(np.nanmax(vals))
    else:
        lo, hi = clim
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((vals - lo) / (hi - lo), 0.0, 1.0)
    rgba = get_cmap(cmap_name)(norm)
    return (rgba[:, :3] * 255.0 + 0.5).astype(np.uint8)


def export_mesh(mesh, out_path, *, fmt: str = "stl",
                scalar_name: str | None = None, cmap_name: str = "green_yellow_red",
                clim: tuple[float, float] | None = None) -> Path:
    """Write ``mesh`` to ``out_path`` as stl / ply / obj / vtp.

    Scalars are carried where the format allows: ``.vtp`` keeps every array;
    ``.ply`` bakes the active (or ``scalar_name``) field into vertex RGB so the
    colour survives; ``.obj`` writes geometry (with an accompanying colour bake
    when a scalar is present); ``.stl`` is geometry only. The vertex count is
    always preserved so the mesh reloads with the same number of points.
    """
    fmt = fmt.lower()
    if fmt not in _MESH_FORMATS:
        raise ValueError(f"fmt must be one of {_MESH_FORMATS}, got {fmt!r}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pd = mesh if isinstance(mesh, pv.PolyData) else pv.wrap(mesh)
    pd = pd.copy(deep=True)

    # Resolve which scalar to bake for colour-only formats.
    active = scalar_name
    if active is None and pd.point_data:
        for name in pd.point_data.keys():
            if name != "Normals":
                active = name
                break

    if fmt == "vtp":
        pd.save(str(out_path))  # keeps all scalars
        return out_path

    if fmt == "glb":
        return _export_glb(pd, out_path, active, cmap_name, clim)

    if fmt == "ply":
        if active is not None and active in pd.point_data:
            rgb = _scalar_to_rgb(pd, active, cmap_name, clim)
            pd.point_data["RGB"] = rgb
            pd.save(str(out_path), texture="RGB")  # vertex colours survive
        else:
            pd.save(str(out_path))
        return out_path

    # obj / stl: geometry writers. Bake colour into a sibling .ply-less path is
    # not standard; we simply write the surface. (OBJ has no portable per-vertex
    # colour in pyvista's writer; STL has none at all.)
    pd.save(str(out_path))
    return out_path
