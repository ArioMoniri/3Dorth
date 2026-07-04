"""Surface registration (Mode B): point-cloud conversion, global+ICP alignment,
mirror, and transform application. Uses synthetic clouds with KNOWN transforms so
recovery is provable."""
import numpy as np
import pyvista as pv

from core.meshing import mask_to_mesh
from core.registration import (
    RegistrationResult,
    apply_transform,
    mirror,
    register,
    register_on_anchor,
    to_point_cloud,
)


def _rng_cloud(n=800, seed=0):
    rng = np.random.default_rng(seed)
    # a curved, non-symmetric surface patch so ICP/PCA is well-conditioned
    xy = rng.uniform(-10, 10, size=(n, 2))
    z = 0.05 * xy[:, 0] ** 2 - 0.03 * xy[:, 1] ** 2 + 0.4 * xy[:, 0]
    return np.column_stack([xy, z]).astype(np.float64)


def _rot(ax, ay, az):
    cx, sx = np.cos(ax), np.sin(ax)
    cy, sy = np.cos(ay), np.sin(ay)
    cz, sz = np.cos(az), np.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _mesh_from_points(pts):
    return pv.PolyData(np.asarray(pts, dtype=float))


def test_to_point_cloud_has_points_and_normals():
    mask = np.zeros((30, 30, 30), dtype=bool)
    mask[10:20, 5:25, 5:25] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    pc = to_point_cloud(mesh)
    assert len(pc.points) == mesh.n_points
    assert pc.has_normals()


def test_register_recovers_rigid_transform():
    src = _rng_cloud(seed=1)
    R = _rot(0.15, -0.1, 0.2)
    t = np.array([3.0, -2.0, 1.5])
    tgt = (R @ src.T).T + t

    res = register(_mesh_from_points(src), _mesh_from_points(tgt),
                   voxel_size=1.0, icp_iters=80, use_global=True)
    assert isinstance(res, RegistrationResult)
    assert res.converged
    assert res.fitness > 0.9
    # transform maps source onto target with sub-fraction-of-voxel RMS
    assert res.rms < 0.1  # < 0.1 * voxel_size (voxel=1.0)

    T = np.array(res.transform)
    moved = apply_transform(_mesh_from_points(src), T)
    d = np.linalg.norm(np.asarray(moved.points) - tgt, axis=1)
    assert float(np.sqrt(np.mean(d ** 2))) < 0.1


def test_register_noisy_copy_converges():
    rng = np.random.default_rng(7)
    src = _rng_cloud(seed=2)
    R = _rot(0.05, 0.08, -0.06)
    t = np.array([1.0, 0.5, -0.7])
    tgt = (R @ src.T).T + t + rng.normal(0, 0.05, size=src.shape)

    res = register(_mesh_from_points(src), _mesh_from_points(tgt),
                   voxel_size=1.0, icp_iters=80, use_global=True)
    assert res.converged
    assert res.fitness > 0.8
    assert res.rms < 0.3  # noise floor ~0.05*sqrt(3); ICP stays small


def test_register_pca_fallback_no_global():
    src = _rng_cloud(seed=3)
    R = _rot(0.1, -0.05, 0.12)
    t = np.array([2.0, 1.0, -1.0])
    tgt = (R @ src.T).T + t
    res = register(_mesh_from_points(src), _mesh_from_points(tgt),
                   voxel_size=1.0, icp_iters=100, use_global=False)
    assert res.converged
    assert res.rms < 0.15


def test_apply_transform_points_and_mesh():
    T = np.eye(4)
    T[:3, :3] = _rot(0.0, 0.0, np.pi / 2)  # 90deg about z
    T[:3, 3] = [1.0, 2.0, 3.0]
    pts = np.array([[1.0, 0.0, 0.0]])
    out = apply_transform(pts, T)
    assert np.allclose(out[0], [1.0, 3.0, 3.0], atol=1e-6)

    mesh = _mesh_from_points(pts)
    m2 = apply_transform(mesh, T)
    assert isinstance(m2, pv.PolyData)
    assert np.allclose(np.asarray(m2.points)[0], [1.0, 3.0, 3.0], atol=1e-6)
    # original mesh untouched (copy semantics)
    assert np.allclose(np.asarray(mesh.points)[0], [1.0, 0.0, 0.0])


def test_mirror_negates_x_about_center():
    mask = np.zeros((20, 20, 30), dtype=bool)
    mask[5:15, 5:15, 5:25] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    c = np.asarray(mesh.points).mean(axis=0)
    m = mirror(mesh, plane="x", center=c)
    p0 = np.asarray(mesh.points)
    p1 = np.asarray(m.points)
    # x reflected about center; y,z preserved
    assert np.allclose(p1[:, 0], 2 * c[0] - p0[:, 0], atol=1e-6)
    assert np.allclose(p1[:, 1], p0[:, 1], atol=1e-6)
    assert np.allclose(p1[:, 2], p0[:, 2], atol=1e-6)


def test_mirror_twice_is_identity():
    mask = np.zeros((20, 20, 30), dtype=bool)
    mask[5:15, 5:15, 5:25] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    m2 = mirror(mirror(mesh, plane="x"), plane="x")
    assert np.allclose(np.asarray(m2.points), np.asarray(mesh.points), atol=1e-6)


def test_mirror_fixes_face_winding():
    """A mirror flips handedness; mirror() must reverse triangle winding and
    reflect the stored normals so they stay outward. Verified on a cube whose
    outward normals point away from the centroid: after mirroring, the stored
    normals still point away from the (unchanged) centroid."""
    mask = np.zeros((24, 24, 24), dtype=bool)
    mask[6:18, 6:18, 6:18] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    mesh.compute_normals(inplace=True, auto_orient_normals=True)
    c = np.asarray(mesh.points).mean(axis=0)
    m = mirror(mesh, plane="x", center=c)
    pts = np.asarray(m.points)
    n1 = np.asarray(m.point_normals)  # stored normals produced by mirror()
    outward = pts - pts.mean(axis=0)
    outward /= np.linalg.norm(outward, axis=1, keepdims=True) + 1e-9
    # stored mirrored normals point outward as strongly as the originals did
    assert float(np.mean(np.sum(n1 * outward, axis=1))) > 0.5

    # winding was actually reversed (not left handedness-flipped)
    f0 = mesh.faces.reshape(-1, 4)
    f1 = m.faces.reshape(-1, 4)
    assert np.array_equal(f1[:, 1:], f0[:, 1:][:, ::-1])


def test_register_on_anchor_restricts_fit():
    src = _rng_cloud(n=1000, seed=11)
    R = _rot(0.08, -0.06, 0.1)
    t = np.array([1.5, -1.0, 0.8])
    tgt = (R @ src.T).T + t
    # anchor = a spatial subset (indices) of the source
    anchor_idx = np.where(src[:, 0] > 0)[0]
    res = register_on_anchor(
        _mesh_from_points(src), _mesh_from_points(tgt), anchor_idx,
        voxel_size=1.0, icp_iters=80, use_global=True,
    )
    assert res.converged
    T = np.array(res.transform)
    moved = apply_transform(_mesh_from_points(src[anchor_idx]), T)
    d = np.linalg.norm(np.asarray(moved.points) - tgt[anchor_idx], axis=1)
    assert float(np.sqrt(np.mean(d ** 2))) < 0.2
