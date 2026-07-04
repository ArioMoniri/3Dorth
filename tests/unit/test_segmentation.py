"""Segmentation: thresholding, region labeling, island removal, metal mask."""
import numpy as np

import core.parameters as P
from core.segmentation import segment_bone


def _air_volume(shape=(40, 40, 40)):
    return np.full(shape, -1000.0, dtype=np.float32)


def test_two_regions_and_island_removal():
    vol = _air_volume()
    # two bone cubes (8^3 = 512 voxels), well separated
    vol[4:12, 4:12, 4:12] = 500.0
    vol[4:12, 4:12, 28:36] = 500.0
    # a tiny 2^3 = 8-voxel speck that must be dropped
    vol[36:38, 36:38, 36:38] = 500.0
    params = P.Parameters(island_min_voxels=100)
    res = segment_bone(vol, (1.0, 1.0, 1.0), params)
    assert res.n_regions == 2
    assert all(r.n_voxels == 512 for r in res.regions)
    assert res.largest_region().volume_mm3 == 512.0  # 1mm^3 voxels


def test_metal_mask():
    vol = _air_volume()
    vol[4:12, 4:12, 4:12] = 500.0     # bone
    vol[20:24, 20:24, 20:24] = 2500.0  # metal (> cutoff 2000)
    res = segment_bone(vol, (1.0, 1.0, 1.0), P.default_parameters())
    assert res.metal_mask.sum() == 4 * 4 * 4
    assert res.metal_fraction > 0


def test_hu_window_excludes_air_and_metal_from_bone():
    vol = _air_volume()
    vol[4:12, 4:12, 4:12] = 500.0      # in bone window
    vol[20:28, 20:28, 20:28] = 5000.0  # above upper threshold -> not bone
    params = P.Parameters(island_min_voxels=100)
    res = segment_bone(vol, (1.0, 1.0, 1.0), params)
    assert res.n_regions == 1  # only the 500 HU cube is bone


def test_combined_mask_selection():
    vol = _air_volume()
    vol[4:12, 4:12, 4:12] = 500.0
    vol[4:12, 4:12, 28:36] = 500.0
    params = P.Parameters(island_min_voxels=100)
    res = segment_bone(vol, (1.0, 1.0, 1.0), params)
    only1 = res.combined_mask([1])
    assert only1.sum() == 512
    assert res.combined_mask().sum() == 1024  # all regions
