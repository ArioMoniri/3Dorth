"""Linked cross-sections (Phase IV): apply_affine math + /compare-slice-map wiring.

The heavy registration (segmentation + FPFH/ICP) is exercised by the registration
suite; here we monkeypatch ``pipeline.compare_registration`` to a known world-map so
the endpoint's point mapping, quality gate, and caching are tested deterministically.
"""
import numpy as np
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core import pipeline

CLIENT = TestClient(app)


def test_apply_affine_translation_and_reflection():
    T = [[1, 0, 0, 10], [0, 1, 0, -5], [0, 0, 1, 2], [0, 0, 0, 1]]
    assert pipeline.apply_affine(T, (1.0, 1.0, 1.0)) == (11.0, -4.0, 3.0)
    # reflection about x = 50: x -> 100 - x
    Mx = [[-1, 0, 0, 100], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    assert pipeline.apply_affine(Mx, (30.0, 7.0, 9.0)) == (70.0, 7.0, 9.0)


def _two_side_session(sid, reg, monkeypatch):
    z, y, x = np.mgrid[0:8, 0:10, 0:12]
    arr = (z + y + x).astype(np.int16)
    def side(off):
        return {"arr": arr, "spacing": (1.0, 1.0, 1.0), "offset_xyz": off, "side": "s"}
    sess.SESSIONS[sid] = {"arr": arr, "spacing": (1.0, 1.0, 1.0), "meta": {},
                          "sides": {"left": side((0.0, 0.0, 0.0)),
                                    "right": side((0.0, 0.0, 0.0))}}
    calls = {"n": 0}
    def fake(ref, tgt, params, *, manual_transform=None):
        calls["n"] += 1
        return reg
    monkeypatch.setattr(pipeline, "compare_registration", fake)
    return calls


def test_compare_slice_map_maps_point_and_gates_reliable(monkeypatch):
    # target world = reference world shifted +2 in x (identity elsewhere)
    reg = {"ref_world_to_tgt_world": [[1, 0, 0, 2], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
           "tgt_world_to_ref_world": [[1, 0, 0, -2], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
           "transform": np.eye(4).tolist(), "rms": 0.4, "inlier_fraction": 0.82}
    sid = "cmp_ok"
    calls = _two_side_session(sid, reg, monkeypatch)
    try:
        body = {"reference_side": "left", "target_side": "right",
                "world_xyz_mm": [5.0, 3.0, 4.0]}
        r = CLIENT.post(f"/api/session/{sid}/compare-slice-map", json=body)
        assert r.status_code == 200
        j = r.json()
        # reference point unchanged; sagittal(ix)=5, coronal(iy)=3, axial(iz)=4
        assert j["reference"]["slices"] == {"axial": 4, "coronal": 3, "sagittal": 5}
        # target shifted +2 in x -> sagittal(ix)=7
        assert j["target"]["voxel_ijk"][0] == 7
        assert j["target"]["slices"]["sagittal"] == 7
        assert j["registration"]["reliable"] is True
        # second identical call is served from cache (no re-registration)
        CLIENT.post(f"/api/session/{sid}/compare-slice-map", json=body)
        assert calls["n"] == 1
    finally:
        sess.SESSIONS.pop(sid, None)


def test_compare_slice_map_flags_low_overlap_unreliable(monkeypatch):
    reg = {"ref_world_to_tgt_world": np.eye(4).tolist(),
           "tgt_world_to_ref_world": np.eye(4).tolist(),
           "transform": np.eye(4).tolist(), "rms": 5.0, "inlier_fraction": 0.08}
    sid = "cmp_bad"
    _two_side_session(sid, reg, monkeypatch)
    try:
        r = CLIENT.post(f"/api/session/{sid}/compare-slice-map",
                        json={"reference_side": "left", "target_side": "right",
                              "world_xyz_mm": [5.0, 3.0, 4.0]})
        assert r.status_code == 200
        assert r.json()["registration"]["reliable"] is False
        assert "unreliable" in r.json()["registration"]["note"]
    finally:
        sess.SESSIONS.pop(sid, None)
