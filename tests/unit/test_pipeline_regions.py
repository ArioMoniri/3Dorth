"""Region selection + thumbnails: prefer bone, never a non-bone (table) region."""
import numpy as np

import core.parameters as P
from core import pipeline


def _volume_with_bone_and_pad():
    """A dense 'bone' block (cortex-like HU) and a low-density 'table pad' block
    that clears the 226 HU floor but has no dense cortex."""
    arr = np.full((30, 40, 60), -1000.0, dtype=np.float32)
    arr[8:22, 12:28, 6:18] = 900.0    # dense bone (HU >= 500) on the low-x side
    arr[8:22, 12:28, 42:56] = 300.0   # low-density pad (226 < HU < 500), high-x
    return arr


def test_boneness_map_separates_bone_from_pad():
    arr = _volume_with_bone_and_pad()
    from core.segmentation import segment_bone

    seg = segment_bone(arr, (1.0, 1.0, 1.0), P.Parameters(island_min_voxels=100))
    bon = pipeline._boneness_map(arr, seg.labels, int(seg.labels.max()))
    # exactly one region should read as "bone" (dense cortex fraction high)
    bony = [r for r in seg.regions if bon[r.label] >= 0.5]
    padlike = [r for r in seg.regions if bon[r.label] < 0.05]
    assert len(bony) == 1
    assert len(padlike) == 1


def test_pick_bone_region_never_picks_the_pad():
    arr = _volume_with_bone_and_pad()
    from core.segmentation import segment_bone

    seg = segment_bone(arr, (1.0, 1.0, 1.0), P.Parameters(island_min_voxels=100))
    bon = pipeline._boneness_map(arr, seg.labels, int(seg.labels.max()))
    picked = pipeline._pick_bone_region(seg, arr, (1.0, 1.0, 1.0), bon)
    assert bon[picked.label] >= 0.5  # the dense bone, not the pad


def test_region_thumbnails_returns_bone_only(tmp_path):
    arr = _volume_with_bone_and_pad()
    thumbs = pipeline.region_thumbnails(arr, (1.0, 1.0, 1.0),
                                        P.Parameters(island_min_voxels=100),
                                        tmp_path, "t")
    assert len(thumbs) >= 1
    for t in thumbs:
        assert set(("label", "volume_cm3", "boneness", "thumb")) <= set(t)
        assert t["boneness"] >= 0.05  # non-bone pads excluded
