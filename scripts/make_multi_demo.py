#!/usr/bin/env python3
"""Generate a DE-IDENTIFIED synthetic *follow-up* demo series.

3Dorth's Mode B compares two or more scans of the same anatomy taken at
different visits (baseline vs follow-up) by anchoring them together and mapping
the signed surface deviation. To demo that out-of-the-box we need a *second*
series — but a real second patient scan carries identifiable information and
must never be committed or bundled. So instead we DERIVE a synthetic follow-up
from the already de-identified bundled demo (``shoulder_demo.nii.gz``):

  1. a small rigid re-positioning (a few mm translation + a few degrees
     rotation), so the registration step has genuine work to do; and
  2. a mild, LOCALISED cortical erosion (~1 voxel shell removed over one
     sub-region), simulating bone resorption between visits — this is the
     non-rigid difference that *survives* registration and shows up as a signed
     (negative / "inside") deviation on the map.

The output is a plain NIfTI volume, which carries no DICOM patient tags; we also
clear the free-text ``descrip`` header field. Nothing here reads or copies any
real patient archive.

Usage (typically run once on the server during setup):
    python scripts/make_multi_demo.py
    python scripts/make_multi_demo.py --source path/in.nii.gz --out path/out.nii.gz \
        --shift-mm 4 --rot-deg 3 --erode-voxels 1
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import SimpleITK as sitk

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "demo" / "shoulder_demo.nii.gz"
DEFAULT_OUT = ROOT / "data" / "demo" / "shoulder_demo_followup.nii.gz"

# HU threshold above which a voxel counts as (cortical) bone for the erosion.
BONE_HU = 200.0
# Value written into eroded voxels — soft-tissue-ish, so the surface recedes.
SOFT_HU = -50.0


def _rigid_transform(center_xyz, shift_mm: float, rot_deg: float) -> sitk.Euler3DTransform:
    """A small rigid re-positioning about the volume centre."""
    t = sitk.Euler3DTransform()
    t.SetCenter(center_xyz)
    r = math.radians(rot_deg)
    # Rotate mostly about the long (through-plane) axis, a touch about the others.
    t.SetRotation(r * 0.25, r * 0.25, r)
    t.SetTranslation((shift_mm, -0.6 * shift_mm, 0.4 * shift_mm))
    return t


def make_followup(
    source: Path,
    out: Path,
    shift_mm: float = 4.0,
    rot_deg: float = 3.0,
    erode_voxels: int = 1,
) -> Path:
    img = sitk.ReadImage(str(source))
    arr = sitk.GetArrayFromImage(img).astype(np.float32)  # (z, y, x)

    # --- localised cortical erosion (simulate a FOCAL resorption lesion) -------
    # Cortical bone is only 1-3 voxels thick, so eroding it everywhere would strip
    # a huge fraction of the bone. Instead we confine the erosion to one small box
    # centred on the bone in the upper region — a focal, bounded change that shows
    # up as a clear localised (negative / "inside") deviation hotspot after the
    # two scans are registered, which is far more illustrative than a global shrink.
    if erode_voxels > 0:
        from scipy import ndimage

        bone = arr > BONE_HU
        eroded = ndimage.binary_erosion(bone, iterations=int(erode_voxels))
        shell = bone & ~eroded  # the ~1-voxel outer cortical shell

        # Focal box: ~40 mm cube around the centroid of the upper-region bone.
        zc = arr.shape[0] // 2
        upper = bone.copy()
        upper[:zc, :, :] = False
        if upper.any():
            cz, cy, cx = (int(round(m)) for m in ndimage.center_of_mass(upper))
        else:  # degenerate fallback
            cz, cy, cx = (3 * arr.shape[0] // 4, arr.shape[1] // 2, arr.shape[2] // 2)
        sz, sy, sx = img.GetSpacing()[2], img.GetSpacing()[1], img.GetSpacing()[0]
        rz, ry, rx = int(20 / sz), int(20 / sy), int(20 / sx)  # ±20 mm
        region = np.zeros_like(bone)
        region[
            max(cz - rz, 0):cz + rz,
            max(cy - ry, 0):cy + ry,
            max(cx - rx, 0):cx + rx,
        ] = True

        arr = np.where(shell & region, SOFT_HU, arr)

    changed = sitk.GetImageFromArray(arr.astype(np.int16))
    changed.CopyInformation(img)

    # --- small rigid re-positioning ------------------------------------------
    size = img.GetSize()
    center_idx = [s / 2.0 for s in size]
    center_xyz = img.TransformContinuousIndexToPhysicalPoint(center_idx)
    tform = _rigid_transform(center_xyz, shift_mm, rot_deg)

    resampled = sitk.Resample(
        changed,
        img,  # same grid / geometry as the reference
        tform,
        sitk.sitkLinear,
        float(arr.min()),  # air fill for out-of-frame voxels
        img.GetPixelID(),
    )

    # --- de-identify: NIfTI has no patient tags; clear the free-text descrip ---
    resampled.EraseMetaData("descrip") if resampled.HasMetaDataKey("descrip") else None
    resampled.SetMetaData("intent_name", "synthetic_followup")

    out.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(resampled, str(out))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--shift-mm", type=float, default=4.0)
    ap.add_argument("--rot-deg", type=float, default=3.0)
    ap.add_argument("--erode-voxels", type=int, default=1)
    args = ap.parse_args()

    if not args.source.exists():
        raise SystemExit(f"source demo not found: {args.source}")

    out = make_followup(
        args.source,
        args.out,
        shift_mm=args.shift_mm,
        rot_deg=args.rot_deg,
        erode_voxels=args.erode_voxels,
    )
    print(f"wrote de-identified synthetic follow-up: {out}")


if __name__ == "__main__":
    main()
