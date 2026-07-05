"""Statistics-figures unit tests: core.stats.figures functions + the
POST /api/session/{sid}/figures and /export-figures endpoints.

Mirrors tests/unit/test_api_mpr.py's synthetic-session-injection pattern and
tests/unit/test_api_export.py's monkeypatched-pipeline pattern — never touches
real patient data or the heavy segmentation/ICP pipeline.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as session_router
from core.stats.figures import (
    distribution_histogram_bytes,
    per_region_summary_bytes,
    region_boxplot_bytes,
    regression_scatter_bytes,
    render_result_figures,
)

CLIENT = TestClient(app)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TIFF_MAGIC_LE = b"II*\x00"
_TIFF_MAGIC_BE = b"MM\x00*"
_JPG_MAGIC = b"\xff\xd8\xff"


# --------------------------------------------------------------------------- #
# core.stats.figures — direct unit tests
# --------------------------------------------------------------------------- #
def _thickness_values(n=800, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(2.5, 0.6, n)


def test_distribution_histogram_png_magic_and_dpi_changes_size():
    vals = _thickness_values()
    low = distribution_histogram_bytes(vals, scalar_name="thickness_mm", dpi=72)
    high = distribution_histogram_bytes(vals, scalar_name="thickness_mm", dpi=300)
    assert low[:8] == _PNG_MAGIC
    assert high[:8] == _PNG_MAGIC
    assert len(low) != len(high)


def test_distribution_histogram_tiff_and_jpg_magic():
    vals = _thickness_values()
    tiff = distribution_histogram_bytes(vals, fmt="tiff", dpi=150)
    jpg = distribution_histogram_bytes(vals, fmt="jpg", dpi=150)
    assert tiff[:4] in (_TIFF_MAGIC_LE, _TIFF_MAGIC_BE)
    assert jpg[:3] == _JPG_MAGIC


def test_distribution_histogram_tiff_dpi_changes_size():
    vals = _thickness_values()
    low = distribution_histogram_bytes(vals, fmt="tiff", dpi=72)
    high = distribution_histogram_bytes(vals, fmt="tiff", dpi=300)
    assert len(low) != len(high)


def test_distribution_histogram_rejects_empty():
    with pytest.raises(ValueError):
        distribution_histogram_bytes([])


def test_distribution_histogram_rejects_bad_format():
    with pytest.raises(ValueError):
        distribution_histogram_bytes(_thickness_values(), fmt="bmp")


def test_per_region_summary_needs_multiple_regions():
    with pytest.raises(ValueError):
        per_region_summary_bytes([{"label": 1, "volume_cm3": 10.0, "boneness": 0.9}])
    with pytest.raises(ValueError):
        per_region_summary_bytes([])


def test_per_region_summary_png_magic_and_dpi_changes_size():
    regions = [
        {"label": 1, "volume_cm3": 120.5, "boneness": 0.82},
        {"label": 2, "volume_cm3": 40.2, "boneness": 0.61},
        {"label": 3, "volume_cm3": 8.7, "boneness": 0.33},
    ]
    low = per_region_summary_bytes(regions, dpi=72)
    high = per_region_summary_bytes(regions, dpi=300)
    assert low[:8] == _PNG_MAGIC and high[:8] == _PNG_MAGIC
    assert len(low) != len(high)


def test_region_boxplot_needs_multiple_regions():
    with pytest.raises(ValueError):
        region_boxplot_bytes({"R1": [1.0, 2.0, 3.0]})


def test_region_boxplot_png_and_tiff():
    rng = np.random.default_rng(1)
    groups = {"R1": rng.normal(2.0, 0.3, 30), "R2": rng.normal(3.0, 0.4, 30)}
    png = region_boxplot_bytes(groups, dpi=100)
    tiff = region_boxplot_bytes(groups, dpi=100, fmt="tiff")
    assert png[:8] == _PNG_MAGIC
    assert tiff[:4] in (_TIFF_MAGIC_LE, _TIFF_MAGIC_BE)


def test_regression_scatter_bytes():
    from core.stats import linear_regression

    rng = np.random.default_rng(2)
    x = np.linspace(0.0, 10.0, 40)
    y = 2.0 * x + 1.0 + rng.normal(0, 0.2, 40)
    fit = linear_regression(x, y)
    png = regression_scatter_bytes(x, y, fit, dpi=100)
    assert png[:8] == _PNG_MAGIC


def test_render_result_figures_all_that_apply():
    vals = _thickness_values()
    regions = [{"label": 1, "volume_cm3": 100.0, "boneness": 0.8},
              {"label": 2, "volume_cm3": 30.0, "boneness": 0.5}]
    out = render_result_figures(scalar_values=vals, scalar_name="thickness_mm",
                                regions=regions, dpi=100)
    assert set(out.keys()) == {"histogram", "ecdf", "table", "by_region"}
    for png in out.values():
        assert png[:8] == _PNG_MAGIC


def test_render_result_figures_omits_by_region_single_region():
    vals = _thickness_values()
    out = render_result_figures(scalar_values=vals, scalar_name="thickness_mm",
                                regions=[{"label": 1, "volume_cm3": 100.0, "boneness": 0.8}],
                                dpi=100)
    assert set(out.keys()) == {"histogram", "ecdf", "table"}


def test_render_result_figures_which_filter():
    vals = _thickness_values()
    regions = [{"label": 1, "volume_cm3": 100.0, "boneness": 0.8},
              {"label": 2, "volume_cm3": 30.0, "boneness": 0.5}]
    out = render_result_figures(scalar_values=vals, scalar_name="thickness_mm",
                                regions=regions, which=["by_region"], dpi=100)
    assert set(out.keys()) == {"by_region"}


# --------------------------------------------------------------------------- #
# API endpoint tests — synthetic injected session (mirrors test_api_mpr.py)
# --------------------------------------------------------------------------- #
def _mesh_with_thickness(n_points_target=None, seed=0):
    from core.meshing import mask_to_mesh

    mask = np.zeros((24, 24, 24), dtype=bool)
    mask[4:20, 4:20, 4:20] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    rng = np.random.default_rng(seed)
    mesh["thickness_mm"] = np.clip(rng.normal(2.5, 0.6, mesh.n_points), 0.1, 8.0)
    return mesh


def _register_volume_session(sid: str) -> None:
    mask = np.zeros((24, 24, 24), dtype=bool)
    mask[4:20, 4:20, 4:20] = True
    session_router.SESSIONS[sid] = {
        "arr": None, "spacing": (1.0, 1.0, 1.0), "meta": {"format": "test"},
        "sides": {"full": {"arr": mask.astype(np.float32), "spacing": (1.0, 1.0, 1.0),
                           "offset_xyz": (0.0, 0.0, 0.0), "side": "full"}},
    }


def test_figures_endpoint_missing_session():
    r = CLIENT.post("/api/session/nope/figures", json={"mode": "A"})
    assert r.status_code == 404


def test_figures_endpoint_validates_mode():
    sid = "figtest_badmode"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures", json={"mode": "Z"})
        assert r.status_code == 422
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_returns_base64_pngs(monkeypatch):
    """Full happy path: patch analyze_thickness with >1 region so both figures
    are produced, then decode + verify the returned base64 PNGs."""
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77},
              {"label": 2, "volume_cm3": 12.1, "boneness": 0.44}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figtest_happy"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures",
                        json={"mode": "A", "side": "full", "params": {}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "figures" in body and "note" in body
        assert set(body["figures"].keys()) == {"histogram", "ecdf", "table", "by_region"}
        # descriptive stat block with percentiles / IQR / threshold fractions
        st = body["stats"]
        for k in ("p5", "p25", "p50", "p75", "p95", "iqr", "pct_over_1mm", "pct_over_2mm"):
            assert k in st, f"missing stat key {k}"
        for name, b64 in body["figures"].items():
            png = base64.b64decode(b64)
            assert png[:8] == _PNG_MAGIC, f"{name} is not a valid PNG"
        assert "single-subject" in body["note"].lower() or "descriptive" in body["note"].lower()
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_reuses_analyze_cache(monkeypatch):
    """A prior /analyze call populates analyze_cache; /figures with the same
    params must reuse it (analyze_thickness must NOT be called again)."""
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77}]
    calls = {"n": 0}

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        calls["n"] += 1
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figtest_cache"
    _register_volume_session(sid)
    try:
        r1 = CLIENT.post(f"/api/session/{sid}/analyze", json={"side": "full", "params": {}})
        assert r1.status_code == 200, r1.text
        assert calls["n"] == 1

        r2 = CLIENT.post(f"/api/session/{sid}/figures",
                         json={"mode": "A", "side": "full", "params": {}})
        assert r2.status_code == 200, r2.text
        assert calls["n"] == 1, "figures endpoint should reuse analyze_cache, not recompute"
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_single_region_omits_by_region(monkeypatch):
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figtest_single_region"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures", json={"mode": "A", "side": "full"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["figures"].keys()) == {"histogram", "ecdf", "table"}
        assert "by_region" in body["note"].lower()
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_which_filter(monkeypatch):
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77},
              {"label": 2, "volume_cm3": 12.1, "boneness": 0.44}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figtest_which"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures",
                        json={"mode": "A", "side": "full", "which": ["histogram"]})
        assert r.status_code == 200, r.text
        assert set(r.json()["figures"].keys()) == {"histogram"}
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_bad_which_422():
    sid = "figtest_badwhich"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures",
                        json={"mode": "A", "side": "full", "which": ["nonsense"]})
        assert r.status_code == 422
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_figures_endpoint_mesh_only_side_rejected_for_mode_a():
    import pyvista as pv

    sid = "figtest_meshonly"
    sphere = pv.Sphere()
    session_router.SESSIONS[sid] = {
        "arr": None, "spacing": None, "meta": {"kind": "mesh"},
        "sides": {"mesh": {"mesh": sphere, "side": "mesh", "offset_xyz": (0, 0, 0)}},
    }
    try:
        r = CLIENT.post(f"/api/session/{sid}/figures", json={"mode": "A", "side": "mesh"})
        assert r.status_code == 400
    finally:
        session_router.SESSIONS.pop(sid, None)


# --------------------------------------------------------------------------- #
# export-figures endpoint
# --------------------------------------------------------------------------- #
def test_export_figures_endpoint_missing_session():
    r = CLIENT.post("/api/session/nope/export-figures", json={"mode": "A"})
    assert r.status_code == 404


def test_export_figures_endpoint_validates_dpi_and_formats(monkeypatch):
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figexp_validate"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/export-figures",
                        json={"mode": "A", "side": "full", "dpi": 0})
        assert r.status_code == 422

        r = CLIENT.post(f"/api/session/{sid}/export-figures",
                        json={"mode": "A", "side": "full", "formats": []})
        assert r.status_code == 422

        r = CLIENT.post(f"/api/session/{sid}/export-figures",
                        json={"mode": "A", "side": "full", "formats": ["svg"]})
        assert r.status_code == 422
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_export_figures_endpoint_writes_png_and_tiff(monkeypatch):
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77},
              {"label": 2, "volume_cm3": 12.1, "boneness": 0.44}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figexp_happy"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/export-figures",
                        json={"mode": "A", "side": "full",
                              "formats": ["png", "tiff"], "dpi": 150})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["files"].keys()) == {
            "histogram_png", "histogram_tiff", "ecdf_png", "ecdf_tiff",
            "table_png", "table_tiff", "by_region_png", "by_region_tiff",
        }
        for url in body["files"].values():
            assert url.startswith("/api/exports/")
            got = CLIENT.get(url)
            assert got.status_code == 200
            assert len(got.content) > 200

        hist_png_url = body["files"]["histogram_png"]
        hist_tiff_url = body["files"]["histogram_tiff"]
        assert CLIENT.get(hist_png_url).content[:8] == _PNG_MAGIC
        assert CLIENT.get(hist_tiff_url).content[:4] in (_TIFF_MAGIC_LE, _TIFF_MAGIC_BE)
    finally:
        session_router.SESSIONS.pop(sid, None)


def test_export_figures_endpoint_single_format_single_name(monkeypatch):
    mesh = _mesh_with_thickness()
    regions = [{"label": 1, "volume_cm3": 55.3, "boneness": 0.77}]

    def fake_analyze(arr, spacing, params, region_label=None, offset_xyz=(0, 0, 0)):
        return {"mesh": mesh, "region_label": 1, "stats": {}, "regions": regions,
               "metal_fraction": 0.0}

    monkeypatch.setattr(session_router.pipeline, "analyze_thickness", fake_analyze)

    sid = "figexp_singlefmt"
    _register_volume_session(sid)
    try:
        r = CLIENT.post(f"/api/session/{sid}/export-figures",
                        json={"mode": "A", "side": "full", "formats": ["png"], "dpi": 100})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["files"].keys()) == {"histogram", "ecdf", "table"}  # single region -> no by_region
        assert "by_region" in body["note"].lower()
    finally:
        session_router.SESSIONS.pop(sid, None)
