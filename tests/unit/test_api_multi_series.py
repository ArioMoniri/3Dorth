"""Multi-series sessions: a session can hold several uploaded SERIES (e.g.
baseline + follow-up visits) that are anchored and compared in Mode B.

The FIRST series keeps plain side names ("left"/"right"/"mesh") for backward
compatibility; further series are namespaced by id ("s1/left"). These tests
pin that data model (``_new_session`` / ``_add_series`` / ``_series_entry``) and
the ``/upload?session_id=`` add-series endpoint, mocking the heavy ingest so the
wiring — not the segmentation — is what's exercised.
"""
import numpy as np
from fastapi.testclient import TestClient

from api.main import app
from api.routers import session as sess
from core import ingest as core_ingest
from core import pipeline

CLIENT = TestClient(app)


def _fake_sides(arr, spacing, layout="auto"):
    """Deterministic bilateral split independent of segmentation."""
    def side(name):
        return {"arr": arr, "spacing": spacing, "offset_xyz": (0.0, 0.0, 0.0), "side": name}
    return {"left": side("left"), "right": side("right")}


def test_new_session_is_single_series_with_plain_sides(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    arr = np.zeros((4, 5, 6), np.int16)
    resp = sess._new_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    try:
        assert [s["id"] for s in resp["series"]] == ["s0"]
        assert resp["series"][0]["name"] == "baseline"
        assert set(resp["all_sides"]) == {"left", "right"}
        assert resp["is_bilateral"] is True
        # first series keeps PLAIN side keys (no namespace)
        assert all("/" not in k for k in resp["all_sides"])
    finally:
        sess.SESSIONS.pop(resp["session_id"], None)


def test_add_series_namespaces_and_cross_series_resolves(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    arr = np.zeros((4, 5, 6), np.int16)
    resp = sess._new_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    sid = resp["session_id"]
    try:
        s = sess._get_session(sid)
        add = sess._add_series(s, sid, arr, (1.0, 1.0, 1.0), {"series": "follow-up"})
        assert add["added"] is True
        assert add["series_id"] == "s1"
        assert [x["id"] for x in add["series"]] == ["s0", "s1"]
        assert add["series"][1]["name"] == "follow-up"
        # second series sides ARE namespaced
        assert set(add["all_sides"]) == {"left", "right", "s1/left", "s1/right"}
        # both the baseline (plain) and follow-up (namespaced) sides resolve —
        # this is what lets compare_sides receive "left" vs "s1/left".
        assert s["sides"].get("left") is not None
        assert s["sides"].get("s1/left") is not None
        assert s["sides"].get("s1/left")["side"] == "left"
    finally:
        sess.SESSIONS.pop(sid, None)


def test_third_series_gets_s2(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    arr = np.zeros((4, 5, 6), np.int16)
    resp = sess._new_session(arr, (1.0, 1.0, 1.0), {"series": "v1"}, layout="bilateral")
    sid = resp["session_id"]
    try:
        s = sess._get_session(sid)
        sess._add_series(s, sid, arr, (1.0, 1.0, 1.0), {"series": "v2"})
        add3 = sess._add_series(s, sid, arr, (1.0, 1.0, 1.0), {"series": "v3"})
        assert add3["series_id"] == "s2"
        assert "s2/left" in add3["all_sides"]
        assert len(add3["series"]) == 3
    finally:
        sess.SESSIONS.pop(sid, None)


def test_upload_with_session_id_adds_series(monkeypatch):
    """POST /upload?session_id=<sid> appends a series rather than creating one."""
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    monkeypatch.setattr(core_ingest, "is_mesh", lambda p: False)
    arr = np.zeros((4, 5, 6), np.int16)
    monkeypatch.setattr(
        pipeline, "load_volume_from_source",
        lambda dest, workdir: (arr, (1.0, 1.0, 1.0), {"format": "nii.gz"}),
    )

    # seed a first session directly
    first = sess._new_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    sid = first["session_id"]
    try:
        r = CLIENT.post(
            f"/api/upload?session_id={sid}",
            files={"file": ("followup.nii.gz", b"dummy-bytes", "application/gzip")},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["added"] is True
        assert j["series_id"] == "s1"
        # the added series' name defaults to the uploaded filename
        assert j["series"][1]["name"] == "followup.nii.gz"
        assert "s1/left" in j["all_sides"]
    finally:
        sess.SESSIONS.pop(sid, None)


def test_upload_without_session_id_is_new_session(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    monkeypatch.setattr(core_ingest, "is_mesh", lambda p: False)
    arr = np.zeros((4, 5, 6), np.int16)
    monkeypatch.setattr(
        pipeline, "load_volume_from_source",
        lambda dest, workdir: (arr, (1.0, 1.0, 1.0), {"format": "nii.gz"}),
    )
    r = CLIENT.post(
        "/api/upload",
        files={"file": ("scan.nii.gz", b"dummy-bytes", "application/gzip")},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    try:
        # brand-new single-series session, plain side keys
        assert [s["id"] for s in j["series"]] == ["s0"]
        assert "added" not in j
        assert all("/" not in k for k in j["all_sides"])
    finally:
        sess.SESSIONS.pop(j["session_id"], None)
