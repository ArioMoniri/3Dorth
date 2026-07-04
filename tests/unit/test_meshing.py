"""Meshing: marching cubes produces a mm-scaled surface."""
import numpy as np

from core.meshing import mask_to_mesh


def test_cube_mesh_scale_and_nonempty():
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True  # 10-voxel cube
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    assert mesh.n_points > 0
    assert mesh.n_faces > 0
    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    # surface spans ~10 mm each axis (marching cubes at the 0.5 iso-level)
    assert 8.0 <= (xmax - xmin) <= 11.0
    assert 8.0 <= (ymax - ymin) <= 11.0
    assert 8.0 <= (zmax - zmin) <= 11.0


def test_anisotropic_spacing_scales_axes():
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    # z spacing 2 mm -> z extent ~2x the x/y extent
    mesh = mask_to_mesh(mask, (1.0, 1.0, 2.0), smooth_iters=0)
    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    assert (zmax - zmin) > 1.7 * (xmax - xmin)


def test_empty_mask_returns_empty_mesh():
    mask = np.zeros((10, 10, 10), dtype=bool)
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0))
    assert mesh.n_points == 0
