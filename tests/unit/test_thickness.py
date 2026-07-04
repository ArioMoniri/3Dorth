"""Cortical thickness: local-thickness convention, ray-cast, sampling, agreement."""
import numpy as np

from core.meshing import mask_to_mesh
from core.thickness import (
    agreement,
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)


def test_local_thickness_slab_is_diameter():
    """A 10-voxel-thick plate at 1 mm iso has local thickness ~10 mm (diameter
    of the largest inscribed sphere), pinning the radius->diameter convention."""
    mask = np.zeros((30, 30, 30), dtype=bool)
    mask[:, :, 10:20] = True  # 10 voxels thick along x
    th, iso = local_thickness_map(mask, (1.0, 1.0, 1.0), iso=1.0)
    interior = th[8:22, 8:22, 12:18]
    assert 8.0 <= float(np.median(interior)) <= 12.0


def test_sample_scalar_linear_field():
    vals = np.zeros((10, 10, 10), dtype=np.float32)
    for x in range(10):
        vals[:, :, x] = float(x)  # value == x index
    verts = np.array([[3.0, 5.0, 5.0], [7.0, 5.0, 5.0]])  # x = 3, 7 mm
    s = sample_scalar_on_vertices(vals, verts, 1.0)
    assert np.allclose(s, [3.0, 7.0], atol=0.5)


def test_raycast_slab_thickness():
    mask = np.zeros((40, 40, 40), dtype=bool)
    mask[15:25, 5:35, 5:35] = True  # slab 10 voxels thick in z
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    v = np.asarray(mesh.points)
    n = np.asarray(mesh.point_normals)
    top = v[:, 2] > 23.0
    up = n[top][:, 2] > 0.7  # outward normals on the top face point +z
    th = raycast_thickness_on_vertices(v[top], n[top], mask, (1.0, 1.0, 1.0), max_mm=20)
    assert up.sum() > 0
    assert 8.0 <= float(np.median(th[up])) <= 12.0


def test_local_and_raycast_agree_on_hollow_shell():
    """On a true cortical shell (hollow cylinder, uniform 4 mm wall) the primary
    (local thickness) and validator (ray-cast) methods must agree. This is the
    correct validation of the implementations; on real trabecular bone the two
    diverge in subcortical regions, which is documented, not asserted here."""
    sp = 0.5
    nz, ny, nx = 70, 90, 90
    cy, cx = ny / 2.0, nx / 2.0
    yy, xx = np.mgrid[0:ny, 0:nx]
    rad = np.sqrt(((yy - cy) * sp) ** 2 + ((xx - cx) * sp) ** 2)
    r_out, r_in = 12.0, 8.0  # wall thickness = 4 mm
    ring = (rad >= r_in) & (rad <= r_out)
    mask = np.zeros((nz, ny, nx), dtype=bool)
    mask[12:58] = ring  # tube along z, away from the ends

    th_iso, iso = local_thickness_map(mask, (sp, sp, sp), iso=sp)

    mesh = mask_to_mesh(mask, (sp, sp, sp), smooth_iters=0)
    v = np.asarray(mesh.points)
    n = np.asarray(mesh.point_normals)
    # outer-wall vertices, away from end caps, with outward (radial) normals
    vr = np.sqrt((v[:, 0] - cx * sp) ** 2 + (v[:, 1] - cy * sp) ** 2)
    zc = (12 + 58) / 2.0 * sp
    radial = np.zeros_like(v)
    radial[:, 0] = v[:, 0] - cx * sp
    radial[:, 1] = v[:, 1] - cy * sp
    rnorm = np.linalg.norm(radial, axis=1, keepdims=True) + 1e-9
    outward = np.sum(n * (radial / rnorm), axis=1)
    sel = (vr > 10.5) & (np.abs(v[:, 2] - zc) < 8.0) & (outward > 0.7)
    assert sel.sum() > 50

    th_local = sample_scalar_on_vertices(th_iso, v[sel], iso)
    th_ray = raycast_thickness_on_vertices(v[sel], n[sel], mask, (sp, sp, sp), max_mm=12)
    ag = agreement(th_local, th_ray)
    # both recover ~4 mm and agree within ~1 mm on the true shell
    assert abs(ag.mean_a_mm - 4.0) < 1.2
    assert abs(ag.mean_b_mm - 4.0) < 1.2
    assert ag.mean_abs_diff_mm < 1.2


def test_agreement_identical():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ag = agreement(a, a.copy())
    assert ag.mean_abs_diff_mm == 0.0
    assert ag.pearson_r > 0.99
    assert ag.n == 5
