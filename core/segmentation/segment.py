"""Bone segmentation and region labeling.

Threshold the HU volume to the bone window (defaults 226-1600), drop noise
islands, and label connected components so the UI can show/hide/highlight
individual bones or sub-regions (the "filter parts after loading" capability).
Kept deliberately simple (no aggressive morphology) so that anatomically
distinct bones stay as separate components.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel
from scipy import ndimage

# 3D full connectivity (26-neighbourhood).
_CONNECTIVITY = np.ones((3, 3, 3), dtype=np.uint8)


class RegionInfo(BaseModel):
    """De-identified metadata for one labeled connected component."""

    label: int
    n_voxels: int
    volume_mm3: float
    bbox_zyx: tuple[int, int, int, int, int, int]  # z0,z1,y0,y1,x0,x1
    centroid_zyx: tuple[float, float, float]


class SegmentationResult:
    """Holds the labeled volume + region metadata (arrays stay out of pydantic)."""

    def __init__(self, labels: np.ndarray, regions: list[RegionInfo],
                 spacing_xyz: tuple[float, float, float], metal_mask: np.ndarray):
        self.labels = labels                # int32, 0 = background
        self.regions = regions              # ordered largest-first
        self.spacing_xyz = spacing_xyz      # (sx, sy, sz) mm
        self.metal_mask = metal_mask        # bool array

    @property
    def n_regions(self) -> int:
        return len(self.regions)

    @property
    def metal_fraction(self) -> float:
        return float(self.metal_mask.mean()) if self.metal_mask.size else 0.0

    def region_mask(self, label: int) -> np.ndarray:
        return self.labels == label

    def largest_region(self) -> RegionInfo | None:
        return self.regions[0] if self.regions else None

    def combined_mask(self, labels: list[int] | None = None) -> np.ndarray:
        """Boolean mask for a selection of region labels (default: all)."""
        if labels is None:
            return self.labels > 0
        out = np.zeros_like(self.labels, dtype=bool)
        for lb in labels:
            out |= self.labels == lb
        return out

    def region_table(self) -> list[dict]:
        return [r.model_dump() for r in self.regions]


def segment_bone(volume_hu: np.ndarray, spacing_xyz: tuple[float, float, float],
                 params) -> SegmentationResult:
    """Threshold + label bone in an HU volume (array axes are z, y, x).

    ``params`` is a ``core.parameters.Parameters`` instance (or any object with
    ``hu_lower``, ``hu_upper``, ``metal_hu_cutoff``, ``island_min_voxels``).
    """
    bone = (volume_hu >= params.hu_lower) & (volume_hu <= params.hu_upper)
    metal = volume_hu > params.metal_hu_cutoff

    labels, n = ndimage.label(bone, structure=_CONNECTIVITY)
    if n == 0:
        return SegmentationResult(labels.astype(np.int32), [], spacing_xyz, metal)

    counts = np.bincount(labels.ravel())
    counts[0] = 0  # background
    keep = np.where(counts >= params.island_min_voxels)[0]
    keep = keep[np.argsort(counts[keep])[::-1]]  # largest first

    remap = np.zeros(counts.shape[0], dtype=np.int32)
    for new_label, old in enumerate(keep, start=1):
        remap[old] = new_label
    new_labels = remap[labels]

    voxel_vol = float(np.prod(spacing_xyz))
    slices = ndimage.find_objects(new_labels)
    regions: list[RegionInfo] = []
    for new_label, old in enumerate(keep, start=1):
        mask = new_labels == new_label
        sl = slices[new_label - 1]
        cz, cy, cx = ndimage.center_of_mass(mask)
        regions.append(
            RegionInfo(
                label=new_label,
                n_voxels=int(counts[old]),
                volume_mm3=float(counts[old]) * voxel_vol,
                bbox_zyx=(sl[0].start, sl[0].stop, sl[1].start, sl[1].stop, sl[2].start, sl[2].stop),
                centroid_zyx=(float(cz), float(cy), float(cx)),
            )
        )
    return SegmentationResult(new_labels, regions, spacing_xyz, metal)
