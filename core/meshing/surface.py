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
    close_iters: int = 0,
    supersample: int = 1,
) -> pv.PolyData:
    """Convert a boolean mask (z, y, x) to a surface mesh in world mm.

    ``spacing_xyz`` is (sx, sy, sz); marching cubes needs it in array-axis order
    (z, y, x), so it is reversed internally. Output vertices are (x, y, z) mm.

    ``close_iters`` > 0 morphologically closes the mask first (dilate then erode),
    bridging small cortex gaps / partial-volume speckle so the surface is smooth
    and continuous instead of lacy. Kept small so it fills only tiny gaps and does
    NOT solidify the medullary cavity.

    ``supersample`` > 1 RESAMPLES THE VOXEL STAIRCASE AWAY (the step Mimics/3-matic
    do silently and the biggest driver of our lacy look): the binary mask is blurred
    into a soft occupancy field and upsampled, so marching cubes traces a smooth
    SUB-VOXEL iso-surface instead of a blocky per-voxel boundary. Bounded by a voxel
    cap so it stays cheap on the cropped bone.

    Both are DISPLAY-only wraps — the mask boundary is unchanged and cortical
    thickness is computed elsewhere on the raw mask at its own spacing.
    """
    mask = np.ascontiguousarray(mask).astype(bool)
    if not mask.any() or min(mask.shape) < 2:
        return pv.PolyData()

    if close_iters and int(close_iters) > 0:
        from scipy import ndimage
        mask = ndimage.binary_closing(mask, iterations=int(close_iters))

    m = mask.astype(np.float32)
    sx, sy, sz = spacing_xyz
    ss = max(1, int(supersample or 1))
    # only supersample when the result stays bounded (the cropped bone is small)
    if ss > 1 and m.size * (ss ** 3) <= 80_000_000:
        from scipy import ndimage
        m = ndimage.gaussian_filter(m, sigma=0.6)          # soften the hard boundary
        m = ndimage.zoom(m, ss, order=1)                    # finer grid, smooth interp
        sx, sy, sz = sx / ss, sy / ss, sz / ss             # spacing shrinks to match
    verts_zyx, faces, _normals, _vals = measure.marching_cubes(
        m, level=0.5, spacing=(sz, sy, sx)
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
