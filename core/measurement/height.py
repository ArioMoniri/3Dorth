"""Fig-2 panel B: height / extent bracket.

``measure_height`` reports the mm span of a mesh (or point cloud) along an axis,
optionally clipped between two bounding planes. ``valid_height`` reports the
*minimum height of the same-color region* (per Guo et al. 2022) — the smallest
axial extent among the connected mesh regions whose per-vertex scalar falls in a
band ``[lo, hi]``.

Overlay geometry is two horizontal reference lines (at the lower/upper planes)
plus a vertical measure line between them; the label is ``"Height"``.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from pydantic import BaseModel

_AXIS = {"x": 0, "y": 1, "z": 2}


class HeightMeasurement(BaseModel):
    """Result of a height/extent measurement."""

    model_config = {"arbitrary_types_allowed": True}

    height_mm: float
    lower: float  # world coordinate of the lower plane along the axis
    upper: float  # world coordinate of the upper plane along the axis
    axis: str
    overlay: pv.PolyData
    label: str


def _points_of(points_or_mesh) -> np.ndarray:
    if isinstance(points_or_mesh, pv.DataSet):
        return np.asarray(points_or_mesh.points, dtype=np.float64)
    return np.asarray(points_or_mesh, dtype=np.float64)


def _bracket_overlay(
    points: np.ndarray, ai: int, lower: float, upper: float
) -> pv.PolyData:
    """Two horizontal reference lines + one vertical measure line."""
    if len(points) == 0:
        return pv.PolyData()
    other = [i for i in (0, 1, 2) if i != ai]
    o0, o1 = other
    lo0, hi0 = float(points[:, o0].min()), float(points[:, o0].max())
    mid1 = float(np.median(points[:, o1]))

    def _pt(av, v0):
        p = [0.0, 0.0, 0.0]
        p[ai] = av
        p[o0] = v0
        p[o1] = mid1
        return p

    verts = np.array(
        [
            _pt(lower, lo0),  # 0 lower line start
            _pt(lower, hi0),  # 1 lower line end
            _pt(upper, lo0),  # 2 upper line start
            _pt(upper, hi0),  # 3 upper line end
            _pt(lower, (lo0 + hi0) / 2.0),  # 4 measure bottom
            _pt(upper, (lo0 + hi0) / 2.0),  # 5 measure top
        ],
        dtype=np.float64,
    )
    lines = np.array([2, 0, 1, 2, 2, 3, 2, 4, 5], dtype=np.int64)
    poly = pv.PolyData(verts)
    poly.lines = lines
    return poly


def measure_height(
    points_or_mesh,
    axis: str = "z",
    lower: float | None = None,
    upper: float | None = None,
) -> HeightMeasurement:
    """Extent (mm) along ``axis`` between two bounding planes.

    ``lower``/``upper`` default to the full extent of the geometry along the
    axis. The returned height is ``upper - lower``.
    """
    if axis not in _AXIS:
        raise ValueError(f"axis must be one of {list(_AXIS)}")
    ai = _AXIS[axis]
    pts = _points_of(points_or_mesh)
    if len(pts) == 0:
        raise ValueError("no points to measure")

    coord = pts[:, ai]
    lo = float(coord.min()) if lower is None else float(lower)
    hi = float(coord.max()) if upper is None else float(upper)
    return HeightMeasurement(
        height_mm=float(hi - lo),
        lower=lo,
        upper=hi,
        axis=axis,
        overlay=_bracket_overlay(pts, ai, lo, hi),
        label="Height",
    )


def valid_height(
    mesh: pv.PolyData,
    scalar_name: str,
    band: tuple[float, float],
    axis: str = "z",
) -> HeightMeasurement:
    """Minimum height (mm) of the connected same-color region.

    Vertices whose scalar lies in ``band = (lo, hi)`` are selected; the induced
    sub-mesh is split into connected components, and the smallest axial extent
    among them is returned (the paper's "minimum height of the same-color
    region"). Falls back to the overall band extent if connectivity is
    unavailable.
    """
    if axis not in _AXIS:
        raise ValueError(f"axis must be one of {list(_AXIS)}")
    if scalar_name not in mesh.point_data:
        raise KeyError(f"scalar {scalar_name!r} not in mesh.point_data")
    ai = _AXIS[axis]
    lo, hi = float(band[0]), float(band[1])

    scalars = np.asarray(mesh.point_data[scalar_name], dtype=np.float64)
    in_band = (scalars >= lo) & (scalars <= hi)
    pts = np.asarray(mesh.points, dtype=np.float64)
    if not in_band.any():
        raise ValueError("no vertices fall in the given band")

    coord_all = pts[in_band, ai]
    overall_lo = float(coord_all.min())
    overall_hi = float(coord_all.max())

    best_extent: float | None = None
    best_lo, best_hi = overall_lo, overall_hi

    try:
        sub = mesh.extract_points(in_band, adjacent_cells=False)
        conn = sub.connectivity()
        region_ids = np.asarray(conn.point_data["RegionId"])
        sub_pts = np.asarray(conn.points, dtype=np.float64)
        for rid in np.unique(region_ids):
            c = sub_pts[region_ids == rid, ai]
            if c.size == 0:
                continue
            ext = float(c.max() - c.min())
            if best_extent is None or ext < best_extent:
                best_extent = ext
                best_lo, best_hi = float(c.min()), float(c.max())
    except Exception:
        best_extent = None

    if best_extent is None:
        best_extent = overall_hi - overall_lo
        best_lo, best_hi = overall_lo, overall_hi

    return HeightMeasurement(
        height_mm=float(best_extent),
        lower=best_lo,
        upper=best_hi,
        axis=axis,
        overlay=_bracket_overlay(pts[in_band], ai, best_lo, best_hi),
        label="Height",
    )
