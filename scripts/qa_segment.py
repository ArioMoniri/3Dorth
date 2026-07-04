#!/usr/bin/env python3
"""Phase 1 gate: segment the real bone volume, label regions, mesh them, and
save QA renders (distinct-color regions + one highlighted region, like the CT
reconstruction screenshot). De-identified.

Usage:
    .venv/bin/python scripts/qa_segment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

import core.parameters as P  # noqa: E402
from core.ingest import ingest_source, load_series_volume  # noqa: E402
from core.meshing import mask_to_mesh  # noqa: E402
from core.segmentation import segment_bone  # noqa: E402

pv.OFF_SCREEN = True
DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

# distinct, print-friendly palette for regions
PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#aec7e8", "#ffbb78",
]


def mesh_region(seg, region, decimate=0.5) -> pv.PolyData:
    """Mesh one region by cropping to its bbox (fast), then place in world mm."""
    z0, z1, y0, y1, x0, x1 = region.bbox_zyx
    pad = 1
    zz0, yy0, xx0 = max(z0 - pad, 0), max(y0 - pad, 0), max(x0 - pad, 0)
    sub = seg.labels[zz0:z1 + pad, yy0:y1 + pad, xx0:x1 + pad] == region.label
    mesh = mask_to_mesh(sub, seg.spacing_xyz, smooth_iters=15, decimate_fraction=decimate)
    if mesh.n_points:
        sx, sy, sz = seg.spacing_xyz
        mesh.translate([xx0 * sx, yy0 * sy, zz0 * sz], inplace=True)
    return mesh


def main() -> int:
    OUT.mkdir(exist_ok=True)
    zips = sorted(DATA.glob("*.zip"))
    if not zips:
        print(f"No zips in {DATA}")
        return 1

    print("Ingesting + selecting bone series ...")
    rep = ingest_source(zips[0], WORKDIR, load_pixels=False)
    bs = rep.bone_series()
    print(f"  bone series: '{bs.description}'  {bs.n_instances} slices  "
          f"{bs.rows}x{bs.cols}  thk={bs.slice_thickness}mm")

    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)  # (z,y,x) HU
    spacing_xyz = tuple(float(s) for s in img.GetSpacing())  # (sx,sy,sz)
    print(f"  volume {arr.shape} (z,y,x)  spacing {tuple(round(s,3) for s in spacing_xyz)} mm  "
          f"HU[{arr.min():.0f},{arr.max():.0f}]")

    params = P.default_parameters()
    print(f"Segmenting bone (HU {params.hu_lower}-{params.hu_upper}, "
          f"island>={params.island_min_voxels}) ...")
    seg = segment_bone(arr, spacing_xyz, params)
    print(f"  {seg.n_regions} regions, metal fraction {seg.metal_fraction:.2e}")

    print("\n  REGION TABLE (top 12 by volume)")
    print("  lbl |   voxels |  vol_cm3 | extent_mm (x,y,z)      | centroid_x(mm)  side")
    mid_x = arr.shape[2] * spacing_xyz[0] / 2.0
    for r in seg.regions[:12]:
        z0, z1, y0, y1, x0, x1 = r.bbox_zyx
        ext = ((x1 - x0) * spacing_xyz[0], (y1 - y0) * spacing_xyz[1], (z1 - z0) * spacing_xyz[2])
        cx_mm = r.centroid_zyx[2] * spacing_xyz[0]
        side = "R" if cx_mm < mid_x else "L"  # provisional; confirm with user
        print(f"  {r.label:3d} | {r.n_voxels:8d} | {r.volume_mm3/1000:8.1f} | "
              f"({ext[0]:5.1f},{ext[1]:5.1f},{ext[2]:5.1f}) | {cx_mm:8.1f}      {side}")

    # ---- mesh top regions and render ----
    n_show = min(8, seg.n_regions)
    print(f"\nMeshing top {n_show} regions and rendering ...")
    meshes = []
    for r in seg.regions[:n_show]:
        m = mesh_region(seg, r)
        if m.n_points:
            meshes.append((r.label, m))
    print(f"  meshed {len(meshes)} regions")

    try:
        # (1) distinct-color region view
        pl = pv.Plotter(off_screen=True, window_size=(1300, 950))
        pl.set_background("white")
        for i, (lbl, m) in enumerate(meshes):
            pl.add_mesh(m, color=PALETTE[i % len(PALETTE)], smooth_shading=True,
                        specular=0.2, label=f"region {lbl}")
        pl.add_axes(line_width=3)
        pl.camera_position = "xz"
        pl.screenshot(str(OUT / "phase1_regions.png"))
        pl.close()

        # (2) largest region highlighted (like the CT screenshot): orange vs neutral
        pl = pv.Plotter(off_screen=True, window_size=(1300, 950))
        pl.set_background("white")
        for i, (lbl, m) in enumerate(meshes):
            if i == 0:
                pl.add_mesh(m, color="#ff8c1a", smooth_shading=True, specular=0.3)
            else:
                pl.add_mesh(m, color="#3a3f7a", opacity=1.0, smooth_shading=True)
        pl.add_axes(line_width=3)
        pl.camera_position = "xz"
        pl.screenshot(str(OUT / "phase1_highlight.png"))
        pl.close()
        print(f"  wrote {OUT/'phase1_regions.png'} and {OUT/'phase1_highlight.png'}")
    except Exception as e:  # noqa: BLE001
        print(f"  RENDER WARNING: {e} (region table + meshes still valid)")

    # save largest region mesh for later phases (gitignored)
    if meshes:
        meshes[0][1].save(str(OUT / "phase1_largest.ply"))
        print(f"  saved largest-region mesh -> {OUT/'phase1_largest.ply'} "
              f"({meshes[0][1].n_points} pts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
