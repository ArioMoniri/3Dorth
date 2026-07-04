"""AR asset: GLB mesh export (per-vertex colour, triangle cap) + /model.glb endpoint."""
import numpy as np
import pyvista as pv
import trimesh
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core.export.mesh import export_mesh

CLIENT = TestClient(app)


def _colored_sphere():
    sph = pv.Sphere(radius=10.0)
    sph.point_data["thickness_mm"] = np.linspace(0.5, 6.0, sph.n_points)
    return sph


def test_export_glb_roundtrips_with_vertex_colour(tmp_path):
    out = export_mesh(_colored_sphere(), tmp_path / "m.glb", fmt="glb",
                      scalar_name="thickness_mm", clim=(0.33, 10.0))
    data = out.read_bytes()
    assert data[:4] == b"glTF"                      # binary glTF magic
    scene = trimesh.load(str(out))
    g = next(iter(scene.geometry.values()))
    assert len(g.vertices) > 0 and len(g.faces) > 0
    assert g.visual.kind == "vertex"                # colour field baked in
    # thin end green-ish, thick end red-ish (Fig-2 direction)
    first, last = g.visual.vertex_colors[0], g.visual.vertex_colors[-1]
    assert first[1] > first[0]                      # green channel dominates at 0.5 mm
    assert last[0] > last[2]                         # red beats blue at 6.0 mm


def test_export_glb_caps_triangle_count(tmp_path):
    # A dense sphere well over the cap decimates down; still a valid GLB.
    dense = pv.Sphere(radius=10.0, theta_resolution=400, phi_resolution=400)
    n_before = dense.triangulate().n_cells
    assert n_before > 250_000
    out = export_mesh(dense, tmp_path / "big.glb", fmt="glb")
    scene = trimesh.load(str(out))
    g = next(iter(scene.geometry.values()))
    assert len(g.faces) <= 260_000                   # capped (small slack for decimate)


def test_model_glb_endpoint_serves_current_surface():
    sid = "ar_ep"
    sess.SESSIONS[sid] = {
        "arr": None, "spacing": None, "meta": {}, "sides": {},
        "ar": {"mesh": _colored_sphere(), "scalar": "thickness_mm",
               "clim": (0.33, 10.0), "cmap": "green_yellow_red"},
    }
    try:
        r = CLIENT.get(f"/api/session/{sid}/model.glb")
        assert r.status_code == 200
        assert r.headers["content-type"] == "model/gltf-binary"
        assert r.content[:4] == b"glTF"
        assert "ar_glb" in sess.SESSIONS[sid]        # byte-cache populated
    finally:
        sess.SESSIONS.pop(sid, None)


def test_model_glb_409_before_compute():
    sid = "ar_empty"
    sess.SESSIONS[sid] = {"arr": None, "spacing": None, "meta": {}, "sides": {}}
    try:
        assert CLIENT.get(f"/api/session/{sid}/model.glb").status_code == 409
    finally:
        sess.SESSIONS.pop(sid, None)
