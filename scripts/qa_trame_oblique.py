"""QA: the trame oblique (arbitrary-tilt) cross-section mode, headless.

Goal (matches the product requirement): "the 3D image of the bone and the 2D
images should be matched up together at all points and viewable [as] any
shape / orientation of cross-section" — an ARBITRARY (tiltable, not just
axial/coronal/sagittal) cutting plane with a LIVE 2D reformat matched to the
3D cut at every point.

Drives the REAL ``app_trame.app`` module (its state, plane-widget callback,
and render path), not a reimplementation, so it validates the shipped path.
Runs fully offscreen and does NOT launch the long-running trame server (a
live browser session dragging the widget is out of scope — see the honesty
note printed at the end).

Checks:
  1. Load the demo scan (bilateral), point the oblique mode at the LEFT side,
     and seed the plane widget at the side's centre with a NON-axis-aligned
     normal (``_oblique_reset_for_side``).
  2. ``mpr.render_oblique_png`` returns a valid PNG (``b'PNG'`` after the
     ``\\x89`` magic byte) for that plane.
  3. PARITY: the app's oblique panel data URI (``state.oblique_img``) is
     BYTE-IDENTICAL to a DIRECT ``core.viz.slice.render_oblique_png`` call with
     the same origin/normal/window/level/size — the widget callback must not
     silently diverge from the locked core function.
  4. INVERSE ROUND-TRIP: ``mpr.oblique_pixel_to_world`` then
     ``mpr.world_to_oblique_pixel`` returns the same (row, col) for a spread of
     pixels, INCLUDING a corner — the pixel<->world mapping the API contract
     promises.
  5. TILT CHANGES IMAGE: simulating the plane-widget callback with a
     DIFFERENT (still non-axis-aligned) normal changes the rendered image
     bytes — the reformat genuinely follows the 3D plane, not a cached/stale
     image.
  6. The widget survives a scene rebuild (``build_thickness_scene`` calls
     ``plotter.clear()``/``clear_actors()``): re-render after a real compute
     and assert the panel is still valid + parity-matched.
  7. Display-only: dragging the widget must NOT bump the recompute request id
     / touch ``core.pipeline`` (mirrors the MPR/compare display-only guarantee).
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402
import core.viz.slice as mpr  # noqa: E402

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _decode_oblique_panel() -> bytes:
    uri = app.state.oblique_img
    assert uri.startswith("data:image/png;base64,"), "oblique_img: not a PNG data URI"
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == _PNG_MAGIC, "oblique_img: not a valid PNG"
    assert len(raw) > 0, "oblique_img: empty PNG"
    return raw


def main() -> None:
    # --- 1. Load the demo and point oblique mode at the LEFT side. ------------
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run oblique QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    app.state.side = "left"
    app._oblique_reset_for_side()

    assert app.state.oblique_available, "oblique panel not available for the demo left side"
    assert app.state.oblique_side == "left", f"oblique side is {app.state.oblique_side!r}, want 'left'"
    side = app._mpr_active_side()
    assert side is not None and side.get("arr") is not None, "no volume side for oblique mode"
    w = app.OBLIQUE_WIDGET.get("widget")
    assert w is not None, "plane widget was not created"
    print(f"[1] demo left side loaded; plane widget seeded at origin="
          f"{tuple(round(x, 2) for x in app.state.oblique_origin)} normal="
          f"{tuple(round(x, 3) for x in app.state.oblique_normal)}")

    # The seeded normal must be a genuine tilt (not axis-aligned) — that's the
    # whole point of "any shape / orientation of cross-section".
    n0 = np.asarray(app.state.oblique_normal, dtype=float)
    axis_aligned = any(np.allclose(np.abs(n0), e, atol=1e-6)
                       for e in (np.array([1, 0, 0]), np.array([0, 1, 0]), np.array([0, 0, 1])))
    assert not axis_aligned, f"seeded normal {n0} is axis-aligned, not an oblique tilt"
    print(f"[1b] seeded normal is non-axis-aligned (genuine oblique tilt): {n0}")

    # --- 2/3. Valid PNG AND byte-identical to a direct render_oblique_png. ----
    ui_png = _decode_oblique_panel()
    origin = tuple(app.state.oblique_origin)
    normal = tuple(app.state.oblique_normal)
    direct_png, direct_meta = mpr.render_oblique_png(
        side["arr"], side["spacing"], side["offset_xyz"], origin, normal,
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert direct_png[:8] == _PNG_MAGIC, "direct render_oblique_png: not a valid PNG"
    assert ui_png == direct_png, "oblique panel not byte-identical to core.viz.slice.render_oblique_png"
    print(f"[2] oblique PNG valid  ({len(ui_png):,} bytes)")
    print("[3] oblique panel byte-identical to a direct render_oblique_png call (parity)")

    # --- 4. Pixel<->world inverse round-trip, incl. a corner. -----------------
    size_px = direct_meta["size_px"]
    probes = [
        (0.0, 0.0),                                   # corner
        (size_px - 1.0, size_px - 1.0),               # opposite corner
        (size_px - 1.0, 0.0),
        ((size_px - 1) / 2.0, (size_px - 1) / 2.0),   # centre
        (7.0, 113.0),
    ]
    for row, col in probes:
        world = mpr.oblique_pixel_to_world(direct_meta, row, col)
        back_row, back_col = mpr.world_to_oblique_pixel(direct_meta, world)
        assert abs(back_row - row) < 1e-6, f"row round-trip failed: {row} -> {back_row}"
        assert abs(back_col - col) < 1e-6, f"col round-trip failed: {col} -> {back_col}"
    print(f"[4] oblique_pixel_to_world <-> world_to_oblique_pixel round-trips exactly "
          f"for {len(probes)} pixels (incl. a corner)")

    # --- 5. Tilting the normal changes the image bytes. ------------------------
    new_normal = np.array([0.6, -0.3, 0.74], dtype=np.float64)
    new_normal = new_normal / np.linalg.norm(new_normal)
    assert not np.allclose(new_normal, np.asarray(normal), atol=1e-3), "test normal too close to the original"
    app._on_oblique_widget(tuple(new_normal), origin)  # the real widget callback
    tilted_png = _decode_oblique_panel()
    assert tilted_png != ui_png, "tilting the plane normal did not change the reformat bytes"
    assert tuple(round(x, 6) for x in app.state.oblique_normal) == tuple(round(x, 6) for x in new_normal), (
        "state.oblique_normal did not adopt the widget's new normal")
    # And it is still parity-matched to a direct call at the new orientation.
    direct_tilted, _ = mpr.render_oblique_png(
        side["arr"], side["spacing"], side["offset_xyz"], origin, tuple(new_normal),
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert tilted_png == direct_tilted, "tilted oblique panel not byte-identical to a direct render"
    print(f"[5] tilting the normal -> {tuple(round(x,3) for x in new_normal)} changed the "
          "reformat bytes, and the new image is still parity-matched")

    # --- 6. The widget/panel survive a real scene rebuild. --------------------
    req_id = app._next_request_id()
    app.state.mode = "A"
    app._compute_worker(req_id)
    assert app._LAST_MESH["thickness"] is not None, "scene rebuild produced no mesh"
    widget_after = app.OBLIQUE_WIDGET.get("widget")
    assert widget_after is w, "plane widget was recreated (should persist across clear())"
    # Re-render once more to prove the panel is still functional post-rebuild.
    app._on_oblique_widget(tuple(new_normal), origin)
    post_rebuild_png = _decode_oblique_panel()
    assert post_rebuild_png == direct_tilted, "oblique panel stale/broken after a scene rebuild"
    print("[6] plane widget persists across plotter.clear()/clear_actors() "
          "(a real Mode A compute ran in between); oblique panel still renders correctly")

    # --- 7. Display-only: the widget callback must not touch the pipeline. ----
    req_before = app._REQ_COUNTER
    debounce_before = app._DEBOUNCE_TIMER
    app._on_oblique_widget(tuple(origin), tuple(normal))
    assert app._REQ_COUNTER == req_before, "oblique widget callback bumped the recompute request id"
    assert app._DEBOUNCE_TIMER is debounce_before, "oblique widget callback armed a recompute debounce"
    print("[7] oblique widget callback is display-only — no recompute request id bump, "
          "no debounce timer armed")

    print("\nQA PASS: the trame oblique cross-section mode seeds a genuinely tilted plane "
          "widget, renders a valid PNG reformat that is byte-identical to a direct "
          "core.viz.slice.render_oblique_png call (parity), round-trips pixel<->world "
          "exactly (incl. a corner), changes bytes when the plane tilts, survives a real "
          "scene rebuild, and never triggers the thickness/deviation recompute pipeline.\n"
          "\n"
          "Scope note: this exercises the real app_trame.app widget callback "
          "(_on_oblique_widget) and render path (core.viz.slice.render_oblique_png) against "
          "the real demo dataset — callback/state-level verification. A live browser session "
          "physically dragging the pyvista plane widget in a running trame server is out of "
          "scope for this script (per the task's VERIFY note).")


if __name__ == "__main__":
    main()
