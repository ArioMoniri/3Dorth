#!/usr/bin/env python3
"""Build a DE-IDENTIFIED demo dataset from the local patient DICOMs.

Converts the bone-kernel CT series to NIfTI. NIfTI carries NONE of the DICOM
patient tags (name / ID / birth date / study dates / institution / accession),
so the output is de-identified by construction — no PHI can survive the format
conversion. The volume is cropped to the bone bounding box (dropping surrounding
air) to keep the file small. The result ships with the app as the default demo
so every user (including on a public server) has something to try, with no
patient information.

Usage:
    .venv/bin/python scripts/make_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ingest import ingest_source, load_series_volume  # noqa: E402

DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "demo"
OUT = OUT_DIR / "shoulder_demo.nii.gz"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zips = sorted(DATA.glob("*.zip"))
    if not zips:
        print(f"No patient zip in {DATA}; cannot build demo.")
        return 1

    print("Loading bone-kernel series ...")
    rep = ingest_source(zips[0], WORKDIR, load_pixels=False)
    bs = rep.bone_series()
    img = load_series_volume(bs)
    arr = sitk.GetArrayFromImage(img).astype(np.int16)  # (z,y,x) HU
    spacing = tuple(float(s) for s in img.GetSpacing())

    # Crop to the bone bounding box (+ margin) to drop surrounding air.
    bone = (arr >= 226) & (arr <= 1600)
    zz, yy, xx = np.where(bone)
    mz, my, mx = 6, 10, 10
    z0, z1 = max(int(zz.min()) - mz, 0), min(int(zz.max()) + mz, arr.shape[0])
    y0, y1 = max(int(yy.min()) - my, 0), min(int(yy.max()) + my, arr.shape[1])
    x0, x1 = max(int(xx.min()) - mx, 0), min(int(xx.max()) + mx, arr.shape[2])
    crop = np.ascontiguousarray(arr[z0:z1, y0:y1, x0:x1])
    print(f"  full {arr.shape} -> cropped {crop.shape} (bone bbox + margin)")

    # New image: keep spacing (needed for mm measurements); reset origin/direction
    # (de-identify geometry). NO metadata copied -> no PHI.
    out = sitk.GetImageFromArray(crop)
    out.SetSpacing(spacing)
    out.SetOrigin((0.0, 0.0, 0.0))
    out.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, 1))
    sitk.WriteImage(out, str(OUT), useCompression=True)

    size_mb = OUT.stat().st_size / 1e6
    print(f"  wrote {OUT}  ({size_mb:.1f} MB, de-identified NIfTI)")
    print("  NIfTI format carries no DICOM patient tags -> PHI-free by construction.")
    if size_mb > 80:
        print("  WARNING: file is large for git; consider downsampling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
