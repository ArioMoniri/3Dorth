"""Interactive analysis pipeline (compute-on-demand) used by the API.

Wraps the core analysis so the UIs can re-run segmentation + thickness with the
*current* parameters, split a bilateral scan into left/right sub-volumes, select
a side/region, and (Mode B) compare two sides. All logic lives here; the API is
a thin wrapper. This is what makes every side-panel parameter actually apply.
"""

from __future__ import annotations

import numpy as np
import pyvista as pv
import SimpleITK as sitk

import core.parameters as P
from core.ingest import ingest_source, load_series_volume
from core.meshing import mask_to_mesh
from core.segmentation import segment_bone
from core.thickness import (
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)


def load_volume_from_source(path, workdir) -> tuple[np.ndarray, tuple, dict]:
    """Ingest a .zip / DICOM dir, pick the bone series, return (arr, spacing, meta)."""
    rep = ingest_source(path, workdir, load_pixels=False)
    bs = rep.bone_series()
    if bs is None:
        raise ValueError("no usable CT series found")
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)
    spacing = tuple(float(s) for s in img.GetSpacing())
    meta = {
        "series": bs.description,
        "shape": list(arr.shape),
        "spacing_mm": [round(s, 3) for s in spacing],
        "laterality": rep.laterality,
        "patient_hash": rep.patient_hash,
    }
    return arr, spacing, meta


def split_sides(arr: np.ndarray, spacing: tuple, margin_mm: float = 12.0) -> dict:
    """Split a bilateral volume into left/right half sub-volumes at the x midline.

    Patient LEFT is the higher-x half here (matches the demo scan's orientation);
    the UI lets the user relabel. Each side keeps a world-space x offset so both
    sides share one coordinate frame (needed for Mode B).
    """
    sx = spacing[0]
    nx = arr.shape[2]
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


def compare_sides(ref, tgt, params) -> dict:
    """Mode B: mirror + register the target side to the reference and colour the
    reference surface by signed deviation. Uses core.registration + core.deviation
    (built separately); returns a clear error until those modules are present."""
    try:
        from core.deviation import deviation_stats, signed_distance
        from core.registration import apply_transform, mirror, register
    except ImportError as e:  # noqa: BLE001
        raise NotImplementedError(f"Mode B modules not available yet: {e}")

    ref_res = analyze_thickness(ref["arr"], ref["spacing"], params, offset_xyz=ref["offset_xyz"])
    tgt_res = analyze_thickness(tgt["arr"], tgt["spacing"], params, offset_xyz=tgt["offset_xyz"])
    ref_mesh, tgt_mesh = ref_res["mesh"], tgt_res["mesh"]
    moving = mirror(tgt_mesh, plane="x") if params.mirror_sagittal else tgt_mesh
    reg = register(moving, ref_mesh, voxel_size=params.reg_voxel_size, icp_iters=params.reg_icp_iters)
    aligned = apply_transform(moving, reg.transform)
    dev = signed_distance(ref_mesh, aligned, convention=params.signed_distance_sign)
    ref_mesh["deviation_mm"] = np.asarray(dev)
    return {
        "mesh": ref_mesh, "stats": deviation_stats(np.asarray(dev)).model_dump(),
        "registration": {"rms": reg.rms, "inlier_fraction": reg.inlier_fraction},
        "scalar": "deviation_mm",
    }
