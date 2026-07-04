"""MPR API endpoints: volume-info, slice PNG, pick-to-slices (synthetic session)."""
import numpy as np
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess

CLIENT = TestClient(app)


def _inject(sid="mprtest"):
    z, y, x = np.mgrid[0:4, 0:6, 0:8]
    arr = (z * 100 + y * 10 + x).astype(np.int16)
    side = {"arr": arr, "spacing": (1.0, 1.0, 2.0), "offset_xyz": (0.0, 0.0, 0.0),
            "side": "full"}
    sess.SESSIONS[sid] = {"arr": arr, "spacing": (1.0, 1.0, 2.0), "meta": {},
                          "sides": {"full": side}}
    return sid


def test_volume_info():
    sid = _inject("mpr_vi")
    try:
        r = CLIENT.get(f"/api/session/{sid}/volume-info", params={"side": "full"})
        assert r.status_code == 200
        vi = r.json()
        assert vi["shape_zyx"] == [4, 6, 8]
        assert vi["n_slices"] == {"axial": 4, "coronal": 6, "sagittal": 8}
        assert vi["orientation"] == "array"
    finally:
        sess.SESSIONS.pop(sid, None)


def test_slice_png():
    sid = _inject("mpr_sl")
    try:
        r = CLIENT.get(f"/api/session/{sid}/slice",
                       params={"side": "full", "plane": "axial", "index": 2, "max_dim": 64})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic
        # index clamps, bad plane 422
        assert CLIENT.get(f"/api/session/{sid}/slice",
                          params={"side": "full", "plane": "axial", "index": 999}).status_code == 200
        assert CLIENT.get(f"/api/session/{sid}/slice",
                          params={"side": "full", "plane": "oblique", "index": 0}).status_code == 422
    finally:
        sess.SESSIONS.pop(sid, None)


def test_pick_to_slices():
    sid = _inject("mpr_pk")
    try:
        r = CLIENT.post(f"/api/session/{sid}/pick-to-slices",
                        json={"side": "full", "world_xyz_mm": [5.0, 3.0, 4.0]})
        # spacing (1,1,2): ix=5, iy=3, iz=round(4/2)=2
        assert r.json()["slices"] == {"axial": 2, "coronal": 3, "sagittal": 5}
        assert r.json()["in_bounds"] is True
    finally:
        sess.SESSIONS.pop(sid, None)


def test_slice_on_mesh_session_errors():
    sess.SESSIONS["mpr_mesh"] = {"arr": None, "spacing": None, "meta": {},
                                 "sides": {"mesh": {"mesh": object(), "side": "mesh",
                                                    "offset_xyz": (0, 0, 0)}}}
    try:
        r = CLIENT.get("/api/session/mpr_mesh/slice",
                       params={"side": "mesh", "plane": "axial", "index": 0})
        assert r.status_code == 400
    finally:
        sess.SESSIONS.pop("mpr_mesh", None)
