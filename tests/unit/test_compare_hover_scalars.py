"""Mode B carries both bones' thickness + their difference on the reference surface,
so a hover can show reference vs contralateral wall thickness (not just deviation)."""
import numpy as np
import pyvista as pv

import core.parameters as P
from core import pipeline


def test_compare_sides_attaches_ref_tgt_thickness_and_diff(monkeypatch):
    # Fake segmentation+thickness: reference wall = 2.0 mm, target wall = 3.0 mm.
    seq = {"n": 0}

    def fake_analyze(arr, spacing, params, *, region_label=None, offset_xyz=(0, 0, 0)):
        m = pv.Sphere(radius=10.0)
        val = 2.0 if seq["n"] == 0 else 3.0
        seq["n"] += 1
        m.point_data["thickness_mm"] = np.full(m.n_points, val)
        return {"mesh": m, "region_label": 1, "regions": [], "metal_fraction": 0.0,
                "stats": {}}

    monkeypatch.setattr(pipeline, "analyze_thickness", fake_analyze)
    params = P.default_parameters()

    ref = {"arr": np.zeros((4, 4, 4), np.int16), "spacing": (1.0, 1.0, 1.0),
           "offset_xyz": (0.0, 0.0, 0.0)}
    tgt = {"arr": np.zeros((4, 4, 4), np.int16), "spacing": (1.0, 1.0, 1.0),
           "offset_xyz": (0.0, 0.0, 0.0)}
    res = pipeline.compare_sides(ref, tgt, params)
    mesh = res["mesh"]

    for name in ("deviation_mm", "ref_thickness_mm", "tgt_thickness_mm", "thickness_diff_mm"):
        assert name in mesh.point_data, f"{name} missing from Mode B surface"
    assert res["hover_scalars"][0] == "deviation_mm"

    assert np.allclose(mesh["ref_thickness_mm"], 2.0)
    assert np.allclose(mesh["tgt_thickness_mm"], 3.0, atol=1e-6)
    # difference = reference - contralateral = 2 - 3 = -1
    assert np.allclose(mesh["thickness_diff_mm"], -1.0, atol=1e-6)
