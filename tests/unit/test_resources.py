"""Resource limits keep RAM/compute bounded on any device."""
import numpy as np

import core.resources as R


def test_adaptive_iso_floor_and_coarsening():
    # small volume -> the min-iso floor
    assert R.adaptive_iso((50, 50, 50), (0.5, 0.5, 0.5)) == 0.6
    # large volume -> coarser than the floor
    big = R.adaptive_iso((600, 600, 600), (1.0, 1.0, 1.0))
    assert big > 0.6
    # and the resulting iso grid stays under the budget
    phys = 600 * 600 * 600
    iso = R.adaptive_iso((600, 600, 600), (1.0, 1.0, 1.0), max_voxels=R.MAX_ISO_VOXELS)
    assert phys / (iso ** 3) <= R.MAX_ISO_VOXELS * 1.05


def test_downsample_to_budget():
    big = np.zeros((400, 400, 400), dtype=np.int16)  # 64M > 60M default budget
    out, sp = R.downsample_to_budget(big, (1.0, 1.0, 1.0))
    assert out.size < big.size
    assert sp[0] >= 1.0  # spacing scaled to match
    small = np.zeros((10, 10, 10), dtype=np.int16)
    out2, sp2 = R.downsample_to_budget(small, (1.0, 1.0, 1.0))
    assert out2.shape == small.shape and sp2 == (1.0, 1.0, 1.0)  # untouched


def test_as_hu_int16():
    b = R.as_hu_int16(np.array([-1024.0, 700.0, 3071.0], dtype=np.float32))
    assert b.dtype == np.int16
    assert np.array_equal(b, np.array([-1024, 700, 3071], dtype=np.int16))


def test_summary_flags():
    s = R.summary()
    assert {"gpu", "max_sessions", "compute_concurrency"} <= set(s)
    assert isinstance(R.GPU, bool)
    assert R.COMPUTE_CONCURRENCY >= 1 and R.MAX_SESSIONS >= 1
