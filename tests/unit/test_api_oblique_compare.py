"""Two-bone matched oblique cross-section (oblique-compare): map_plane + endpoint.

One movable oblique plane on the reference bone is mapped through the cached
registration onto the target bone, so both bones' 2D reformats ("2 boxes") show
the same physical cut. Registration is monkeypatched to a known transform so the
plane mapping + gate are deterministic.
"""
import base64

import numpy as np
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core import pipeline

CLIENT = TestClient(app)


def test_map_plane_rotates_normal_translates_origin():
    th = np.pi / 2  # 90° about z
    M = [[np.cos(th), -np.sin(th), 0, 10], [np.sin(th), np.cos(th), 0, -5],
         [0, 0, 1, 3], [0, 0, 0, 1]]
    o, n = pipeline.map_plane(M, (1, 0, 0), (1, 0, 0))
    assert np.allclose(o, (10, -4, 3))
    assert np.allclose(n, (0, 1, 0), atol=1e-9)   # +x normal -> +y after z-rot
    # identity leaves a plane untouched
    o2, n2 = pipeline.map_plane(np.eye(4), (3, 4, 5), (0, 0, 1))
    assert np.allclose(o2, (3, 4, 5)) and np.allclose(n2, (0, 0, 1))


def _two_side_session(sid, reg, monkeypatch):
    z, y, x = np.mgrid[0:16, 0:20, 0:24]
    arr = (z * 100 + y * 10 + x).astype(np.int16)
    side = lambda: {"arr": arr, "spacing": (1.0, 1.0, 1.0),
                    "offset_xyz": (0.0, 0.0, 0.0), "side": "s"}
    sess.SESSIONS[sid] = {"arr": arr, "spacing": (1.0, 1.0, 1.0), "meta": {},
                          "sides": {"left": side(), "right": side()}}
    calls = {"n": 0}
    def fake(ref, tgt, params, *, manual_transform=None):
        calls["n"] += 1
        return reg
    monkeypatch.setattr(pipeline, "compare_registration", fake)
    return calls


def test_oblique_compare_returns_two_reformats_and_gate(monkeypatch):
    reg = {"ref_world_to_tgt_world": np.eye(4).tolist(),
           "tgt_world_to_ref_world": np.eye(4).tolist(),
           "transform": np.eye(4).tolist(), "rms": 0.5, "inlier_fraction": 0.9}
    sid = "obc_ok"
    calls = _two_side_session(sid, reg, monkeypatch)
    try:
        body = {"reference_side": "left", "target_side": "right",
                "origin_xyz_mm": [12, 10, 8], "normal": [1, 1, 0],
                "size_mm": 40, "px_mm": 1.0, "max_dim": 128}
        r = CLIENT.post(f"/api/session/{sid}/oblique-compare", json=body)
        assert r.status_code == 200
        j = r.json()
        for box in ("reference", "target"):
            raw = base64.b64decode(j[box]["image_png_base64"])
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"       # valid PNG each box
            assert len(j[box]["meta"]["normal"]) == 3
        assert j["registration"]["reliable"] is True
        # second identical call reuses the cached registration
        CLIENT.post(f"/api/session/{sid}/oblique-compare", json=body)
        assert calls["n"] == 1
        # bad-length guard
        assert CLIENT.post(f"/api/session/{sid}/oblique-compare",
                           json={"origin_xyz_mm": [1, 2], "normal": [0, 0, 1]}
                           ).status_code == 422
    finally:
        sess.SESSIONS.pop(sid, None)


def test_oblique_compare_flags_unreliable(monkeypatch):
    reg = {"ref_world_to_tgt_world": np.eye(4).tolist(),
           "tgt_world_to_ref_world": np.eye(4).tolist(),
           "transform": np.eye(4).tolist(), "rms": 6.0, "inlier_fraction": 0.09}
    sid = "obc_bad"
    _two_side_session(sid, reg, monkeypatch)
    try:
        r = CLIENT.post(f"/api/session/{sid}/oblique-compare",
                        json={"reference_side": "left", "target_side": "right",
                              "origin_xyz_mm": [12, 10, 8], "normal": [0, 0, 1],
                              "size_mm": 40, "max_dim": 96})
        assert r.status_code == 200
        assert r.json()["registration"]["reliable"] is False
        assert "unreliable" in r.json()["registration"]["note"]
    finally:
        sess.SESSIONS.pop(sid, None)
