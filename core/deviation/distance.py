"""Signed surface deviation — Mode B core.

The sign is **safety-critical**. With ``convention='target_outside_positive'``
a target vertex that lies OUTSIDE the closed reference surface is POSITIVE
(bone gain / hypertrophy); inside is negative (bone loss / atrophy).

Two independent implementations are provided so the sign can be cross-checked:

* :func:`signed_distance` — primary, VTK's ``vtkImplicitPolyDataDistance``,
  which returns +outside / -inside by default (no negation needed).
* :func:`_signed_distance_trimesh` — a closest-point-plus-face-normal method
  that needs neither ``rtree`` nor ray casting, used only by
  :func:`cross_check`.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv

_CONVENTIONS = ("target_outside_positive", "target_outside_negative")


def _as_polydata(mesh) -> pv.PolyData:
    """Coerce to a triangulated, cleaned pyvista ``PolyData``."""
    pd = pv.wrap(mesh) if not isinstance(mesh, pv.PolyData) else mesh
    return pd.triangulate().clean()


def _sign_factor(convention: str) -> float:
    if convention not in _CONVENTIONS:
        raise ValueError(
            f"convention must be one of {_CONVENTIONS}, got {convention!r}"
        )
    return 1.0 if convention == "target_outside_positive" else -1.0


def signed_distance(
    target_mesh,
    reference_mesh,
    convention: str = "target_outside_positive",
) -> np.ndarray:
    """Signed distance from each TARGET vertex to the REFERENCE surface.

    Uses ``vtkImplicitPolyDataDistance`` whose native sign is
    +outside / -inside the closed reference. With
    ``convention='target_outside_positive'`` that native sign is kept, so a
    target vertex outside the reference is positive (bone gain). The
    ``'target_outside_negative'`` convention flips every value.

    Returns one float per target vertex, in world millimetres, ordered to match
    ``target_mesh.points``.
    """
    import vtk  # local import keeps module import cheap

    factor = _sign_factor(convention)
    target = _as_polydata(target_mesh)
    reference = _as_polydata(reference_mesh)

    if target.n_points == 0 or reference.n_points == 0:
        return np.zeros(target.n_points, dtype=np.float32)

    imp = vtk.vtkImplicitPolyDataDistance()
    imp.SetInput(reference)
    pts = np.asarray(target.points, dtype=np.float64)
    dev = np.fromiter(
        (imp.EvaluateFunction(p) for p in pts), dtype=np.float64, count=len(pts)
    )
    return (factor * dev).astype(np.float32)


def _signed_distance_trimesh(
    target_mesh,
    reference_mesh,
    convention: str = "target_outside_positive",
) -> np.ndarray:
    """Independent signed-distance via closest point + closest-face normal.

    The unsigned distance is the closest-point distance; the sign comes from
    the dot product of (query - closest_point) with the reference face normal
    (positive => outside). This avoids ``rtree`` / ray casting, so it works as a
    portable cross-check against :func:`signed_distance`.
    """
    import trimesh
    from trimesh.proximity import closest_point_naive

    factor = _sign_factor(convention)
    target = _as_polydata(target_mesh)
    reference = _as_polydata(reference_mesh)
    if target.n_points == 0 or reference.n_points == 0:
        return np.zeros(target.n_points, dtype=np.float32)

    faces = reference.faces.reshape(-1, 4)[:, 1:]
    ref_tm = trimesh.Trimesh(
        vertices=np.asarray(reference.points), faces=faces, process=False
    )
    pts = np.asarray(target.points, dtype=np.float64)
    closest, distance, tri_id = closest_point_naive(ref_tm, pts)
    vec = pts - closest
    dot = np.einsum("ij,ij->i", vec, ref_tm.face_normals[tri_id])
    sign = np.where(dot >= 0.0, 1.0, -1.0)
    return (factor * sign * distance).astype(np.float32)


def cross_check(target_mesh, reference_mesh) -> float:
    """Median absolute difference between VTK and trimesh signed distances.

    Both use ``target_outside_positive``. A small value (sub-voxel) confirms the
    two independent implementations agree in magnitude AND sign.
    """
    a = signed_distance(target_mesh, reference_mesh, "target_outside_positive")
    b = _signed_distance_trimesh(
        target_mesh, reference_mesh, "target_outside_positive"
    )
    if len(a) == 0:
        return 0.0
    return float(np.median(np.abs(a.astype(np.float64) - b.astype(np.float64))))
