"""Point-cloud registration primitives built on open3d.

Deterministic where the open3d API exposes a seed (RANSAC). Transforms are
returned as plain 4x4 lists inside a pydantic :class:`RegistrationResult` so the
result is serialisable and framework-agnostic.
"""

from __future__ import annotations

import numpy as np
import open3d as o3d
import pyvista as pv
from pydantic import BaseModel, Field

# Determinism: seed open3d's RNG at import so RANSAC is reproducible on builds
# whose registration_ransac API does not accept a per-call ``seed`` argument.
try:  # pragma: no cover - depends on open3d build
    o3d.utility.random.seed(42)
except Exception:  # pragma: no cover
    pass


class RegistrationResult(BaseModel):
    """Outcome of aligning a source surface onto a target surface.

    ``transform`` is the 4x4 homogeneous matrix that maps source points into the
    target frame. ``rms`` is the inlier root-mean-square residual (mm); ``fitness``
    is the fraction of source points with a target correspondence within the ICP
    threshold; ``inlier_fraction`` mirrors fitness for callers expecting that name.
    """

    transform: list[list[float]]
    rms: float
    inlier_fraction: float
    fitness: float
    converged: bool = Field(default=True)


# --------------------------------------------------------------------------- #
# conversions
# --------------------------------------------------------------------------- #
def _mesh_points(mesh_or_points) -> np.ndarray:
    if isinstance(mesh_or_points, pv.PolyData):
        return np.asarray(mesh_or_points.points, dtype=np.float64)
    return np.asarray(mesh_or_points, dtype=np.float64)


def to_point_cloud(mesh, normal_radius: float | None = None) -> o3d.geometry.PointCloud:
    """Build an open3d ``PointCloud`` (with normals) from a mesh or point array.

    Vertex normals are reused when the mesh carries them; otherwise they are
    estimated from a local neighbourhood. ``normal_radius`` defaults to a scale
    derived from the point-cloud extent.
    """
    pts = _mesh_points(mesh)
    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(pts)

    normals = None
    if isinstance(mesh, pv.PolyData) and "Normals" in mesh.point_data:
        normals = np.asarray(mesh.point_normals, dtype=np.float64)
        if normals.shape == pts.shape:
            pc.normals = o3d.utility.Vector3dVector(normals)

    if pc.has_normals():
        return pc

    if normal_radius is None:
        extent = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        normal_radius = max(extent / 20.0, 1e-3)
    pc.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=normal_radius, max_nn=30)
    )
    pc.orient_normals_consistent_tangent_plane(k=15)
    return pc


def apply_transform(mesh_or_points, transform):
    """Return a transformed copy of ``mesh_or_points`` (never mutates the input).

    Accepts a ``pyvista.PolyData`` (returns a transformed copy) or an ``(n, 3)``
    array (returns an ``(n, 3)`` array). ``transform`` is a 4x4 matrix or nested
    list mapping (x, y, z) -> (x, y, z).
    """
    T = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    if isinstance(mesh_or_points, pv.PolyData):
        out = mesh_or_points.copy(deep=True)
        pts = np.asarray(out.points, dtype=np.float64)
        moved = (T[:3, :3] @ pts.T).T + T[:3, 3]
        out.points = moved
        if "Normals" in out.point_data:
            n = np.asarray(out.point_normals, dtype=np.float64)
            out.point_data["Normals"] = (T[:3, :3] @ n.T).T
        return out
    pts = np.asarray(mesh_or_points, dtype=np.float64)
    return (T[:3, :3] @ pts.T).T + T[:3, 3]


# --------------------------------------------------------------------------- #
# mirror
# --------------------------------------------------------------------------- #
def mirror(mesh, plane: str = "x", center=None) -> pv.PolyData:
    """Reflect a mesh across a sagittal plane for contralateral comparison.

    ``plane`` selects the reflected axis ('x' negates x about ``center``). The
    reflection flips face handedness, so triangle winding is reversed to keep
    outward normals outward. ``center`` defaults to the mesh centroid.
    """
    axis = {"x": 0, "y": 1, "z": 2}[plane]
    out = mesh.copy(deep=True)
    pts = np.asarray(out.points, dtype=np.float64)
    if center is None:
        c = float(pts[:, axis].mean())
    else:
        c = float(np.asarray(center, dtype=np.float64)[axis])
    pts[:, axis] = 2.0 * c - pts[:, axis]
    out.points = pts

    # Reflection reverses orientation -> flip winding of each triangle face.
    if out.n_cells > 0 and out.is_all_triangles:
        faces = out.faces.reshape(-1, 4).copy()
        faces[:, 1:] = faces[:, 1:][:, ::-1]
        out.faces = faces.ravel()

    if "Normals" in out.point_data:
        n = np.asarray(out.point_normals, dtype=np.float64)
        n[:, axis] = -n[:, axis]
        out.point_data["Normals"] = n
    return out


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def _pca_frame(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (centroid, rotation) whose columns are principal axes (sorted)."""
    c = pts.mean(axis=0)
    cov = np.cov((pts - c).T)
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    R = evecs[:, order]
    if np.linalg.det(R) < 0:  # keep right-handed
        R[:, -1] *= -1
    return c, R


def _pca_init(src: np.ndarray, tgt: np.ndarray) -> np.ndarray:
    """Coarse rigid init aligning the PCA frames of source and target."""
    cs, Rs = _pca_frame(src)
    ct, Rt = _pca_frame(tgt)
    R = Rt @ Rs.T
    t = ct - R @ cs
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


# The sign of each principal axis is arbitrary; enumerate the det=+1 sign
# combinations so an ambiguous (near-symmetric) patch still finds the right basin.
_PCA_SIGNS = [
    np.diag(s).astype(float)
    for s in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))
]


def _pca_init_candidates(src: np.ndarray, tgt: np.ndarray) -> list[np.ndarray]:
    cs, Rs = _pca_frame(src)
    ct, Rt = _pca_frame(tgt)
    out = []
    for S in _PCA_SIGNS:
        R = (Rt @ S) @ Rs.T
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = ct - R @ cs
        out.append(T)
    return out


def _prep(pc: o3d.geometry.PointCloud, voxel: float):
    down = pc.voxel_down_sample(voxel) if voxel and voxel > 0 else pc
    if not down.has_normals():
        down.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2.0, max_nn=30)
        )
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 5.0, max_nn=100)
    )
    return down, fpfh


def _global_ransac(src_pc, tgt_pc, voxel):
    src_d, src_f = _prep(src_pc, voxel)
    tgt_d, tgt_f = _prep(tgt_pc, voxel)
    dist = voxel * 1.5
    result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        src_d, tgt_d, src_f, tgt_f, True, dist,
        o3d.pipelines.registration.TransformationEstimationPointToPoint(False), 3,
        [
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(dist),
        ],
        o3d.pipelines.registration.RANSACConvergenceCriteria(4_000_000, 0.999),
    )
    return result.transformation


def _icp_refine(src_pc, tgt_pc, init, voxel, icp_iters):
    if not src_pc.has_normals():
        src_pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2, max_nn=30))
    if not tgt_pc.has_normals():
        tgt_pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2, max_nn=30))
    p2l = o3d.pipelines.registration.TransformationEstimationPointToPlane()
    # Coarse-to-fine: start with a generous correspondence threshold so a rough
    # init still finds matches, then tighten so an exact transform reaches
    # fitness ~1.0 with a small residual.
    reg = None
    for scale in (3.0, 1.5, 0.75):
        reg = o3d.pipelines.registration.registration_icp(
            src_pc, tgt_pc, voxel * scale, init, p2l,
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=int(icp_iters)),
        )
        init = reg.transformation
    return reg


def _register_clouds(src_pc, tgt_pc, src_pts, tgt_pts, voxel, icp_iters, use_global):
    def _score(T):
        ev = o3d.pipelines.registration.evaluate_registration(
            src_pc, tgt_pc, voxel * 1.5, T
        )
        return float(ev.fitness), float(ev.inlier_rmse)

    # Build a set of candidate initial poses, refine each with ICP, and keep the
    # best. PCA sign variants disambiguate near-symmetric patches; global
    # RANSAC (when enabled and available) contributes another candidate.
    inits: list[np.ndarray] = list(_pca_init_candidates(src_pts, tgt_pts))
    if use_global:
        try:
            g = _global_ransac(src_pc, tgt_pc, voxel)
            if np.isfinite(g).all() and not np.allclose(g, np.eye(4)):
                inits.insert(0, np.asarray(g, dtype=np.float64))
        except Exception:
            pass

    best_T = np.eye(4)
    best_fit, best_rms = -1.0, float("inf")
    for init in inits:
        reg = _icp_refine(src_pc, tgt_pc, init, voxel, icp_iters)
        T = np.asarray(reg.transformation, dtype=np.float64)
        if not np.isfinite(T).all():
            continue
        fit, rms = _score(T)
        better = fit > best_fit + 1e-6 or (abs(fit - best_fit) <= 1e-6 and rms < best_rms)
        if better:
            best_T, best_fit, best_rms = T, fit, rms
        if best_fit > 0.999 and best_rms < voxel * 0.05:
            break  # already an essentially exact fit

    fitness = max(best_fit, 0.0)
    converged = fitness > 0.3 and np.isfinite(best_T).all()
    return RegistrationResult(
        transform=best_T.tolist(),
        rms=best_rms,
        inlier_fraction=fitness,
        fitness=fitness,
        converged=bool(converged),
    )


def register(source, target, voxel_size: float = 2.0, icp_iters: int = 50,
             use_global: bool = True) -> RegistrationResult:
    """Align ``source`` onto ``target`` (global FPFH+RANSAC then point-to-plane ICP).

    Falls back to a PCA-based initial alignment when ``use_global`` is False or the
    global stage fails. Returns a :class:`RegistrationResult` whose ``transform``
    maps source points into the target frame.
    """
    src_pts = _mesh_points(source)
    tgt_pts = _mesh_points(target)
    src_pc = to_point_cloud(source)
    tgt_pc = to_point_cloud(target)
    return _register_clouds(src_pc, tgt_pc, src_pts, tgt_pts,
                            float(voxel_size), int(icp_iters), bool(use_global))


def register_on_anchor(source, target, anchor, voxel_size: float = 2.0,
                       icp_iters: int = 50, use_global: bool = True) -> RegistrationResult:
    """Register using only an anchor subset of the source surface.

    ``anchor`` is either an integer index array selecting source vertices or a
    boolean mask over them. The returned transform still maps the full source
    into the target frame, but the fit is driven by the anchor points only —
    useful when a stable region (e.g. an unaffected shaft) should drive alignment.
    """
    src_pts = _mesh_points(source)
    tgt_pts = _mesh_points(target)
    idx = np.asarray(anchor)
    if idx.dtype == bool:
        idx = np.where(idx)[0]
    anchor_pts = src_pts[idx]

    src_pc = to_point_cloud(source)
    anchor_pc = o3d.geometry.PointCloud()
    anchor_pc.points = o3d.utility.Vector3dVector(anchor_pts)
    if src_pc.has_normals():
        src_n = np.asarray(src_pc.normals)
        anchor_pc.normals = o3d.utility.Vector3dVector(src_n[idx])
    tgt_pc = to_point_cloud(target)

    return _register_clouds(anchor_pc, tgt_pc, anchor_pts, tgt_pts,
                            float(voxel_size), int(icp_iters), bool(use_global))
