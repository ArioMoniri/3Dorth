#!/usr/bin/env python3
"""Build outputs/demo/ — the geometry bundle both frontends load.

Produces (all in world millimetres so region toggles + the thickness overlay
align): region_<label>.vtp for the largest bones, thickness.vtp (isolated
humerus coloured by cortical thickness), and manifest.json. De-identified.

Usage:
    .venv/bin/python scripts/build_demo_bundle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.parameters as P  # noqa: E402
from core.ingest import ingest_source, load_series_volume  # noqa: E402
from core.meshing import mask_to_mesh  # noqa: E402
from core.segmentation import segment_bone  # noqa: E402
from core.thickness import (  # noqa: E402
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)

DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"
DEMO = ROOT / "outputs" / "demo"


def region_mesh_world(seg, region, decimate=0.6, smooth=15):
    z0, z1, y0, y1, x0, x1 = region.bbox_zyx
    pad = 2
    zz0, yy0, xx0 = max(z0 - pad, 0), max(y0 - pad, 0), max(x0 - pad, 0)
    sub = seg.labels[zz0:z1 + pad, yy0:y1 + pad, xx0:x1 + pad] == region.label
    mesh = mask_to_mesh(sub, seg.spacing_xyz, smooth_iters=smooth, decimate_fraction=decimate)
    sx, sy, sz = seg.spacing_xyz
    origin = np.array([xx0 * sx, yy0 * sy, zz0 * sz])
    if mesh.n_points:
        mesh.translate(origin.tolist(), inplace=True)
    return mesh, sub, origin


def main() -> int:
    DEMO.mkdir(parents=True, exist_ok=True)
    params = P.default_parameters()
    zips = sorted(DATA.glob("*.zip"))

    rep = ingest_source(zips[0], WORKDIR, load_pixels=False)
    bs = rep.bone_series()
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)
    spacing = tuple(float(s) for s in img.GetSpacing())
    sx, sy, sz = spacing
    seg = segment_bone(arr, spacing, params)
    fov_x = arr.shape[2] * sx

    # isolated limb (abducted humerus) = sizable but laterally compact
    def is_limb(r):
        z0, z1, y0, y1, x0, x1 = r.bbox_zyx
        return 20.0 <= r.volume_mm3 / 1000 <= 300.0 and (x1 - x0) * sx < 0.45 * fov_x
    limbs = [r for r in seg.regions if is_limb(r)]
    humerus = max(limbs, key=lambda r: r.volume_mm3) if limbs else seg.largest_region()

    regions_manifest = []
    for r in seg.regions[:6]:
        mesh, _sub, _o = region_mesh_world(seg, r)
        if not mesh.n_points:
            continue
        fn = f"region_{r.label}.vtp"
        mesh.save(str(DEMO / fn))
        regions_manifest.append({
            "label": r.label, "volume_cm3": round(r.volume_mm3 / 1000, 1),
            "n_points": int(mesh.n_points), "file": fn,
            "is_humerus": r.label == humerus.label,
        })

    # thickness on the isolated humerus (world frame)
    mesh, sub, origin = region_mesh_world(seg, humerus, decimate=0.3)
    verts_world = np.asarray(mesh.points)
    verts_crop = verts_world - origin
    normals = np.asarray(mesh.point_normals)
    lt_iso, iso = local_thickness_map(sub, spacing, iso=0.6)
    th = np.clip(sample_scalar_on_vertices(lt_iso, verts_crop, iso),
                 params.thickness_min_clamp, params.thickness_max_clamp)
    th_ray = np.clip(raycast_thickness_on_vertices(verts_crop, normals, sub, spacing, 15.0),
                     params.thickness_min_clamp, params.thickness_max_clamp)
    mesh["thickness_mm"] = th
    mesh["thickness_raycast_mm"] = th_ray
    mesh.save(str(DEMO / "thickness.vtp"))

    manifest = {
        "source_hash": rep.source_hash,
        "patient_hash": rep.patient_hash,
        "bone_series": bs.description,
        "spacing_mm": [round(s, 3) for s in spacing],
        "note": "Research tooling, not a clinical diagnostic. De-identified.",
        "regions": regions_manifest,
        "thickness": {
            "file": "thickness.vtp", "scalar": "thickness_mm",
            "region_label": humerus.label,
            "mean": round(float(np.mean(th)), 3), "median": round(float(np.median(th)), 3),
            "sd": round(float(np.std(th)), 3),
            "min": round(float(np.min(th)), 3), "max": round(float(np.max(th)), 3),
            "colorbar_range_mm": [params.mode_a_range_min, params.mode_a_range_max],
            "colorbar_steps": params.mode_a_colorbar_steps,
            "colormap": params.mode_a_colormap,
        },
    }
    (DEMO / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Demo bundle -> {DEMO}")
    print(f"  {len(regions_manifest)} region meshes + thickness.vtp")
    print(f"  humerus region {humerus.label}: thickness mean {manifest['thickness']['mean']} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
