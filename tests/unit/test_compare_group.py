"""N-way "compare all visits at once" (same anatomical side) -> one colour map.

Geometry is mocked to concentric spheres (a growing bone), registration to
identity (spheres are already concentric), so the REAL signed_distance +
aggregate + sign path is exercised deterministically:
  baseline r=10, follow-up r=11, latest r=12  =>  latest surface sits OUTSIDE the
  others => positive deviation (excess / growth) with target_outside_positive.
"""
from types import SimpleNamespace

import numpy as np
import pyvista as pv
import pytest

import core.parameters as P
import core.registration as reg_mod
from core import pipeline


def _sphere(r):
    m = pv.Sphere(radius=float(r), theta_resolution=24, phi_resolution=24)
    m["thickness_mm"] = np.full(m.n_points, 2.0)
    return m


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    # analyze_thickness gets (arr, spacing, params, ...); we encode the sphere
    # radius in `arr` so each visit reconstructs to a known geometry.
    monkeypatch.setattr(pipeline, "analyze_thickness",
                        lambda arr, spacing, params, **k: {"mesh": _sphere(arr)})
    # Spheres are concentric, so identity registration is the correct alignment.
    monkeypatch.setattr(reg_mod, "register",
                        lambda *a, **k: SimpleNamespace(transform=np.eye(4), rms=0.2, inlier_fraction=1.0))


def _side(r):
    return {"arr": float(r), "spacing": (1.0, 1.0, 1.0), "offset_xyz": (0.0, 0.0, 0.0)}


def test_group_colours_latest_with_positive_excess():
    params = P.Parameters()  # defaults: nway_colored='latest', baseline_to_latest
    res = pipeline.compare_series_group([_side(10), _side(11), _side(12)], params)
    assert res["n_visits"] == 3
    assert res["colored_index"] == 2               # latest carries the colour
    assert len(res["ghosts"]) == 2                 # the two earlier visits
    # latest (r=12) is OUTSIDE the baseline (r=10) -> strongly positive (excess).
    assert res["stats"]["max_positive"] > 1.0
    assert res["stats"]["mean"] > 0.5
    assert res["scalar"] == "deviation_mm"
    assert "spread_mm" in res["hover_scalars"]


def test_colouring_baseline_flips_sign():
    params = P.Parameters(nway_colored="baseline")
    res = pipeline.compare_series_group([_side(10), _side(12)], params)
    assert res["colored_index"] == 0
    # baseline (r=10) sits INSIDE the latest (r=12) -> negative (deficit).
    assert res["stats"]["max_negative"] < -1.0


def test_mean_vs_baseline_to_latest_differ_for_three_visits():
    # Monotonic growth 10 -> 11 -> 12, colouring the latest (r=12):
    #  * baseline_to_latest = distance latest->baseline = +2 (net change);
    #  * mean_signed = mean of latest->baseline(+2) and latest->mid(+1) = +1.5.
    # Both positive (latest is the largest); they differ, proving aggregate matters.
    sides = [_side(10), _side(11), _side(12)]
    net = pipeline.compare_series_group(sides, P.Parameters(nway_aggregate="baseline_to_latest"))
    mean = pipeline.compare_series_group(sides, P.Parameters(nway_aggregate="mean_signed"))
    assert net["stats"]["mean"] > mean["stats"]["mean"] + 0.3   # +2.0 vs +1.5
    assert mean["stats"]["mean"] > 0.5
    # 3 visits -> per-vertex spread across visits is carried and non-trivial.
    assert mean["spread_stats"]["max_positive"] > 0.1


def test_guards():
    with pytest.raises(ValueError):
        pipeline.compare_series_group([_side(10)], P.Parameters())          # < 2 visits
    with pytest.raises(ValueError):
        pipeline.compare_series_group(
            [_side(10), {"arr": None, "spacing": (1, 1, 1), "offset_xyz": (0, 0, 0)}],
            P.Parameters())                                                 # bare-mesh side
