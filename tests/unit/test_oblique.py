"""Oblique / arbitrary cross-section (Phase VII): basis, pixel<->world, endpoint.

The whole point is that the 3D cut and the 2D reformat are matched at *every*
pixel, so the tests pin the pixel<->world inverse and the plane basis exactly.
"""
import base64
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core.viz import slice as S

CLIENT = TestClient(app)


def _vol():
    z, y, x = np.mgrid[0:40, 0:50, 0:60]
    return (z * 100 + y * 10 + x).astype(np.int16)


def test_plane_basis_orthonormal_right_handed():
    for normal in [(0, 0, 1), (1, 1, 0), (1, 2, 3), (0, 1, 0)]:
        n, u, v = S.plane_basis(normal)
        assert abs(np.linalg.norm(u) - 1) < 1e-9
        assert abs(np.linalg.norm(v) - 1) < 1e-9
        assert abs(np.dot(u, n)) < 1e-9 and abs(np.dot(v, n)) < 1e-9
        assert abs(np.dot(u, v)) < 1e-9
        assert np.allclose(np.cross(u, v), n)          # right-handed: u×v = n
    with pytest.raises(ValueError):
        S.plane_basis((0, 0, 0))


def test_pixel_world_roundtrip_is_exact():
    _, meta = S.oblique_grid_world(origin=(30, 25, 20), normal=(1, 1, 0.5),
                                   size_mm=60, px_mm=1.0)
    c0 = (meta["size_px"] - 1) / 2.0
    # centre pixel maps to the plane origin
    assert np.allclose(S.oblique_pixel_to_world(meta, c0, c0), (30, 25, 20))
    # arbitrary pixel round-trips world -> pixel -> world
    for (r, c) in [(0, 0), (5, 12), (meta["size_px"] - 1, 3)]:
        w = S.oblique_pixel_to_world(meta, r, c)
        rr, cc = S.world_to_oblique_pixel(meta, w)
        assert abs(rr - r) < 1e-6 and abs(cc - c) < 1e-6


def test_axis_normal_oblique_reads_the_expected_voxel():
    a = _vol()  # arr[z,y,x] = z*100 + y*10 + x, identity spacing/offset
    from scipy import ndimage
    # world (30,25,20) == voxel (ix,iy,iz)=(30,25,20); its HU is 20*100+25*10+30
    val = ndimage.map_coordinates(a, [[20], [25], [30]], order=1)[0]
    assert val == 20 * 100 + 25 * 10 + 30
    # the oblique plane's exact centre pixel maps back to that same world point,
    # so a click at the centre of the 2D reformat lands on the intended 3D voxel
    _, meta = S.oblique_grid_world((30, 25, 20), (0, 0, 1), size_mm=40, px_mm=1.0)
    c0 = (meta["size_px"] - 1) / 2.0
    assert np.allclose(S.oblique_pixel_to_world(meta, c0, c0), (30, 25, 20))


def test_render_oblique_png_valid_image():
    from PIL import Image
    a = _vol()
    png, meta = S.render_oblique_png(a, (1, 1, 1), (0, 0, 0), (30, 25, 20),
                                     (1, 1, 0), size_mm=50, px_mm=1.0, max_dim=128)
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG"
    assert max(im.size) <= 128
    assert set(meta) >= {"origin_xyz_mm", "normal", "u", "v", "px_mm", "size_px"}


def _inject(sid="obl"):
    a = _vol()
    side = {"arr": a, "spacing": (1.0, 1.0, 1.0), "offset_xyz": (0.0, 0.0, 0.0),
            "side": "full"}
    sess.SESSIONS[sid] = {"arr": a, "spacing": (1.0, 1.0, 1.0), "meta": {},
                          "sides": {"full": side}}
    return sid


def test_oblique_endpoint_returns_image_and_basis():
    sid = _inject("obl_ep")
    try:
        r = CLIENT.post(f"/api/session/{sid}/oblique-slice",
                        json={"side": "full", "origin_xyz_mm": [30, 25, 20],
                              "normal": [1, 1, 0], "size_mm": 50, "px_mm": 1.0,
                              "max_dim": 128})
        assert r.status_code == 200
        j = r.json()
        raw = base64.b64decode(j["image_png_base64"])
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert j["meta"]["size_px"] <= 128
        assert len(j["meta"]["normal"]) == 3 and len(j["meta"]["u"]) == 3
        # bad length -> 422
        assert CLIENT.post(f"/api/session/{sid}/oblique-slice",
                           json={"origin_xyz_mm": [1, 2], "normal": [0, 0, 1]}
                           ).status_code == 422
    finally:
        sess.SESSIONS.pop(sid, None)
