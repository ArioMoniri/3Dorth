"""Interactive analysis pipeline (compute-on-demand) used by the API.

Wraps the core analysis so the UIs can re-run segmentation + thickness with the
*current* parameters, split a bilateral scan into left/right sub-volumes, select
a side/region, and (Mode B) compare two sides. All logic lives here; the API is
a thin wrapper. This is what makes every side-panel parameter actually apply.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
import SimpleITK as sitk

from core.ingest import (
    MESH_EXTENSIONS,
    NIFTI_EXTENSIONS,
    ingest_source,
    is_nifti,
    load_nifti_volume,
    load_series_volume,
)
from core.ingest import load_mesh_source as _load_mesh_source
from core.meshing import mask_to_mesh
from core.segmentation import segment_bone
from core.thickness import (
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)

# Everything the upload endpoint / ingest layer knows how to open. DICOM archives
# and directories come in as ``.zip`` (or a bare dir), NIfTI as ``.nii``/``.nii.gz``,
# and surface meshes as ``.stl``/``.ply``/``.obj``/``.vtp``.
SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = (".zip",) + NIFTI_EXTENSIONS + MESH_EXTENSIONS


def load_volume_from_source(path, workdir) -> tuple[np.ndarray, tuple, dict]:
    """Load a scan volume as ``(arr[z, y, x] float32 HU, spacing (sx, sy, sz), meta)``.

    Handles a DICOM ``.zip`` / DICOM directory (unchanged) **and** a NIfTI
    ``.nii`` / ``.nii.gz`` file. NIfTI is read with ``SimpleITK.ReadImage`` into
    the identical array/spacing convention, so downstream segmentation and
    thickness work without changes. ``meta`` always carries a ``'format'`` key.
    """
    if is_nifti(path):
        arr, spacing, meta = load_nifti_volume(path)
        # keep the keys existing callers already read on the DICOM path
        meta.setdefault("series", Path(path).name)
        meta.setdefault("laterality", "unknown")
        meta.setdefault("patient_hash", "unknown0")
        return arr, spacing, meta

    rep = ingest_source(path, workdir, load_pixels=False)
    bs = rep.bone_series()
    if bs is None:
        raise ValueError("no usable CT series found")
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)
    spacing = tuple(float(s) for s in img.GetSpacing())
    meta = {
        "format": "dicom",
        "series": bs.description,
        "shape": list(arr.shape),
        "spacing_mm": [round(s, 3) for s in spacing],
        "laterality": rep.laterality,
        "patient_hash": rep.patient_hash,
    }
    return arr, spacing, meta


def load_mesh_source(path) -> pv.PolyData:
    """Load a surface mesh (``.stl`` / ``.ply`` / ``.obj`` / ``.vtp``) as PolyData.

    A **surface** input for Mode-B mesh-vs-mesh comparison and viewing. Cortical
    thickness (Mode A) needs a *volume* (a wall to measure), not a bare surface,
    so a mesh loaded here cannot be run through thickness analysis. Thin wrapper
    over :func:`core.ingest.load_mesh_source`.
    """
    return _load_mesh_source(path)


def _bone_mask_for_geometry(arr: np.ndarray, hu_lower: float = 226.0,
                            hu_upper: float = 3000.0) -> np.ndarray:
    """Coarse bone mask for geometry heuristics (side detection).

    Uses the paper's default lower HU bound but is only a rough, denoised mask —
    not the analysis segmentation. Nothing here assumes a particular bone.
    """
    m = (arr >= hu_lower) & (arr <= hu_upper)
    return m


def detect_bilateral(arr: np.ndarray, spacing: tuple,
                     hu_lower: float = 226.0, min_side_fraction: float = 0.20,
                     gap_fraction: float = 0.06) -> bool:
    """Heuristically decide whether a scan holds bone on BOTH sides of the x-midline.

    Bilateral scans (e.g. both shoulders in one field of view) show two separated
    bone masses straddling the x centre with a relatively empty column between
    them. A single-sided scan has essentially all its bone mass on one side.

    Returns ``True`` when both the left and right halves each carry at least
    ``min_side_fraction`` of the bone voxels *and* the central column is
    comparatively sparse (a real gap between two structures), else ``False``.
    Makes no assumption about which bone is present.
    """
    mask = _bone_mask_for_geometry(arr, hu_lower)
    total = int(mask.sum())
    if total == 0:
        return False

    # Bone voxel count per x column, collapsed over z and y.
    col = mask.sum(axis=(0, 1)).astype(np.float64)  # shape (nx,)
    nx = col.size
    mid = nx // 2
    left_mass = float(col[mid:].sum())
    right_mass = float(col[:mid].sum())
    frac_left = left_mass / total
    frac_right = right_mass / total
    if min(frac_left, frac_right) < min_side_fraction:
        return False

    # Require a genuine central gap: the busiest central column should be well
    # below the peak column density, indicating two separated masses.
    band = max(1, int(round(0.08 * nx)))
    central = col[max(mid - band, 0):min(mid + band, nx)]
    peak = float(col.max())
    if peak <= 0:
        return False
    central_ratio = float(central.max()) / peak
    return central_ratio <= (1.0 - gap_fraction) or central_ratio < 0.85


def split_sides(arr: np.ndarray, spacing: tuple, margin_mm: float = 12.0,
                layout: str = "auto") -> dict:
    """Split a scan into per-side sub-volumes, auto-detecting bilateral vs single.

    For a **bilateral** scan (bone on both sides of the x-midline) this returns
    ``{'right': {...}, 'left': {...}}`` exactly as before — two overlapping half
    sub-volumes with world-space x offsets so both share one coordinate frame
    (needed for Mode B). Patient LEFT is the higher-x half here (matches the demo
    scan's orientation); the UI lets the user relabel.

    For a **single-sided** scan it returns ``{'full': {...}}`` — the whole volume
    with a zero offset. The return dict always maps side-name -> a dict with
    ``arr`` / ``spacing`` / ``offset_xyz`` / ``side``, so callers that iterate
    ``.keys()`` and index by side name keep working unchanged.
    """
    sx = spacing[0]
    nx = arr.shape[2]

    # layout: "auto" uses the geometric detector; "bilateral"/"single" force it
    # (a bilateral limb CT whose thoracic skeleton fills the midline defeats the
    # auto gap test, so the caller/UI can override).
    bilateral = layout == "bilateral" or (layout == "auto" and detect_bilateral(arr, spacing))
    if not bilateral:
        return {
            "full": {"arr": np.ascontiguousarray(arr), "spacing": spacing,
                     "offset_xyz": (0.0, 0.0, 0.0), "side": "full"},
        }

    mid = nx // 2
    m = int(round(margin_mm / sx))
    right_hi = min(mid + m, nx)
    left_lo = max(mid - m, 0)
    return {
        "right": {"arr": np.ascontiguousarray(arr[:, :, :right_hi]), "spacing": spacing,
                  "offset_xyz": (0.0, 0.0, 0.0), "side": "right"},
        "left": {"arr": np.ascontiguousarray(arr[:, :, left_lo:]), "spacing": spacing,
                 "offset_xyz": (left_lo * sx, 0.0, 0.0), "side": "left"},
    }


def _pick_limb_region(seg, shape, spacing):
    """Best default region for a limb bone: sizable but laterally compact."""
    sx = spacing[0]
    fov_x = shape[2] * sx
    cands = [r for r in seg.regions
             if 15.0 <= r.volume_mm3 / 1000 <= 400.0
             and (r.bbox_zyx[5] - r.bbox_zyx[4]) * sx < 0.7 * fov_x]
    return max(cands, key=lambda r: r.volume_mm3) if cands else seg.largest_region()


def _stats(v: np.ndarray) -> dict:
    return {
        "mean": round(float(np.mean(v)), 3), "median": round(float(np.median(v)), 3),
        "sd": round(float(np.std(v)), 3), "rms": round(float(np.sqrt(np.mean(v ** 2))), 3),
        "min": round(float(np.min(v)), 3), "max": round(float(np.max(v)), 3),
        "n": int(v.size),
    }


def analyze_thickness(arr, spacing, params, region_label=None, offset_xyz=(0.0, 0.0, 0.0)) -> dict:
    """Segment with the current params, pick/keep a region, compute its cortical
    thickness map, and return a world-placed mesh + stats + the region list."""
    seg = segment_bone(arr, spacing, params)
    if seg.n_regions == 0:
        raise ValueError("no bone segmented at these thresholds")
    region = next((r for r in seg.regions if r.label == region_label), None)
    if region is None:
        region = _pick_limb_region(seg, arr.shape, spacing)

    z0, z1, y0, y1, x0, x1 = region.bbox_zyx
    pad = 2
    zz0, yy0, xx0 = max(z0 - pad, 0), max(y0 - pad, 0), max(x0 - pad, 0)
    sub = seg.labels[zz0:z1 + pad, yy0:y1 + pad, xx0:x1 + pad] == region.label

    decimate = params.mesh_decimate_fraction or 0.3
    mesh = mask_to_mesh(sub, spacing, smooth_iters=params.mesh_smooth_iters,
                        decimate_fraction=decimate)
    verts = np.asarray(mesh.points)
    normals = np.asarray(mesh.point_normals)

    lo, hi = params.thickness_min_clamp, params.thickness_max_clamp
    iso = max(0.6, min(spacing))
    if params.thickness_algorithm == "ray_cast":
        th = raycast_thickness_on_vertices(verts, normals, sub, spacing, max_mm=hi + 5)
    else:
        lt_iso, iso = local_thickness_map(sub, spacing, iso=iso)
        th = sample_scalar_on_vertices(lt_iso, verts, iso)
    th = np.clip(th, lo, hi)
    mesh["thickness_mm"] = th

    sx, sy, sz = spacing
    mesh.translate([xx0 * sx + offset_xyz[0], yy0 * sy + offset_xyz[1], zz0 * sz + offset_xyz[2]],
                   inplace=True)

    return {
        "mesh": mesh,
        "region_label": region.label,
        "stats": _stats(th),
        "regions": [{"label": r.label, "volume_cm3": round(r.volume_mm3 / 1000, 1)}
                    for r in seg.regions[:12]],
        "metal_fraction": round(seg.metal_fraction, 6),
    }


def _compose_transforms(auto, manual):
    """Return ``manual @ auto`` as a 4x4 float array (both 4x4-shaped inputs).

    The auto-registration transform maps the moving surface into the reference
    frame; the manual nudge is applied *after* it, so composition is left-multiply.
    """
    A = np.asarray(auto, dtype=np.float64).reshape(4, 4)
    if manual is None:
        return A
    M = np.asarray(manual, dtype=np.float64)
    if M.shape != (4, 4):
        raise ValueError(f"manual_transform must be 4x4, got shape {M.shape}")
    return M @ A


def compare_sides(ref, tgt, params, *, manual_transform=None) -> dict:
    """Mode B: mirror + register the target side to the reference and colour the
    reference surface by signed deviation.

    ``manual_transform`` (optional 4x4 list) is a user "nudge" composed with the
    auto-registration transform and applied *after* ICP, letting the operator
    fine-tune the alignment. When ``None`` the behaviour is identical to before.

    ``params.mode_b_reference`` chooses which scan is on top: the default
    ``'scan_a'`` keeps ``ref`` as the reference surface being coloured; ``'scan_b'``
    swaps the roles so ``tgt`` becomes the reference (which also flips the sign of
    the reported deviation, since reference/target are interchanged).
    """
    try:
        from core.deviation import deviation_stats, signed_distance
        from core.registration import apply_transform, mirror, register
    except ImportError as e:  # noqa: BLE001
        raise NotImplementedError(f"Mode B modules not available yet: {e}")

    # "which one on top": scan_b makes the target the reference surface.
    if getattr(params, "mode_b_reference", "scan_a") == "scan_b":
        ref, tgt = tgt, ref

    ref_res = analyze_thickness(ref["arr"], ref["spacing"], params, offset_xyz=ref["offset_xyz"])
    tgt_res = analyze_thickness(tgt["arr"], tgt["spacing"], params, offset_xyz=tgt["offset_xyz"])
    ref_mesh, tgt_mesh = ref_res["mesh"], tgt_res["mesh"]
    moving = mirror(tgt_mesh, plane="x") if params.mirror_sagittal else tgt_mesh
    reg = register(moving, ref_mesh, voxel_size=params.reg_voxel_size, icp_iters=params.reg_icp_iters)
    transform = _compose_transforms(reg.transform, manual_transform)
    aligned = apply_transform(moving, transform)
    dev = signed_distance(ref_mesh, aligned, convention=params.signed_distance_sign)
    ref_mesh["deviation_mm"] = np.asarray(dev)
    return {
        "mesh": ref_mesh, "stats": deviation_stats(np.asarray(dev)).model_dump(),
        "registration": {"rms": reg.rms, "inlier_fraction": reg.inlier_fraction,
                         "manual_adjusted": manual_transform is not None},
        "scalar": "deviation_mm",
    }
