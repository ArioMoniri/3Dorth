"""Cortical (wall) thickness.

Primary method: **local thickness** (Hildebrand & Rüegsegger) — the diameter of
the largest inscribed sphere at each voxel — which is what 3-Matic's wall-
thickness tool computes. Anisotropic CT voxels are resampled to an isotropic
grid first (porespy's local_thickness assumes isotropy), then the value in mm is
sampled back onto the outer-surface vertices.

Validation method: **two-surface ray casting** — from each outer vertex, march
inward along the surface normal until the mask ends; the distance is the wall
thickness along the normal. The two methods are cross-checked (``agreement``).

All thicknesses are in millimetres and clamped to the registry window.
"""

from __future__ import annotations

import numpy as np
import porespy as ps
from pydantic import BaseModel
from scipy import ndimage


def _extrapolate_into_background(field: np.ndarray, foreground: np.ndarray,
                                 band_vox: int) -> np.ndarray:
    """Fill a thin background shell with the nearest foreground value.

    Without this, trilinear sampling of a scalar field at outer-surface vertices
    averages the interior value against background zeros and roughly halves the
    reading. Filling a ``band_vox`` shell makes boundary sampling unbiased.
    """
    bg = ~foreground
    dist, idx = ndimage.distance_transform_edt(bg, return_indices=True)
    out = field.copy()
    near = bg & (dist <= band_vox)
    iz, iy, ix = idx
    out[near] = field[iz[near], iy[near], ix[near]]
    return out


def local_thickness_map(
    mask_zyx: np.ndarray, spacing_xyz: tuple[float, float, float], iso: float = 0.6
) -> tuple[np.ndarray, float]:
    """Local-thickness (mm) on an isotropic resample of ``mask_zyx``.

    Returns ``(thickness_iso_zyx_mm, iso)`` where the array shares the mask's
    origin at iso spacing. porespy returns the *radius* of the largest inscribed
    sphere in voxels; thickness = diameter = 2 * radius * iso. The field is
    extrapolated a short distance into the background so that sampling it at the
    outer-surface vertices is not biased low by the background zeros.
    """
    sx, sy, sz = spacing_xyz
    zoom = (sz / iso, sy / iso, sx / iso)  # array axes are (z, y, x)
    iso_mask = ndimage.zoom(mask_zyx.astype(np.float32), zoom, order=0) > 0.5
    if iso_mask.sum() == 0:
        return np.zeros_like(iso_mask, dtype=np.float32), iso
    lt_radius_vox = ps.filters.local_thickness(iso_mask)
    thickness_mm = (2.0 * lt_radius_vox.astype(np.float32)) * iso
    band = max(2, int(round(2.0 / iso)))
    thickness_mm = _extrapolate_into_background(thickness_mm, iso_mask, band)
    return thickness_mm, iso


def sample_scalar_on_vertices(
    values_zyx: np.ndarray, vertices_xyz: np.ndarray, value_spacing: float,
    order: int = 1, fill: float = 0.0,
) -> np.ndarray:
    """Sample a scalar field (origin at 0, isotropic ``value_spacing``) at each
    mesh vertex (x, y, z mm). Trilinear (``order=1``) by default."""
    if len(vertices_xyz) == 0:
        return np.zeros(0, dtype=np.float32)
    coords = np.vstack([
        vertices_xyz[:, 2] / value_spacing,  # z index
        vertices_xyz[:, 1] / value_spacing,  # y index
        vertices_xyz[:, 0] / value_spacing,  # x index
    ])
    return ndimage.map_coordinates(
        values_zyx, coords, order=order, mode="constant", cval=fill
    ).astype(np.float32)


def raycast_thickness_on_vertices(
    vertices_xyz: np.ndarray, normals_xyz: np.ndarray, mask_zyx: np.ndarray,
    spacing_xyz: tuple[float, float, float], max_mm: float = 15.0, step_mm: float = 0.25,
) -> np.ndarray:
    """Wall thickness along the inward normal for each vertex.

    Marches from each vertex in the ``-normal`` direction until the mask ends;
    the travelled distance is the thickness. Vertices are assumed to be on the
    outer surface with outward-pointing ``normals_xyz``.
    """
    sx, sy, sz = spacing_xyz
    nz, ny, nx = mask_zyx.shape
    n = len(vertices_xyz)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    normals = normals_xyz / (np.linalg.norm(normals_xyz, axis=1, keepdims=True) + 1e-12)
    thickness = np.full(n, max_mm, dtype=np.float32)
    still_inside = np.ones(n, dtype=bool)

    for t in np.arange(step_mm, max_mm + step_mm, step_mm):
        p = vertices_xyz - t * normals  # step inward
        iz = np.round(p[:, 2] / sz).astype(int)
        iy = np.round(p[:, 1] / sy).astype(int)
        ix = np.round(p[:, 0] / sx).astype(int)
        in_bounds = (
            (iz >= 0) & (iz < nz) & (iy >= 0) & (iy < ny) & (ix >= 0) & (ix < nx)
        )
        val = np.zeros(n, dtype=bool)
        val[in_bounds] = mask_zyx[iz[in_bounds], iy[in_bounds], ix[in_bounds]]
        newly_exited = still_inside & ~val
        thickness[newly_exited] = t
        still_inside &= val
        if not still_inside.any():
            break
    return thickness


class ThicknessAgreement(BaseModel):
    n: int
    mean_abs_diff_mm: float
    median_abs_diff_mm: float
    rms_diff_mm: float
    pearson_r: float
    mean_a_mm: float
    mean_b_mm: float


def agreement(a: np.ndarray, b: np.ndarray) -> ThicknessAgreement:
    """Compare two per-vertex thickness estimates."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    diff = a - b
    if len(a) >= 2 and a.std() > 0 and b.std() > 0:
        r = float(np.corrcoef(a, b)[0, 1])
    else:
        r = float("nan")
    return ThicknessAgreement(
        n=int(len(a)),
        mean_abs_diff_mm=float(np.mean(np.abs(diff))),
        median_abs_diff_mm=float(np.median(np.abs(diff))),
        rms_diff_mm=float(np.sqrt(np.mean(diff**2))),
        pearson_r=r,
        mean_a_mm=float(np.mean(a)),
        mean_b_mm=float(np.mean(b)),
    )
