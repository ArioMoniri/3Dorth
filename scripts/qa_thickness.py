#!/usr/bin/env python3
"""Phase 2 gate: cortical thickness on the isolated humerus.

Local thickness (primary) vs ray-cast (validation), agreement report, and a
Fig-2-faithful render (green->red discrete mm colorbar, triad, white bg).
De-identified. Writes outputs/phase2_thickness.png + .vtp + stats.

Usage:
    .venv/bin/python scripts/qa_thickness.py
"""
from __future__ import annotations

import json
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
from core.thickness import (  # noqa: E402
    agreement,
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)
from core.viz import get_cmap  # noqa: E402

pv.OFF_SCREEN = True
DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"
OUT = ROOT / "outputs"


def pick_isolated_limb(seg, fov_x_mm: float):
    """Region with sizable volume but a laterally compact footprint = an
    isolated limb bone (the abducted humerus), not the connected thorax."""
    sx, sy, sz = seg.spacing_xyz
    cands = []
    for r in seg.regions:
        z0, z1, y0, y1, x0, x1 = r.bbox_zyx
        x_ext = (x1 - x0) * sx
        vol_cm3 = r.volume_mm3 / 1000.0
        if 20.0 <= vol_cm3 <= 300.0 and x_ext < 0.45 * fov_x_mm:
            cands.append((r, vol_cm3))
    if not cands:
        return seg.largest_region()
    return max(cands, key=lambda c: c[1])[0]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    params = P.default_parameters()
    zips = sorted(DATA.glob("*.zip"))

    rep = ingest_source(zips[0], WORKDIR, load_pixels=False)
    bs = rep.bone_series()
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)
    spacing = tuple(float(s) for s in img.GetSpacing())
    sx, sy, sz = spacing
    seg = segment_bone(arr, spacing, params)

    region = pick_isolated_limb(seg, arr.shape[2] * sx)
    print(f"Analyzing isolated bone: region {region.label}, "
          f"{region.volume_mm3/1000:.1f} cm^3")

    # crop to the region bbox (+pad)
    z0, z1, y0, y1, x0, x1 = region.bbox_zyx
    pad = 2
    zz0, yy0, xx0 = max(z0 - pad, 0), max(y0 - pad, 0), max(x0 - pad, 0)
    sub = seg.labels[zz0:z1 + pad, yy0:y1 + pad, xx0:x1 + pad] == region.label
    print(f"  crop {sub.shape} (z,y,x), {int(sub.sum())} bone voxels")

    # outer surface mesh (crop frame: index 0 -> 0 mm)
    mesh = mask_to_mesh(sub, spacing, smooth_iters=15, decimate_fraction=0.3)
    verts = np.asarray(mesh.points)
    normals = np.asarray(mesh.point_normals)
    print(f"  surface: {mesh.n_points} verts, {mesh.n_faces} faces")

    # primary: local thickness (Hildebrand-Ruegsegger) on isotropic resample
    print("  computing local thickness (isotropic resample) ...")
    lt_iso, iso = local_thickness_map(sub, spacing, iso=0.6)
    th_local = sample_scalar_on_vertices(lt_iso, verts, iso, order=1)

    # validation: ray-cast along inward normal on the native mask
    print("  computing ray-cast thickness (validation) ...")
    th_ray = raycast_thickness_on_vertices(verts, normals, sub, spacing, max_mm=15.0)

    lo, hi = params.thickness_min_clamp, params.thickness_max_clamp
    th_local = np.clip(th_local, lo, hi)
    th_ray = np.clip(th_ray, lo, hi)

    # agreement (validation surfaces only where ray-cast actually exited)
    valid = th_ray < (15.0 - 1e-3)
    ag = agreement(th_local[valid], th_ray[valid])
    print("\n  METHOD AGREEMENT (local vs ray-cast, n={})".format(ag.n))
    print(f"    mean|diff|={ag.mean_abs_diff_mm:.3f} mm  median|diff|="
          f"{ag.median_abs_diff_mm:.3f} mm  RMS={ag.rms_diff_mm:.3f} mm  r={ag.pearson_r:.3f}")
    print(f"    mean local={ag.mean_a_mm:.3f} mm  mean ray={ag.mean_b_mm:.3f} mm")

    def stats(v):
        return dict(mean=float(np.mean(v)), median=float(np.median(v)),
                    sd=float(np.std(v)), rms=float(np.sqrt(np.mean(v**2))),
                    min=float(np.min(v)), max=float(np.max(v)))

    s_local = stats(th_local)
    print("\n  LOCAL-THICKNESS SURFACE STATS (mm):")
    print(f"    mean={s_local['mean']:.2f}  median={s_local['median']:.2f}  "
          f"SD={s_local['sd']:.2f}  RMS={s_local['rms']:.2f}  "
          f"min={s_local['min']:.2f}  max={s_local['max']:.2f}")

    # ---- Fig-2-faithful render ----
    mesh["thickness_mm"] = th_local
    vmin, vmax = params.mode_a_range_min, params.mode_a_range_max
    steps = params.mode_a_colorbar_steps
    try:
        pl = pv.Plotter(off_screen=True, window_size=(1000, 1250))
        pl.set_background("white")
        sargs = dict(title="Cortical thickness (mm)", vertical=True,
                     position_x=0.86, position_y=0.08, height=0.82, width=0.07,
                     n_labels=steps, fmt="%.4f", label_font_size=18,
                     title_font_size=20, color="black")
        pl.add_mesh(mesh, scalars="thickness_mm",
                    cmap=get_cmap(params.mode_a_colormap), n_colors=steps,
                    clim=[vmin, vmax], scalar_bar_args=sargs, smooth_shading=True)
        pl.add_axes(line_width=3, labels_off=False)
        pl.camera_position = "xz"
        pl.screenshot(str(OUT / "phase2_thickness.png"))
        pl.close()
        print(f"\n  wrote {OUT/'phase2_thickness.png'}")
    except Exception as e:  # noqa: BLE001
        print(f"\n  RENDER WARNING: {e}")

    mesh.save(str(OUT / "phase2_thickness.vtp"))
    (OUT / "phase2_thickness_stats.json").write_text(json.dumps(
        {"region_label": region.label, "region_volume_cm3": region.volume_mm3 / 1000,
         "iso_mm": iso, "clamp_mm": [lo, hi], "colorbar_range_mm": [vmin, vmax],
         "local_stats_mm": s_local, "agreement": ag.model_dump()}, indent=2))
    print(f"  wrote {OUT/'phase2_thickness.vtp'} and stats json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
