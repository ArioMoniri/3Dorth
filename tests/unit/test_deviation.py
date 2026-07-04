"""Tests for core.deviation — signed surface deviation (Mode B).

The sign is safety-critical: with ``convention='target_outside_positive'`` a
target vertex OUTSIDE the closed reference surface must be POSITIVE (bone
gain / hypertrophy), inside must be NEGATIVE.

Fixtures use concentric spheres with KNOWN geometry so the signed distance has
a provable answer (the radial gap between the two shells).
"""

from __future__ import annotations

import numpy as np
import pytest
import pyvista as pv

from core.deviation import (
    DeviationStats,
    cross_check,
    deviation_figure,
    deviation_histogram,
    deviation_stats,
    signed_distance,
)


def _sphere(radius: float, center=(0.0, 0.0, 0.0)) -> pv.PolyData:
    # High resolution so the discretised surface is close to the ideal sphere.
    s = pv.Sphere(radius=radius, center=center,
                  theta_resolution=90, phi_resolution=90)
    return s.triangulate().clean()


# --------------------------------------------------------------------------- #
# Sign + magnitude
# --------------------------------------------------------------------------- #
def test_target_outside_reference_is_positive():
    """Larger target vs smaller reference -> all POSITIVE, ~ radius gap."""
    target = _sphere(10.0)      # outer shell
    reference = _sphere(7.0)    # inner shell
    dev = signed_distance(target, reference, convention="target_outside_positive")

    assert dev.shape[0] == target.n_points
    assert np.all(dev > 0), "target outside reference must be positive"
    # every target vertex sits ~3 mm outside the reference sphere
    assert np.mean(dev) == pytest.approx(3.0, abs=0.15)
    assert np.max(np.abs(dev - 3.0)) < 0.3


def test_target_inside_reference_is_negative():
    """Swap -> smaller target inside larger reference -> all NEGATIVE."""
    target = _sphere(7.0)
    reference = _sphere(10.0)
    dev = signed_distance(target, reference, convention="target_outside_positive")

    assert np.all(dev < 0), "target inside reference must be negative"
    assert np.mean(dev) == pytest.approx(-3.0, abs=0.15)


def test_convention_flips_sign():
    """The negative convention flips the sign of every vertex."""
    target = _sphere(10.0)
    reference = _sphere(7.0)
    pos = signed_distance(target, reference, "target_outside_positive")
    neg = signed_distance(target, reference, "target_outside_negative")
    assert np.allclose(pos, -neg, atol=1e-6)
    assert np.all(neg < 0)


def test_invalid_convention_raises():
    target = _sphere(10.0)
    reference = _sphere(7.0)
    with pytest.raises(ValueError):
        signed_distance(target, reference, convention="nonsense")


# --------------------------------------------------------------------------- #
# Cross-check: two independent implementations agree
# --------------------------------------------------------------------------- #
def test_cross_check_small_disagreement():
    target = _sphere(10.0)
    reference = _sphere(7.0)
    med = cross_check(target, reference)
    assert med < 0.05, f"vtk vs trimesh median abs diff too large: {med}"


# --------------------------------------------------------------------------- #
# Stats: known field -> known added/removed split
# --------------------------------------------------------------------------- #
def test_deviation_stats_known_field():
    # 4 vertices, each with 1 mm^2 area. Two +2mm, two -1mm.
    dev = np.array([2.0, 2.0, -1.0, -1.0], dtype=np.float64)
    areas = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float64)
    st = deviation_stats(dev, areas=areas)
    assert isinstance(st, DeviationStats)
    assert st.n == 4
    assert st.mean == pytest.approx(0.5)
    assert st.median == pytest.approx(0.5)
    assert st.max_positive == pytest.approx(2.0)
    assert st.max_negative == pytest.approx(-1.0)
    # rms = sqrt((4+4+1+1)/4) = sqrt(2.5)
    assert st.rms == pytest.approx(np.sqrt(2.5))
    # added volume = sum(pos dev * area) = 2*1 + 2*1 = 4 mm^3 = 0.004 cc
    assert st.added_volume_cc == pytest.approx(4.0 / 1000.0)
    # removed volume magnitude = 1*1 + 1*1 = 2 mm^3 = 0.002 cc (reported positive)
    assert st.removed_volume_cc == pytest.approx(2.0 / 1000.0)


def test_deviation_stats_thresholds():
    dev = np.array([0.5, 1.5, 2.5, -1.5, -2.5], dtype=np.float64)
    st = deviation_stats(dev)
    assert st.n == 5
    # over +1mm: 1.5, 2.5 -> 2/5 = 40%
    assert st.pct_over_1mm_pos == pytest.approx(40.0)
    # over +2mm: 2.5 -> 1/5 = 20%
    assert st.pct_over_2mm_pos == pytest.approx(20.0)
    # over -1mm (more negative than): -1.5, -2.5 -> 40%
    assert st.pct_over_1mm_neg == pytest.approx(40.0)
    assert st.pct_over_2mm_neg == pytest.approx(20.0)


def test_deviation_stats_no_areas():
    dev = np.array([1.0, -1.0], dtype=np.float64)
    st = deviation_stats(dev)
    # volumes require areas; without them they are 0
    assert st.added_volume_cc == 0.0
    assert st.removed_volume_cc == 0.0
    assert st.n == 2


def test_histogram_counts():
    dev = np.array([-1.0, -1.0, 1.0, 1.0, 1.0], dtype=np.float64)
    bins, counts = deviation_histogram(dev, n_bins=2, value_range=(-2.0, 2.0))
    assert counts.sum() == 5
    assert len(bins) == 3  # n_bins + 1 edges
    assert counts[0] == 2  # the two -1.0 values
    assert counts[1] == 3  # the three +1.0 values


# --------------------------------------------------------------------------- #
# Render helper
# --------------------------------------------------------------------------- #
def test_deviation_figure_writes_png(tmp_path):
    from core.parameters import default_parameters

    target = _sphere(10.0)
    reference = _sphere(7.0)
    dev = signed_distance(target, reference)
    out = tmp_path / "dev.png"
    p = deviation_figure(target, dev, default_parameters(), out)
    assert p.exists()
    assert p.stat().st_size > 0
