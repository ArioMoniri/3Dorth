"""/session/{sid}/compare-group wiring: side resolution, error codes, response
shape, and cache reuse. The heavy compute (compare_series_group) is monkeypatched
to a light fake so this tests the ENDPOINT, not the registration math (covered by
test_compare_group.py).
"""
import numpy as np
import pyvista as pv
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core import pipeline

CLIENT = TestClient(app)


def _fake_sides(arr, spacing, layout="auto"):
    def side(n):
        return {"arr": arr, "spacing": spacing, "offset_xyz": (0.0, 0.0, 0.0), "side": n}
    return {"left": side("left"), "right": side("right")}


def _fake_group(sides_list, params, **k):
    m = pv.Sphere(radius=5.0)
    m["deviation_mm"] = np.zeros(m.n_points)
    return {
        "mesh": m, "ghosts": [pv.Sphere(radius=6.0)], "scalar": "deviation_mm",
        "stats": {"mean": 0.0, "max_positive": 1.0, "max_negative": -1.0},
        "spread_stats": {"mean": 0.0, "max_positive": 0.0},
        "registrations": [{"rms": 0.0, "inlier_fraction": 1.0},
                          {"rms": 0.3, "inlier_fraction": 0.9}],
        "colored_index": 1, "n_visits": 2, "aggregate": "baseline_to_latest",
        "hover_scalars": ["deviation_mm", "spread_mm", "ref_thickness_mm"],
    }


@pytest.fixture
def two_series(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    arr = np.zeros((4, 5, 6), np.int16)
    first = sess._new_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    sid = first["session_id"]
    sess._add_series(sess._get_session(sid), sid, arr, (1.0, 1.0, 1.0), {"series": "follow-up"})
    yield sid
    sess.SESSIONS.pop(sid, None)


def test_group_happy_path(two_series, monkeypatch):
    calls = {"n": 0}
    def spy(sides_list, params, **k):
        calls["n"] += 1
        return _fake_group(sides_list, params, **k)
    monkeypatch.setattr(pipeline, "compare_series_group", spy)
    body = {"sides_group": ["left", "s1/left"], "params": {}}
    r = CLIENT.post(f"/api/session/{two_series}/compare-group", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["geometry_url"] and len(j["ghost_urls"]) == 1
    assert j["colored_index"] == 1 and j["n_visits"] == 2
    assert j["aggregate"] == "baseline_to_latest"
    assert len(j["registrations"]) == 2 and j["registrations"][1]["reliable"] is True
    # identical second call is served from cache (no recompute)
    CLIENT.post(f"/api/session/{two_series}/compare-group", json=body)
    assert calls["n"] == 1


def test_group_needs_two(two_series):
    r = CLIENT.post(f"/api/session/{two_series}/compare-group",
                    json={"sides_group": ["left"], "params": {}})
    assert r.status_code == 400


def test_group_unknown_side(two_series):
    r = CLIENT.post(f"/api/session/{two_series}/compare-group",
                    json={"sides_group": ["left", "s9/left"], "params": {}})
    assert r.status_code == 400


def test_group_rejects_mesh_side(two_series, monkeypatch):
    # Inject a bare-mesh side (arr is None) and ensure it is refused pre-compute.
    s = sess._get_session(two_series)
    s["sides"]["s1/mesh"] = {"mesh": object(), "side": "mesh", "offset_xyz": (0, 0, 0)}
    r = CLIENT.post(f"/api/session/{two_series}/compare-group",
                    json={"sides_group": ["left", "s1/mesh"], "params": {}})
    assert r.status_code == 400
