"""Fig-2 measurement tools: sampling line (panel A) + height bracket (panel B)."""
import numpy as np
import pyvista as pv

from core.measurement import (
    HeightMeasurement,
    LinePoint,
    measure_height,
    sample_line_on_surface,
    sample_line_overlay,
    valid_height,
)


def _box_mesh(sx=10.0, sy=20.0, sz=30.0, n=12):
    """Axis-aligned box [0,sx]x[0,sy]x[0,sz] as a triangulated surface."""
    box = pv.Box(bounds=(0.0, sx, 0.0, sy, 0.0, sz)).triangulate()
    # subdivide so there are dense vertices to snap to along faces
    box = box.subdivide(3)
    return box


def test_sample_line_returns_n_points_with_linear_scalar():
    """On a box whose per-vertex scalar equals the x-coordinate, points sampled
    along a line at x=2,5,8 read back ~2,5,8 mm."""
    mesh = _box_mesh()
    mesh["thickness"] = np.asarray(mesh.points)[:, 0].astype(np.float32)  # scalar == x
    # a line across the top face (z=30) from x=2 to x=8 at y=10
    p0 = (2.0, 10.0, 30.0)
    p1 = (8.0, 10.0, 30.0)
    pts = sample_line_on_surface(mesh, "thickness", p0, p1, n=3)
    assert len(pts) == 3
    assert all(isinstance(p, LinePoint) for p in pts)
    xs = [p.value_mm for p in pts]
    # values track x position of the (evenly spaced, snapped) samples
    assert abs(xs[0] - 2.0) < 1.5
    assert abs(xs[1] - 5.0) < 1.5
    assert abs(xs[2] - 8.0) < 1.5
    # param_t evenly spaced 0, .5, 1
    ts = [p.param_t for p in pts]
    assert np.allclose(ts, [0.0, 0.5, 1.0], atol=1e-6)
    # indices are valid vertex ids
    for p in pts:
        assert 0 <= p.index < mesh.n_points


def test_sample_line_overlay_geometry_and_label():
    mesh = _box_mesh()
    mesh["thickness"] = np.asarray(mesh.points)[:, 0].astype(np.float32)
    pts = sample_line_on_surface(mesh, "thickness", (2.0, 10.0, 30.0),
                                 (8.0, 10.0, 30.0), n=3)
    markers, line, label = sample_line_overlay(pts)
    assert isinstance(markers, pv.PolyData)
    assert isinstance(line, pv.PolyData)
    assert markers.n_points > 0  # triangle markers exist
    assert line.n_points >= 2
    assert label == "Cortical thickness"


def test_sample_line_default_n_is_three():
    mesh = _box_mesh()
    mesh["thickness"] = np.asarray(mesh.points)[:, 0].astype(np.float32)
    pts = sample_line_on_surface(mesh, "thickness", (1.0, 10.0, 30.0),
                                 (9.0, 10.0, 30.0))
    assert len(pts) == 3


def test_measure_height_full_extent_box():
    """A 10x20x30 mm box measures 30 mm along z (full extent, default planes)."""
    mesh = _box_mesh(10.0, 20.0, 30.0)
    h = measure_height(mesh, axis="z")
    assert isinstance(h, HeightMeasurement)
    assert abs(h.height_mm - 30.0) < 1e-3
    # x and y too
    assert abs(measure_height(mesh, axis="x").height_mm - 10.0) < 1e-3
    assert abs(measure_height(mesh, axis="y").height_mm - 20.0) < 1e-3


def test_measure_height_with_bounds():
    mesh = _box_mesh(10.0, 20.0, 30.0)
    h = measure_height(mesh, axis="z", lower=5.0, upper=25.0)
    assert abs(h.height_mm - 20.0) < 1e-3
    # overlay geometry present + label
    assert isinstance(h.overlay, pv.PolyData)
    assert h.overlay.n_points >= 2
    assert h.label == "Height"


def test_measure_height_on_points_array():
    pts = np.array([[0, 0, 3.0], [1, 1, 13.0], [2, 2, 7.0]])
    h = measure_height(pts, axis="z")
    assert abs(h.height_mm - 10.0) < 1e-9


def _grid_plane(nz=31, ny=11, z_max=30.0, y_max=20.0):
    """A dense z-y plane whose vertices sit on an exact 1 mm z-grid, so band
    edges can align exactly with vertex positions (analytic answers)."""
    zz, yy = np.meshgrid(np.linspace(0.0, z_max, nz), np.linspace(0.0, y_max, ny))
    xx = np.zeros_like(zz)
    grid = pv.StructuredGrid(xx, yy, zz)
    return grid.extract_surface(algorithm="dataset_surface").triangulate()


def test_valid_height_band_region():
    """A dense plane whose scalar equals z (0..30, integer grid). Selecting the
    band [10,20] gives a connected region with z-extent exactly 10 mm."""
    mesh = _grid_plane(nz=31, ny=11, z_max=30.0, y_max=20.0)
    z = np.asarray(mesh.points)[:, 2].astype(np.float32)
    mesh["scalar"] = z  # color == z height, vertices at integer z
    vh = valid_height(mesh, "scalar", band=(10.0, 20.0), axis="z")
    assert isinstance(vh, HeightMeasurement)
    assert abs(vh.height_mm - 10.0) < 1e-4
    assert vh.label == "Height"


def test_valid_height_picks_smallest_component():
    """Two disjoint z-bands share the same color value; valid_height reports the
    MINIMUM height among the connected same-color regions."""
    mesh = _grid_plane(nz=41, ny=11, z_max=40.0, y_max=20.0)
    z = np.asarray(mesh.points)[:, 2]
    scalar = np.zeros(mesh.n_points, dtype=np.float32)
    # band-colored: a thin z in [5,10] (5 mm) and a thicker z in [25,40] (15 mm)
    scalar[(z >= 5.0) & (z <= 10.0)] = 1.0
    scalar[(z >= 25.0) & (z <= 40.0)] = 1.0
    mesh["scalar"] = scalar
    vh = valid_height(mesh, "scalar", band=(0.5, 1.5), axis="z")
    # smallest connected same-color region spans exactly 5 mm
    assert abs(vh.height_mm - 5.0) < 1e-4
