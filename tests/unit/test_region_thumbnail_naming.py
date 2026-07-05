"""Regression: region-thumbnail filenames must stay a single path segment even
for MULTI-SERIES side keys, which are namespaced with a slash ("s1/left"). Before
the fix, the raw key flowed into the output filename, so pyvista tried to write to
a non-existent subdirectory (EXPORTS_DIR/"5_s1"/"left_r1.png") and raised
FileNotFoundError — breaking region previews for every added series in BOTH
frontends. Rendering is mocked so this stays fast and headless.
"""
from types import SimpleNamespace

import numpy as np

from core import parameters as P
from core import pipeline


class _FakePlotter:
    """Captures the screenshot path instead of rendering."""
    captured: list = []

    def __init__(self, *a, **k):
        pass

    def set_background(self, *a, **k):
        pass

    def add_mesh(self, *a, **k):
        pass

    @property
    def camera_position(self):
        return None

    @camera_position.setter
    def camera_position(self, v):
        pass

    def screenshot(self, path):
        _FakePlotter.captured.append(str(path))

    def close(self):
        pass


def test_namespaced_side_key_flattened_in_thumbnail_name(monkeypatch, tmp_path):
    _FakePlotter.captured = []
    labels = np.zeros((3, 4, 5), np.int32)
    labels[1, 1:3, 1:3] = 1  # one region, label 1
    region = SimpleNamespace(label=1, bbox_zyx=(1, 2, 1, 3, 1, 3), volume_mm3=50_000.0)
    seg = SimpleNamespace(n_regions=1, labels=labels, regions=[region])

    monkeypatch.setattr(pipeline, "segment_bone", lambda *a, **k: seg)
    monkeypatch.setattr(pipeline, "_boneness_map", lambda *a, **k: {1: 0.9})
    monkeypatch.setattr(pipeline, "_bone_regions", lambda *a, **k: [region])
    monkeypatch.setattr(pipeline, "mask_to_mesh", lambda *a, **k: SimpleNamespace(n_points=10))
    monkeypatch.setattr(pipeline.pv, "Plotter", _FakePlotter)

    arr = np.zeros((3, 4, 5), np.int16)
    # prefix carries a namespaced multi-series side key (the bug trigger)
    out = pipeline.region_thumbnails(arr, (1.0, 1.0, 1.0), P.default_parameters(),
                                     tmp_path, "5_s1/left")

    assert _FakePlotter.captured, "screenshot was never called"
    written = _FakePlotter.captured[0]
    # The filename must be a single segment under tmp_path — no 's1/' subdir.
    assert written == str(tmp_path / "5_s1_left_r1.png"), written
    # The returned thumb URL must match (no stray slash beyond the mount prefix).
    assert out[0]["thumb"] == "/api/exports/5_s1_left_r1.png"
