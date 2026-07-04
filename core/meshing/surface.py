"""Surface extraction from a binary mask.

Marching cubes in millimetres (spacing-aware), then optional Taubin smoothing
(shape-preserving) and decimation. Returns a pyvista ``PolyData`` in (x, y, z)
world millimetres so downstream viewers and distance queries share one frame.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
from skimage import measure


def mask_to_mesh(
    mask: np.ndarray,
    spacing_xyz: tuple[float, float, float],
    smooth_iters: int = 20,
    decimate_fraction: float = 0.0,
) -> pv.PolyData:
    """Convert a boolean mask (z, y, x) to a surface mesh in world mm.

    ``spacing_xyz`` is (sx, sy, sz); marching cubes needs it in array-axis order
    (z, y, x), so it is reversed internally. Output vertices are (x, y, z) mm.
    """
    mask = np.ascontiguousarray(mask).astype(np.float32)
    if mask.max() == 0 or min(mask.shape) < 2:
        return pv.PolyData()

    sx, sy, sz = spacing_xyz
    verts_zyx, faces, _normals, _vals = measure.marching_cubes(
        mask, level=0.5, spacing=(sz, sy, sx)
    )
    verts_xyz = verts_zyx[:, ::-1]  # (z,y,x) -> (x,y,z)
    faces_pv = np.hstack(
        [np.full((faces.shape[0], 1), 3, dtype=np.int64), faces.astype(np.int64)]
    ).ravel()
    mesh = pv.PolyData(verts_xyz, faces_pv)

    if smooth_iters and smooth_iters > 0:
        mesh = mesh.smooth_taubin(n_iter=int(smooth_iters), pass_band=0.1)
    if decimate_fraction and decimate_fraction > 0:
        mesh = mesh.decimate(float(decimate_fraction))
    mesh = mesh.clean()
    mesh.compute_normals(inplace=True, auto_orient_normals=True)
    return mesh
