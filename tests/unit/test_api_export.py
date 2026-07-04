"""Light API tests for the new upload/export/compare surface.

These are deliberately light: they check that the new endpoints exist, validate
their input, and (for mesh upload / a direct export) exercise the wiring on tiny
synthetic data — never the heavy real-data segmentation/ICP compute.
"""
import io

import numpy as np
import pyvista as pv
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as session_router

CLIENT = TestClient(app)


# ------------------------------- upload ----------------------------------- #
def test_upload_rejects_unknown_extension():
    r = CLIENT.post("/api/upload",
                    files={"file": ("bad.txt", io.BytesIO(b"nope"), "text/plain")})
    assert r.status_code == 400
    assert "accepted" in r.json()["detail"].lower()


def test_upload_mesh_creates_mesh_session(tmp_path):
    sphere = pv.Sphere()
    p = tmp_path / "surf.vtp"
    sphere.save(str(p))
    data = p.read_bytes()
    r = CLIENT.post("/api/upload",
                    files={"file": ("surf.vtp", io.BytesIO(data), "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sides"] == ["mesh"]
    assert body["is_mesh"] is True
    assert body["is_bilateral"] is False
    assert body["meta"]["kind"] == "mesh"
    assert body["meta"]["n_points"] == sphere.n_points


def test_upload_stl_mesh_session(tmp_path):
    sphere = pv.Sphere()
    p = tmp_path / "surf.stl"
    sphere.save(str(p))
    r = CLIENT.post("/api/upload",
                    files={"file": ("surf.stl", io.BytesIO(p.read_bytes()),
                                    "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["sides"] == ["mesh"]


# ------------------------------- export ----------------------------------- #
def _register_thickness_session() -> str:
    """Insert a minimal single-side session (used only by validation tests,
    which fail before any compute runs)."""
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    sid = "testexportsid1"
    session_router.SESSIONS[sid] = {
        "arr": None, "spacing": (1.0, 1.0, 1.0), "meta": {"format": "test"},
        "sides": {"full": {"arr": mask.astype(np.float32), "spacing": (1.0, 1.0, 1.0),
                           "offset_xyz": (0.0, 0.0, 0.0), "side": "full"}},
    }
    return sid


def test_export_endpoint_missing_session():
    r = CLIENT.post("/api/session/nope/export", json={"mode": "A"})
    assert r.status_code == 404


def test_export_endpoint_validates_mode():
    sid = _register_thickness_session()
    r = CLIENT.post(f"/api/session/{sid}/export", json={"mode": "Z"})
    assert r.status_code == 422


def test_export_endpoint_validates_dpi():
    sid = _register_thickness_session()
    r = CLIENT.post(f"/api/session/{sid}/export",
                    json={"mode": "A", "dpi": 0, "formats": ["png"]})
    assert r.status_code == 422


def test_export_endpoint_requires_formats():
    sid = _register_thickness_session()
    r = CLIENT.post(f"/api/session/{sid}/export",
                    json={"mode": "A", "formats": []})
    assert r.status_code == 422


def test_export_endpoint_runs_bundle(monkeypatch, tmp_path):
    """Full happy-path: patch analyze_thickness to return a tiny mesh, then export."""
    from core.meshing import mask_to_mesh
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    mesh["thickness_mm"] = np.linspace(0.5, 5.0, mesh.n_points)

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {},
                "regions": [], "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "exprun1"
    session_router.SESSIONS[sid] = {
        "arr": None, "spacing": (1.0, 1.0, 1.0), "meta": {"format": "test"},
        "sides": {"full": {"arr": mask.astype(np.float32), "spacing": (1.0, 1.0, 1.0),
                           "offset_xyz": (0.0, 0.0, 0.0), "side": "full"}},
    }
    r = CLIENT.post(f"/api/session/{sid}/export",
                    json={"mode": "A", "side": "full",
                          "formats": ["png", "vtp"], "dpi": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["files"].keys()) == {"png", "vtp"}
    for url in body["files"].values():
        assert url.startswith("/api/exports/")
    # the exported files are actually served by the static mount
    vtp_url = body["files"]["vtp"]
    got = CLIENT.get(vtp_url)
    assert got.status_code == 200
    assert len(got.content) > 200


def test_export_mesh_side_rejected_for_mode_a(monkeypatch):
    """A bare-mesh session cannot run Mode A thickness export (needs a volume)."""
    sphere = pv.Sphere()
    sid = "meshonly1"
    session_router.SESSIONS[sid] = {
        "arr": None, "spacing": None, "meta": {"kind": "mesh"},
        "sides": {"mesh": {"mesh": sphere, "side": "mesh", "offset_xyz": (0, 0, 0)}},
    }
    r = CLIENT.post(f"/api/session/{sid}/export",
                    json={"mode": "A", "side": "mesh", "formats": ["png"], "dpi": 100})
    assert r.status_code == 400


# ------------------------------- compare ---------------------------------- #
def test_compare_accepts_manual_transform_field():
    """The /compare body now accepts an optional manual_transform (4x4)."""
    from api.routers.session import CompareReq
    req = CompareReq(reference_side="left", target_side="right",
                     manual_transform=[[1, 0, 0, 0], [0, 1, 0, 0],
                                       [0, 0, 1, 0], [0, 0, 0, 1]])
    assert req.manual_transform is not None
    # backward compatible: default is None
    assert CompareReq().manual_transform is None
