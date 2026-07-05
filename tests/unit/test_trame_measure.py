"""Measure tool (trame): click two surface points -> straight-line mm distance.

Pins the point-accumulation state machine and the distance math. Rendering
(pyvista actors) is a side effect exercised separately; here we assert the
logic — 1st click waits for the 2nd, 2nd click yields the distance, a 3rd click
starts a fresh pair.
"""
import pytest

trame_app = pytest.importorskip("app_trame.app")


@pytest.fixture(autouse=True)
def _reset_measure():
    trame_app._MEASURE_PTS.clear()
    trame_app.state.measure_dist_mm = None
    yield
    trame_app._MEASURE_PTS.clear()


def test_two_clicks_give_euclidean_distance():
    trame_app._on_measure_pick([0.0, 0.0, 0.0])
    assert len(trame_app._MEASURE_PTS) == 1
    assert trame_app.state.measure_dist_mm is None  # waiting for 2nd point

    trame_app._on_measure_pick([3.0, 4.0, 0.0])  # 3-4-5 triangle
    assert len(trame_app._MEASURE_PTS) == 2
    assert trame_app.state.measure_dist_mm == 5.0


def test_third_click_starts_a_new_pair():
    trame_app._on_measure_pick([0.0, 0.0, 0.0])
    trame_app._on_measure_pick([0.0, 0.0, 2.0])
    assert trame_app.state.measure_dist_mm == 2.0
    # third click restarts from the new point
    trame_app._on_measure_pick([9.0, 9.0, 9.0])
    assert len(trame_app._MEASURE_PTS) == 1
    assert trame_app._MEASURE_PTS[0] == [9.0, 9.0, 9.0]
    assert trame_app.state.measure_dist_mm is None


def test_3d_distance_uses_all_axes():
    trame_app._on_measure_pick([1.0, 2.0, 3.0])
    trame_app._on_measure_pick([1.0 + 2.0, 2.0 + 3.0, 3.0 + 6.0])  # (2,3,6) -> 7
    assert trame_app.state.measure_dist_mm == 7.0


def test_clear_measure_resets():
    trame_app._on_measure_pick([0.0, 0.0, 0.0])
    trame_app._on_measure_pick([1.0, 0.0, 0.0])
    trame_app.clear_measure()
    assert trame_app._MEASURE_PTS == []
    assert trame_app.state.measure_dist_mm is None
