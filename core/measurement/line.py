"""Fig-2 panel A: sampling line across a surface.

Place ``n`` evenly spaced points along the straight segment ``p0 -> p1``, snap
each to the nearest surface vertex, and read a per-vertex scalar (e.g. cortical
thickness) there. Also builds lightweight overlay geometry (a poly-line plus a
small triangle marker at each sample) for a viewer to draw on top of the mesh.

All coordinates are world millimetres in (x, y, z); scalars live in the mesh's
``point_data`` under ``scalar_name``.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from pydantic import BaseModel


class LinePoint(BaseModel):
    """One sample along the Fig-2 measurement line."""

    index: int  # nearest surface vertex id
    position_xyz: tuple[float, float, float]  # snapped vertex position (mm)
    value_mm: float  # scalar read at that vertex
    param_t: float  # fractional position along p0 -> p1 in [0, 1]


def sample_line_on_surface(
    mesh: pv.PolyData,
    scalar_name: str,
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    n: int = 3,
) -> list[LinePoint]:
    """Sample ``n`` points along ``p0 -> p1``, snapped to the nearest vertex.

    Points are placed at ``t = 0, 1/(n-1), ..., 1`` (evenly spaced). Each ideal
    point is snapped to its nearest surface vertex and the scalar there is read.
    """
    if scalar_name not in mesh.point_data:
        raise KeyError(f"scalar {scalar_name!r} not in mesh.point_data")
    if n < 1:
        raise ValueError("n must be >= 1")

    pts = np.asarray(mesh.points, dtype=np.float64)
    if len(pts) == 0:
        return []
    scalars = np.asarray(mesh.point_data[scalar_name], dtype=np.float64)

    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    ts = np.array([0.0]) if n == 1 else np.linspace(0.0, 1.0, n)

    out: list[LinePoint] = []
    for t in ts:
        ideal = a + t * (b - a)
        d2 = np.einsum("ij,ij->i", pts - ideal, pts - ideal)
        idx = int(np.argmin(d2))
        v = pts[idx]
        out.append(
            LinePoint(
                index=idx,
                position_xyz=(float(v[0]), float(v[1]), float(v[2])),
                value_mm=float(scalars[idx]),
                param_t=float(t),
            )
        )
    return out


def _triangle_marker(center: np.ndarray, size: float) -> pv.PolyData:
    """A small flat triangle (in the x-y plane, at the point's z) for overlay."""
    cx, cy, cz = center
    h = size
    v = np.array(
        [
            [cx, cy + h, cz],
            [cx - h * 0.866, cy - h * 0.5, cz],
            [cx + h * 0.866, cy - h * 0.5, cz],
        ],
        dtype=np.float64,
    )
    faces = np.array([3, 0, 1, 2], dtype=np.int64)
    return pv.PolyData(v, faces)


def sample_line_overlay(
    points: list[LinePoint], marker_size: float = 0.6
) -> tuple[pv.PolyData, pv.PolyData, str]:
    """Build overlay geometry for the sampled line.

    Returns ``(markers, line, label)``:
    - ``markers``: merged small triangles, one per sample point.
    - ``line``: a poly-line connecting the sample positions (empty if < 2 pts).
    - ``label``: the Fig-2 caption string ``"Cortical thickness"``.
    """
    label = "Cortical thickness"
    if not points:
        return pv.PolyData(), pv.PolyData(), label

    positions = np.array([p.position_xyz for p in points], dtype=np.float64)

    markers = _triangle_marker(positions[0], marker_size)
    for pos in positions[1:]:
        markers = markers.merge(_triangle_marker(pos, marker_size))

    if len(positions) >= 2:
        n = len(positions)
        cells = np.hstack([[n], np.arange(n)]).astype(np.int64)
        line = pv.PolyData(positions)
        line.lines = cells
    else:
        line = pv.PolyData(positions)

    return markers, line, label
