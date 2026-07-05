"""Trame multi-series data model — parity with the React/API multi-series feature
(tests/unit/test_api_multi_series.py). A trame session can hold several uploaded
SERIES (baseline + follow-up …); the first keeps plain side names, later series
are namespaced ("s1/left"), and _side_label prefixes the series name once >1
series exist. The heavy segmentation (split_sides) is stubbed so the wiring — not
the segmentation — is exercised. Importing app_trame.app builds the server-side UI
but starts no server (bootstrap runs only under __main__).
"""
import numpy as np
import pytest

trame_app = pytest.importorskip("app_trame.app")
from core import pipeline


def _fake_sides(arr, spacing, layout="auto"):
    def side(name):
        return {"arr": arr, "spacing": spacing, "offset_xyz": (0.0, 0.0, 0.0), "side": name}
    return {"left": side("left"), "right": side("right")}


@pytest.fixture(autouse=True)
def _stub_split(monkeypatch):
    monkeypatch.setattr(pipeline, "split_sides", _fake_sides)
    # snapshot + restore module SESSION so tests don't leak into each other
    saved = dict(trame_app.SESSION)
    yield
    trame_app.SESSION.clear()
    trame_app.SESSION.update(saved)


def test_adopt_is_single_series_plain_sides():
    arr = np.zeros((4, 5, 6), np.int16)
    trame_app._adopt_volume_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    series = trame_app.SESSION["series"]
    assert [s["id"] for s in series] == ["s0"]
    assert series[0]["name"] == "baseline"
    assert all("/" not in k for k in trame_app.SESSION["sides"])
    # single series -> label has no series prefix
    assert trame_app._side_label("left") == "Left"


def test_add_series_namespaces_and_resolves():
    arr = np.zeros((4, 5, 6), np.int16)
    trame_app._adopt_volume_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")
    sid = trame_app._add_series(arr, (1.0, 1.0, 1.0), {"series": "follow-up"})
    assert sid == "s1"
    sides = trame_app.SESSION["sides"]
    assert set(sides) == {"left", "right", "s1/left", "s1/right"}
    assert sides.get("s1/left") is not None
    # once 2 series exist, labels are prefixed with the series name
    assert trame_app._side_label("left") == "baseline · Left"
    assert trame_app._side_label("s1/left") == "follow-up · Left"
    # compare picks two distinct volume sides
    pair = trame_app._compare_sides_available()
    assert pair is not None and pair[0] != pair[1]


def test_third_series_gets_s2():
    arr = np.zeros((4, 5, 6), np.int16)
    trame_app._adopt_volume_session(arr, (1.0, 1.0, 1.0), {"series": "v1"}, layout="bilateral")
    trame_app._add_series(arr, (1.0, 1.0, 1.0), {"series": "v2"})
    sid3 = trame_app._add_series(arr, (1.0, 1.0, 1.0), {"series": "v3"})
    assert sid3 == "s2"
    assert "s2/left" in trame_app.SESSION["sides"]
    assert len(trame_app.SESSION["series"]) == 3


def test_add_mesh_series_namespaced():
    arr = np.zeros((4, 5, 6), np.int16)
    trame_app._adopt_volume_session(arr, (1.0, 1.0, 1.0), {"series": "baseline"}, layout="bilateral")

    class _Mesh:
        n_points = 10
    sid = trame_app._add_series(None, None, {"series": "surf"}, mesh=_Mesh())
    assert sid == "s1"
    assert "s1/mesh" in trame_app.SESSION["sides"]
    assert trame_app.SESSION["sides"]["s1/mesh"]["side"] == "mesh"
