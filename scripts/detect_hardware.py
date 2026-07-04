#!/usr/bin/env python3
"""Try to infer the operated side by localizing high-density (metal/hardware)
voxels — e.g. a metallic suture anchor. Honest about inconclusive results:
bioabsorbable/PEEK anchors are radiolucent and cannot be seen on CT.

Usage:
    .venv/bin/python scripts/detect_hardware.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ingest import ingest_source, load_series_volume  # noqa: E402

DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"


def main() -> int:
    zips = sorted(DATA.glob("*.zip"))
    rep = ingest_source(zips[0], WORKDIR, load_pixels=False)
    bs = rep.bone_series()
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)  # (z,y,x)
    sx, sy, sz = (float(s) for s in img.GetSpacing())
    mid_x_mm = arr.shape[2] * sx / 2.0

    print("\n" + "=" * 70)
    print("  HARDWARE / OPERATED-SIDE DETECTION")
    print("=" * 70)
    print(f"  volume {arr.shape} (z,y,x)  spacing ({sx:.3f},{sy:.3f},{sz:.3f}) mm")
    print(f"  HU range [{arr.min():.0f}, {arr.max():.0f}]  midline x = {mid_x_mm:.0f} mm")
    print("  (patient RIGHT = x < midline, LEFT = x > midline, provisional)\n")

    # Dense cortical bone tops out ~1900-2000 HU; metal implants go far higher
    # (titanium ~3000+, saturating at 3071). Scan several thresholds.
    for thr in (2000, 2500, 3000):
        hi = arr >= thr
        n = int(hi.sum())
        if n == 0:
            print(f"  >= {thr:4d} HU : 0 voxels")
            continue
        lbl, ncomp = ndimage.label(hi)
        sizes = np.bincount(lbl.ravel())
        sizes[0] = 0
        big = np.argsort(sizes)[::-1][:5]
        print(f"  >= {thr:4d} HU : {n} voxels in {ncomp} clusters")
        for c in big:
            if sizes[c] == 0:
                continue
            cz, cy, cx = ndimage.center_of_mass(lbl == c)
            side = "RIGHT" if cx * sx < mid_x_mm else "LEFT"
            vol_mm3 = sizes[c] * sx * sy * sz
            print(f"      cluster: {sizes[c]:5d} vox ({vol_mm3:7.1f} mm^3)  "
                  f"x={cx*sx:6.1f}mm z={cz*sz:6.1f}mm  -> {side}")

    # Side balance of the highest-density voxels (>= 2500 HU)
    hi = arr >= 2500
    if hi.sum() > 0:
        zz, yy, xx = np.where(hi)
        x_mm = xx * sx
        rt = int((x_mm < mid_x_mm).sum())
        lt = int((x_mm >= mid_x_mm).sum())
        print(f"\n  >=2500 HU voxel balance:  RIGHT={rt}  LEFT={lt}")
        verdict = ("RIGHT" if rt > 3 * max(lt, 1) else
                   "LEFT" if lt > 3 * max(rt, 1) else "inconclusive")
        print(f"  provisional operated-side signal: {verdict}")
    else:
        print("\n  No >=2500 HU voxels: no clear metallic hardware.")
        verdict = "inconclusive (no metal; anchor may be bioabsorbable/PEEK)"
        print(f"  provisional operated-side signal: {verdict}")

    print("\n  NOTE: CT cannot see radiolucent (bioabsorbable/PEEK) anchors. If the")
    print("  signal is inconclusive, the operated side must be confirmed clinically.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
