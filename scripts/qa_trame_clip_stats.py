"""QA: trame parity features — Mode B hover scalars, histogram, clip + visible
stats.

Drives the REAL ``app_trame.app`` module (its state and callbacks), not a
reimplementation, so it validates the shipped path. Runs fully offscreen and
does NOT launch the long-running trame server.

Checks:
  1. MODE A (thickness map): compute, then enable a clip that keeps a STRICT
     SUBSET of vertices; assert the "visible part" stats (mean/n) are computed
     from the CLIPPED mesh (not re-derived) and ``n`` is strictly less than the
     "total" (whole map) ``n``.
  2. HISTOGRAM: ``state.histogram_bins`` bin counts sum to the number of finite
     vertices on the active mesh (honesty: no vertex silently dropped/added).
  3. MODE B (deviation): the mesh returned by ``core.pipeline.compare_sides``
     (and adopted into ``_LAST_MESH["deviation"]``) carries all four scalars
     (deviation_mm / ref_thickness_mm / tgt_thickness_mm / thickness_diff_mm);
     the hover/pick path (``_on_hover``) reads all four at a picked vertex and
     the tooltip HTML mentions each one.
  4. Clip + visible stats also works for Mode B (deviation) — a strict subset
     again, and the recomputed visible mean can legitimately differ from the
     whole-map mean (both sourced from the mesh's own point data).

Honesty note printed at the end: everything here is callback/state-level (the
real ``core.pipeline`` + ``app_trame.app`` functions run against the real demo
data) — a live browser session is out of scope for this script (see the task's
VERIFY note).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402


def _load_demo_bilateral() -> None:
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run clip/stats QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()


def main() -> None:
    # --- 0. Load the demo (bilateral). ---------------------------------------
    _load_demo_bilateral()
    print(f"[0] demo loaded; sides = {app._side_names()}")

    # ======================================================================= #
    # MODE A: thickness map + clip / visible-part stats + histogram
    # ======================================================================= #
    with app.state:
        app.state.mode = "A"
        app.state.side = "left"
    app._compute_worker(app._next_request_id())

    mesh_a = app._LAST_MESH["thickness"]
    assert mesh_a is not None, "Mode A compute did not populate _LAST_MESH['thickness']"
    assert "thickness_mm" in mesh_a.point_data
    total_n = int(mesh_a.n_points)
    print(f"[1] Mode A thickness computed: {total_n:,} vertices")

    # Histogram (no clip yet): bins must sum to the finite vertex count.
    app.refresh_histogram_and_clip()
    assert app.state.histogram_img.startswith("data:image/png;base64,"), \
        "histogram_img is not a PNG data URI"
    bins = app.state.histogram_bins
    thickness_vals = np.asarray(mesh_a.point_data["thickness_mm"], dtype=np.float64)
    finite_n = int(np.isfinite(thickness_vals).sum())
    bin_sum = int(sum(bins["counts"]))
    assert bin_sum == finite_n == bins["n"], (
        f"histogram bin counts ({bin_sum}) != finite vertex count ({finite_n}) "
        f"!= reported n ({bins['n']})")
    print(f"[2] histogram: {len(bins['counts'])} bins sum to {bin_sum} "
          f"(== {finite_n} finite vertices)")

    # Enable a clip that keeps a STRICT SUBSET (fraction 0.5 on the x axis is
    # guaranteed to be strict on a real bone surface: it's not flat in x).
    with app.state:
        app.state.clip_enabled = True
        app.state.clip_axis = "x"
        app.state.clip_fraction = 0.5
        app.state.clip_invert = False
    app.refresh_histogram_and_clip()

    total_stats = app.state.clip_total_stats
    visible_stats = app.state.clip_visible_stats
    assert total_stats["n"] == total_n, (
        f"total stats n ({total_stats['n']}) != mesh n_points ({total_n})")
    assert visible_stats["n"] < total_stats["n"], (
        f"clip did not reduce the vertex count: visible={visible_stats['n']} "
        f"total={total_stats['n']}")
    assert visible_stats["n"] > 0, "clip removed ALL vertices (fraction=0.5 should be strict)"

    # Verify the visible-part stats really come from the CLIPPED mesh's own
    # scalar, not merely re-labeled totals: recompute independently via
    # core.pipeline's clip call path (mesh.clip) and compare exactly.
    clipped = app._clip_mesh(mesh_a, "x", 0.5, False)
    direct_vals = np.asarray(clipped.point_data["thickness_mm"], dtype=np.float64)
    direct_stats = app._scalar_stats(direct_vals)
    assert visible_stats == direct_stats, (
        f"visible stats {visible_stats} do not match a direct clipped-mesh "
        f"recomputation {direct_stats}")
    print(f"[3] clip (Mode A): visible n={visible_stats['n']:,} < total "
          f"n={total_stats['n']:,}; visible mean={visible_stats['mean']} "
          f"matches a direct clipped-mesh recomputation")

    # Histogram after clip: total bins still sum to the WHOLE map (never
    # silently narrowed to the clip) — the highlight overlay is separate.
    app.refresh_histogram_and_clip()
    bins2 = app.state.histogram_bins
    assert int(sum(bins2["counts"])) == finite_n, (
        "histogram bins changed vertex accounting after enabling clip — "
        "the TOTAL histogram must still cover the whole map")
    print(f"[4] histogram after clip still sums to the WHOLE map "
          f"({int(sum(bins2['counts']))} == {finite_n})")

    # Disable the clip; visible stats must fall back to the total.
    with app.state:
        app.state.clip_enabled = False
    app.refresh_histogram_and_clip()
    assert app.state.clip_visible_stats == app.state.clip_total_stats, (
        "disabling the clip did not restore visible == total stats")
    print("[5] disabling the clip restores visible == total stats")

    # ======================================================================= #
    # MODE B: deviation mesh carries the four thickness scalars + hover reads them
    # ======================================================================= #
    with app.state:
        app.state.mode = "B"
        app.state.b_view = "deviation"
        app.state.ref_side = "left"
        app.state.tgt_side = "right"
    app._compute_worker(app._next_request_id())

    mesh_b = app._LAST_MESH["deviation"]
    assert mesh_b is not None, "Mode B compute did not populate _LAST_MESH['deviation']"
    required = ["deviation_mm", "ref_thickness_mm", "tgt_thickness_mm", "thickness_diff_mm"]
    for key in required:
        assert key in mesh_b.point_data, f"Mode B mesh missing point_data[{key!r}]"
    print(f"[6] Mode B mesh carries all four scalars: {required} "
          f"({mesh_b.n_points:,} vertices)")

    # thickness_diff_mm must equal ref - tgt at every finite vertex (honesty:
    # it's a derived field, not an independently fabricated one).
    ref_th = np.asarray(mesh_b.point_data["ref_thickness_mm"], dtype=np.float64)
    tgt_th = np.asarray(mesh_b.point_data["tgt_thickness_mm"], dtype=np.float64)
    diff = np.asarray(mesh_b.point_data["thickness_diff_mm"], dtype=np.float64)
    finite = np.isfinite(ref_th) & np.isfinite(tgt_th) & np.isfinite(diff)
    assert finite.any(), "no finite vertices to check thickness_diff_mm against"
    np.testing.assert_allclose(diff[finite], (ref_th - tgt_th)[finite], atol=1e-6)
    print("[7] thickness_diff_mm == ref_thickness_mm - tgt_thickness_mm "
          f"at all {int(finite.sum()):,} finite vertices")

    # Hover/pick: read all four scalars at a real picked vertex via the actual
    # _on_hover callback (world point -> find_closest_point -> point_data).
    pid = mesh_b.n_points // 3
    world_point = np.asarray(mesh_b.points[pid], dtype=float)
    app._on_hover(world_point)
    assert app.state.hover_active, "hover did not activate for an on-surface point"
    hover_html = app.state.hover_html
    for label in ("Deviation", "Reference thickness", "Target thickness",
                 "Thickness diff"):
        assert label in hover_html, f"hover tooltip missing {label!r}: {hover_html}"
    # Cross-check the reported deviation value against the mesh directly.
    found_pid = mesh_b.find_closest_point(world_point)
    expected_dev = float(mesh_b.point_data["deviation_mm"][found_pid])
    assert f"{expected_dev:+.2f}" in hover_html or f"{expected_dev:.2f}" in hover_html, (
        f"hover tooltip deviation value doesn't match the mesh at the picked "
        f"vertex (expected {expected_dev:+.2f})")
    print(f"[8] hover at picked vertex {found_pid} surfaces all four scalars; "
          f"deviation {expected_dev:+.2f} mm matches the mesh directly")

    # Clip + visible stats also works for Mode B (deviation).
    with app.state:
        app.state.clip_enabled = True
        app.state.clip_axis = "z"
        app.state.clip_fraction = 0.5
        app.state.clip_invert = False
    app.refresh_histogram_and_clip()
    total_b = app.state.clip_total_stats
    visible_b = app.state.clip_visible_stats
    assert total_b["n"] == mesh_b.n_points
    assert 0 < visible_b["n"] < total_b["n"], (
        f"Mode B clip did not produce a strict subset: visible={visible_b['n']} "
        f"total={total_b['n']}")
    print(f"[9] clip (Mode B deviation): visible n={visible_b['n']:,} < total "
          f"n={total_b['n']:,}")

    with app.state:
        app.state.clip_enabled = False

    print("\nQA PASS: Mode B hover surfaces reference/target thickness + "
          "difference + deviation from the mesh's own point data; the "
          "histogram's bins account for every finite vertex; the clip "
          "isolates a strict sub-part of the surface and 'visible part' "
          "stats are recomputed from that clipped mesh (both Mode A "
          "thickness and Mode B deviation) — display-only, no "
          "thickness/deviation recompute pipeline touched. "
          "(callback/state-level; live browser out of scope.)")


if __name__ == "__main__":
    main()
