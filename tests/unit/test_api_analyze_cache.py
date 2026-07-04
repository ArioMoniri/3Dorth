"""/analyze caches by (side, region, params): identical requests must not recompute."""
import numpy as np
import pyvista as pv
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core import pipeline

CLIENT = TestClient(app)


def test_repeat_analyze_hits_cache(monkeypatch):
    sid = "acache"
    z, y, x = np.mgrid[0:6, 0:8, 0:10]
    arr = (x + y + z).astype(np.int16)
    sess.SESSIONS[sid] = {"arr": arr, "spacing": (1.0, 1.0, 1.0), "meta": {},
                          "sides": {"left": {"arr": arr, "spacing": (1.0, 1.0, 1.0),
                                             "offset_xyz": (0.0, 0.0, 0.0), "side": "left"}}}
    calls = {"n": 0}

    def fake_analyze(a, sp, params, *, region_label=None, offset_xyz=(0, 0, 0)):
        calls["n"] += 1
        m = pv.Sphere(radius=3)
        m.point_data["thickness_mm"] = np.linspace(1, 5, m.n_points)
        return {"mesh": m, "region_label": 1, "regions": [], "metal_fraction": 0.0,
                "stats": {"mean": 2.5, "median": 2.4, "std": 0.5, "rms": 2.6,
                          "min": 1.0, "max": 5.0, "count": m.n_points}}

    monkeypatch.setattr(pipeline, "analyze_thickness", fake_analyze)
    try:
        body = {"side": "left", "params": {}}
        r1 = CLIENT.post(f"/api/session/{sid}/analyze", json=body)
        r2 = CLIENT.post(f"/api/session/{sid}/analyze", json=body)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["stats"]["mean"] == r2.json()["stats"]["mean"]
        assert calls["n"] == 1                 # second call served from cache
        # a different param DOES recompute
        CLIENT.post(f"/api/session/{sid}/analyze", json={"side": "left", "params": {"hu_min": 300}})
        assert calls["n"] == 2
    finally:
        sess.SESSIONS.pop(sid, None)
