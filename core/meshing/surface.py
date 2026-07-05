"""Surface extraction from a binary mask.

Marching cubes in millimetres (spacing-aware), then optional Taubin smoothing
(shape-preserving) and decimation. Returns a pyvista ``PolyData`` in (x, y, z)
world millimetres so downstream viewers and distance queries share one frame.

An OPTIONAL 3-matic-equivalent reconstruction pass (:func:`reconstruct_surface`)
can wrap the raw marching-cubes shell into a clean, watertight, evenly-triangulated
surface for the paper's smooth render. It is **DISPLAY-ONLY cosmetics**: it never
changes the mask and cortical thickness is always computed on the raw thresholded
mask at native spacing, then re-sampled onto the reconstructed vertices so the
scalar survives remeshing. It does NOT create or alter any measurement.
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
    reconstruct: str = "raw",
    reconstruct_target_verts: int = 30_000,
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

    ``reconstruct`` selects an OPTIONAL 3-matic-equivalent DISPLAY-ONLY finishing
    pass applied after marching cubes / Taubin (see :func:`reconstruct_surface`):
      * ``"raw"``   — no reconstruction (marching-cubes shell as-is);
      * ``"smooth"``— watertight repair + windowed-sinc smoothing only;
      * ``"wrap"``  — full pipeline: repair + windowed-sinc + isotropic remesh
        (even triangulation) + decimate to budget.
    All are cosmetic wraps — the mask boundary is unchanged and cortical thickness
    is computed elsewhere on the raw mask at its own spacing.
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

    mode = str(reconstruct or "raw").lower()
    if mode in ("smooth", "wrap"):
        # Full 3-matic-equivalent finishing pass. The isotropic remesh + budget
        # decimation is only done for "wrap"; "smooth" stops after windowed-sinc.
        mesh = reconstruct_surface(
            mesh,
            target_verts=int(reconstruct_target_verts),
            remesh=(mode == "wrap"),
            decimate_fraction=float(decimate_fraction or 0.0),
        )
    else:
        if decimate_fraction and decimate_fraction > 0:
            mesh = mesh.decimate(float(decimate_fraction))
        mesh = mesh.clean()

    mesh.compute_normals(inplace=True, auto_orient_normals=True)
    return mesh


def _resample_point_scalars(src: pv.PolyData, dst: pv.PolyData) -> None:
    """Copy every point scalar from ``src`` onto ``dst`` by nearest source vertex.

    Remeshing / decimation destroys the original vertex indexing, so any per-vertex
    field (cortical thickness) must be transferred back onto the new vertices. We use
    a KDTree nearest-neighbour lookup from the pre-remesh surface — cheap, and exact
    at coincident points. This is a DISPLAY re-sampling of an already-computed scalar;
    it does not recompute or alter the measurement.
    """
    if src.n_points == 0 or dst.n_points == 0:
        return
    keys = [k for k in src.point_data.keys()]
    if not keys:
        return
    from scipy.spatial import cKDTree
    tree = cKDTree(np.asarray(src.points, dtype=float))
    _, idx = tree.query(np.asarray(dst.points, dtype=float), k=1)
    for k in keys:
        vals = np.asarray(src.point_data[k])
        dst.point_data[k] = vals[idx]


def _make_watertight(mesh: pv.PolyData, hole_size: float) -> pv.PolyData:
    """Repair to a closed manifold: vtk fill_holes + clean, then open3d
    non-manifold / duplicate removal. Best-effort — never raises on a mesh that
    cannot be perfectly closed; returns the most-repaired version available."""
    out = mesh
    try:
        out = out.clean()
        filled = out.fill_holes(hole_size)
        if filled is not None and filled.n_points:
            out = filled.clean()
    except Exception:  # noqa: BLE001 — repair is best-effort/cosmetic
        pass

    # open3d pass: drop duplicated verts/triangles, degenerate + non-manifold edges.
    try:
        import open3d as o3d

        tri = out.triangulate()
        pts = np.asarray(tri.points, dtype=np.float64)
        faces = tri.faces.reshape(-1, 4)[:, 1:].astype(np.int64)
        if len(pts) and len(faces):
            om = o3d.geometry.TriangleMesh(
                o3d.utility.Vector3dVector(pts),
                o3d.utility.Vector3iVector(faces),
            )
            om.remove_duplicated_vertices()
            om.remove_duplicated_triangles()
            om.remove_degenerate_triangles()
            om.remove_non_manifold_edges()
            om.remove_unreferenced_vertices()
            v = np.asarray(om.vertices)
            f = np.asarray(om.triangles)
            if len(v) and len(f):
                faces_pv = np.hstack(
                    [np.full((f.shape[0], 1), 3, dtype=np.int64), f.astype(np.int64)]
                ).ravel()
                rebuilt = pv.PolyData(v, faces_pv)
                _resample_point_scalars(out, rebuilt)
                out = rebuilt
    except Exception:  # noqa: BLE001
        pass
    return out


def reconstruct_surface(
    mesh: pv.PolyData,
    target_verts: int = 30_000,
    *,
    remesh: bool = True,
    decimate_fraction: float = 0.0,
    passband: float = 0.05,
    sinc_iters: int = 20,
    thickness_key: str = "thickness_mm",
) -> pv.PolyData:
    """3-matic-EQUIVALENT DISPLAY-ONLY surface reconstruction.

    Turns a raw marching-cubes shell into a clean, watertight, evenly-triangulated
    surface (the paper's smooth look). Pipeline:

      1. **Watertight repair** — vtk ``fill_holes`` + ``clean`` and open3d
         non-manifold / duplicate / degenerate removal → a closed manifold.
      2. **Windowed-sinc smoothing** — ``vtkWindowedSincPolyDataFilter`` with
         normalized coordinates, moderate ``passband`` (~0.05), ~20 iterations.
         Shape-preserving; removes residual staircase Taubin can't.
      3. **Isotropic remesh** (``remesh=True``) — pyacvd ``Clustering`` →
         ``subdivide`` → cluster to ``target_verts`` → ``create_mesh`` for even
         triangulation. When remeshing, ``target_verts`` IS the render budget.
      4. **Decimate to budget** — ``decimate_pro`` down to ``decimate_fraction``,
         used ONLY when not remeshing (a decimate after ACVD would undo the even
         triangulation), preserving the thickness scalar.

    CRITICAL: any per-vertex scalar (``thickness_key`` and friends) is re-sampled
    onto the new vertices after every topology-changing step via nearest-neighbour
    from the pre-step surface, so the thickness colouring SURVIVES remeshing. This
    is a cosmetic re-sampling of an already-computed field — it does not recompute
    or fabricate any measurement. Cortical thickness stays computed on the raw
    thresholded mask at native spacing.

    ``mesh`` should be the marching-cubes surface (optionally Taubin-smoothed).
    Returns a new ``PolyData`` carrying the same point scalars.
    """
    if mesh is None or mesh.n_points == 0:
        return mesh if mesh is not None else pv.PolyData()

    src = mesh  # keep the pre-reconstruction surface as the scalar source of truth

    # hole size scaled to the model so fill_holes closes real gaps, not the shell.
    try:
        diag = float(np.linalg.norm(np.ptp(np.asarray(src.points), axis=0)))
    except Exception:  # noqa: BLE001
        diag = 0.0
    hole_size = max(diag * 0.05, 1.0)

    # 1) watertight repair
    work = _make_watertight(src, hole_size)

    # 2) windowed-sinc smoothing (shape-preserving; kills residual staircase)
    try:
        work_tri = work.triangulate()
    except Exception:  # noqa: BLE001
        work_tri = work
    try:
        import vtk

        sinc = vtk.vtkWindowedSincPolyDataFilter()
        sinc.SetInputData(work_tri)
        sinc.SetNumberOfIterations(int(sinc_iters))
        sinc.SetPassBand(float(passband))
        sinc.NormalizeCoordinatesOn()
        sinc.FeatureEdgeSmoothingOff()
        sinc.BoundarySmoothingOff()
        sinc.NonManifoldSmoothingOff()
        sinc.Update()
        out = pv.wrap(sinc.GetOutput())
        if out is not None and out.n_points:
            _resample_point_scalars(work_tri, out)
            work = out
        else:
            work = work_tri
    except Exception:  # noqa: BLE001 — smoothing is cosmetic; keep repaired mesh
        work = work_tri

    # 3) isotropic remesh to an even triangulation at ~target_verts
    #    When remeshing, ``target_verts`` IS the render budget, so a subsequent
    #    decimate_pro is deliberately skipped: decimate_pro re-introduces the very
    #    triangle-size variance ACVD just removed (verified: CV 0.34 raw -> 0.20
    #    remesh -> 0.51 if decimated after). The even ACVD output IS the budget.
    remeshed_ok = False
    if remesh:
        remeshed = _isotropic_remesh(work, int(target_verts))
        if remeshed is not None and remeshed.n_points:
            _resample_point_scalars(work, remeshed)
            work = remeshed
            remeshed_ok = True

    # 4) decimate to render budget, preserving the scalar — only when we did NOT
    #    remesh (remesh already hit the budget with an even triangulation).
    if (not remeshed_ok) and decimate_fraction and decimate_fraction > 0:
        try:
            pre = work
            dec = work.triangulate().decimate_pro(
                float(decimate_fraction), preserve_topology=True
            )
            if dec is not None and dec.n_points:
                _resample_point_scalars(pre, dec)
                work = dec
        except Exception:  # noqa: BLE001
            pass

    work = work.clean()
    # Final manifold tidy: ACVD's create_mesh can leave a handful of non-manifold
    # edges / duplicate verts. Re-run the open3d/vtk repair so the delivered shell
    # is as close to a closed watertight manifold as we can get (cosmetic).
    work = _make_watertight(work, hole_size)
    _resample_point_scalars(src, work)  # final guarantee the scalar is present/fresh
    return work


def _isotropic_remesh(mesh: pv.PolyData, target_verts: int) -> pv.PolyData | None:
    """Even triangulation via pyacvd (ACVD isotropic clustering).

    Clusters the surface into ~``target_verts`` roughly equal-area cells and rebuilds
    a mesh whose vertices are the cluster centroids — the standard way to get the
    uniform triangle sizing 3-matic produces. Subdivides first when the input is too
    coarse to seed enough clusters. Returns ``None`` on failure so the caller keeps
    the smoothed mesh."""
    try:
        import pyacvd

        tri = mesh.triangulate().clean()
        if tri.n_points == 0:
            return None
        target = max(int(target_verts), 100)
        clus = pyacvd.Clustering(tri)
        # ACVD needs more input points than clusters; subdivide coarse inputs.
        subdiv = 0
        while clus.mesh.n_points < target * 3 and subdiv < 3:
            clus.subdivide(1)
            subdiv += 1
        clus.cluster(target)
        remeshed = clus.create_mesh()
        return remeshed.clean() if remeshed is not None else None
    except Exception:  # noqa: BLE001 — remesh is cosmetic; caller falls back
        return None
