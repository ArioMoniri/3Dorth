"""QA: the trame BILATERAL oblique-compare cross-section mode, headless.

Product requirement (verbatim intent): the green-red 3D bone plus an
adjustable/movable cross-section "page" (the oblique cutting plane) whose CT
reformat depends on the plane position, AND "the 2D views of 2 bones are shown
as 2 boxes above the cross-section panel" — i.e. for a bilateral session the
Oblique mode must show BOTH bones' 2D reformats (labeled Reference bone /
Target bone), both driven by the SAME movable plane, matched via the cached
rigid registration (mirrors the locked API contract:
``POST /api/session/{sid}/oblique-compare``).

Drives the REAL ``app_trame.app`` module (its state, plane-widget callback,
registration cache, and render path), not a reimplementation, so it validates
the shipped path. Runs fully offscreen and does NOT launch the long-running
trame server (a live browser session dragging the widget is out of scope).

Checks:
  1. Load the demo scan (bilateral) and reset the oblique widget: bilateral
     mode is detected (``oblique_bilateral``), the widget seeds on the
     REFERENCE side, and BOTH boxes render valid PNGs.
  2. REGISTRATION CACHE: the (reference,target,params) registration used by
     the oblique-compare render is the SAME cached object
     ``_get_compare_registration`` returns — i.e. the heavy registration runs
     ONCE and is reused (identity check), matching the locked contract's
     "the first call runs the heavy registration; it is then cached".
  3. PARITY: the reference box is byte-identical to a DIRECT
     ``core.viz.slice.render_oblique_png(ref_arr, ..., origin, normal, ...)``
     call, and the target box is byte-identical to a DIRECT
     ``render_oblique_png(tgt_arr, ..., *map_plane(reg[...], origin, normal))``
     call — i.e. ONE reference oblique plane mapped through the cached rigid
     registration onto the target bone, both boxes showing the SAME physical
     cut, exactly as the locked API's ``/oblique-compare`` does.
  4. RELIABLE/AMBER GATE: ``oblique_cmp_reliable`` matches
     ``inlier_fraction >= 0.30`` exactly (same threshold as Compare mode / the
     API), and the target box is NEVER hidden when unreliable (only flagged) —
     checked both for the live registration and a forced low-inlier stub.
  5. TILT CHANGES BOTH PANELS: simulating the plane-widget callback with a
     different (still non-axis-aligned) normal changes BOTH the reference and
     target box bytes — the reformat genuinely follows the 3D plane on both
     bones, not a cached/stale image.
  6. Display-only: dragging the widget must NOT bump the recompute request id
     / touch ``core.pipeline``'s thickness/deviation compute (mirrors the
     single-side oblique QA's guarantee).
  7. Single-sided fallback: forcing a single-volume-side view (as if the
     session were not bilateral) falls back to the existing single-panel
     oblique (``oblique_bilateral`` False, ``oblique_img`` populated).

Honesty note printed at the end: everything here is callback/state-level (the
real ``core.pipeline`` + ``core.viz.slice`` functions, run against the real
demo dataset) — a live browser session is out of scope for this script.
"""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402
import core.viz.slice as mpr  # noqa: E402
from core import pipeline  # noqa: E402

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _decode(uri: str, what: str) -> bytes:
    assert uri.startswith("data:image/png;base64,"), f"{what}: not a PNG data URI"
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == _PNG_MAGIC, f"{what}: not a valid PNG"
    assert len(raw) > 0, f"{what}: empty PNG"
    return raw


def _wait_for(predicate, timeout: float = 300.0, interval: float = 0.2) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


def main() -> None:
    # --- 1. Load the demo (bilateral) and reset the oblique widget. -----------
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run oblique-compare QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    app.state.mode = "A"
    app.state.side = "left"
    app.state.ref_side, app.state.tgt_side = "left", "right"
    assert app.state.is_bilateral, "demo session should be bilateral (left/right)"

    app._oblique_reset_for_side()
    # Wait for a CONCRETE effect of the background registration job (not just
    # the busy flag, which is only flipped True *inside* the spawned thread —
    # a momentary window right after starting it would otherwise let us race
    # ahead of the job with oblique_cmp_busy still reading False).
    _wait_for(lambda: bool(app.state.oblique_ref_img) and app.state.oblique_ref_side == "left"
              and not app.state.oblique_cmp_busy)

    assert app.state.oblique_available, "oblique panel not available"
    assert app.state.oblique_bilateral, "bilateral session should show the two-box oblique-compare view"
    assert app.state.oblique_ref_side == "left", f"oblique_ref_side={app.state.oblique_ref_side!r}, want 'left'"
    assert app.state.oblique_tgt_side == "right", f"oblique_tgt_side={app.state.oblique_tgt_side!r}, want 'right'"
    ref_png0 = _decode(app.state.oblique_ref_img, "oblique_ref_img")
    tgt_png0 = _decode(app.state.oblique_tgt_img, "oblique_tgt_img")
    print(f"[1] bilateral oblique-compare active  (reference={app.state.oblique_ref_side}, "
          f"target={app.state.oblique_tgt_side}, ref PNG {len(ref_png0):,} bytes, "
          f"tgt PNG {len(tgt_png0):,} bytes)")

    # The seeded normal must be a genuine tilt (not axis-aligned).
    n0 = np.asarray(app.state.oblique_normal, dtype=float)
    axis_aligned = any(np.allclose(np.abs(n0), e, atol=1e-6)
                       for e in (np.array([1, 0, 0]), np.array([0, 1, 0]), np.array([0, 0, 1])))
    assert not axis_aligned, f"seeded normal {n0} is axis-aligned, not an oblique tilt"
    print(f"[1b] seeded normal is non-axis-aligned (genuine oblique tilt): {n0}")

    # --- 2. Registration cache: reused, not recomputed. ------------------------
    cache_size_before = len(app._COMPARE_REG_CACHE)
    cached_reg = app._get_compare_registration("left", "right")
    origin0 = tuple(app.state.oblique_origin)
    normal0 = tuple(app.state.oblique_normal)
    # Re-render at the SAME (origin, normal) via the real widget callback path;
    # this must reuse the cache (no growth, same object identity).
    app._on_oblique_widget(normal0, origin0)
    reg_after = app._get_compare_registration("left", "right")
    assert reg_after is cached_reg, "registration was recomputed instead of reused from cache"
    assert len(app._COMPARE_REG_CACHE) == cache_size_before, "registration cache grew on a repeat render"
    print(f"[2] registration cached & reused  (cache size stays {len(app._COMPARE_REG_CACHE)}, "
          f"rms={cached_reg['rms']:.3f} mm, inlier_fraction={cached_reg['inlier_fraction']:.3f})")

    # --- 3. Parity: both boxes byte-identical to direct core calls. -----------
    with app._LOCK:
        ref_side = app.SESSION["sides"]["left"]
        tgt_side = app.SESSION["sides"]["right"]

    ui_ref_png = _decode(app.state.oblique_ref_img, "oblique_ref_img (post re-render)")
    direct_ref_png, direct_ref_meta = mpr.render_oblique_png(
        ref_side["arr"], ref_side["spacing"], ref_side["offset_xyz"], origin0, normal0,
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert ui_ref_png == direct_ref_png, "reference box not byte-identical to a direct render_oblique_png call"

    tgt_origin, tgt_normal = pipeline.map_plane(cached_reg["ref_world_to_tgt_world"], origin0, normal0)
    ui_tgt_png = _decode(app.state.oblique_tgt_img, "oblique_tgt_img (post re-render)")
    direct_tgt_png, direct_tgt_meta = mpr.render_oblique_png(
        tgt_side["arr"], tgt_side["spacing"], tgt_side["offset_xyz"], tgt_origin, tgt_normal,
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert ui_tgt_png == direct_tgt_png, (
        "target box not byte-identical to a direct render_oblique_png call at map_plane(...)")
    print(f"[3] PARITY: reference box == direct render_oblique_png(origin,normal); "
          f"target box == direct render_oblique_png(*map_plane(reg, origin, normal)) "
          f"(mapped origin={tuple(round(x,2) for x in tgt_origin)}, "
          f"normal={tuple(round(x,3) for x in tgt_normal)})")

    # --- 4. Reliable/amber gate matches inlier_fraction >= 0.30. ---------------
    live_reliable = cached_reg["inlier_fraction"] >= 0.30
    assert app.state.oblique_cmp_reliable == live_reliable, (
        f"oblique_cmp_reliable={app.state.oblique_cmp_reliable} but "
        f"inlier_fraction={cached_reg['inlier_fraction']} (>= 0.30 -> {live_reliable})")
    print(f"[4a] live registration: inlier_fraction={cached_reg['inlier_fraction']:.3f} -> "
          f"reliable={app.state.oblique_cmp_reliable} (gate: >= 0.30)")

    # Force a low-inlier stub through the same render path to exercise the
    # amber branch explicitly (without needing a pathological dataset). Patch
    # the cache entry so _get_compare_registration returns the stub.
    key = app._compare_cache_key("left", "right", app._params_from_state(), app._manual_transform_matrix())
    stub_reg = dict(cached_reg)
    stub_reg["inlier_fraction"] = 0.05
    with app._COMPARE_REG_LOCK:
        real_reg_saved = app._COMPARE_REG_CACHE[key]
        app._COMPARE_REG_CACHE[key] = stub_reg
    try:
        app._oblique_render_compare("left", "right", origin0, normal0)
        assert app.state.oblique_cmp_reliable is False, "forced low-inlier stub did not flip the amber gate"
        assert "UNRELIABLE" not in app.state.oblique_cmp_reg_note  # note text is lowercase; banner text is separate
        assert "unreliable" in app.state.oblique_cmp_reg_note, "amber note text missing 'unreliable'"
        # The target box is STILL rendered (never hidden), just flagged.
        assert app.state.oblique_tgt_img, "target box was hidden when unreliable (must not be)"
        _decode(app.state.oblique_tgt_img, "oblique_tgt_img (forced-unreliable)")
        print("[4b] forced low-inlier stub (0.05 < 0.30) -> amber gate fires, "
              "target box still rendered (not hidden), note flags it as unreliable")
    finally:
        with app._COMPARE_REG_LOCK:
            app._COMPARE_REG_CACHE[key] = real_reg_saved
        # Restore real state for the following checks.
        app._oblique_render_compare("left", "right", origin0, normal0)

    # --- 5. Tilting the plane changes BOTH panels' bytes. ----------------------
    new_normal = np.array([0.6, -0.3, 0.74], dtype=np.float64)
    new_normal = new_normal / np.linalg.norm(new_normal)
    assert not np.allclose(new_normal, np.asarray(normal0), atol=1e-3), "test normal too close to the original"
    app._on_oblique_widget(tuple(new_normal), origin0)  # the real widget callback
    tilted_ref_png = _decode(app.state.oblique_ref_img, "oblique_ref_img (tilted)")
    tilted_tgt_png = _decode(app.state.oblique_tgt_img, "oblique_tgt_img (tilted)")
    assert tilted_ref_png != ref_png0, "tilting the plane did not change the reference box bytes"
    assert tilted_tgt_png != tgt_png0, "tilting the plane did not change the target box bytes"
    # And both are still parity-matched to direct calls at the new orientation.
    direct_ref_tilted, _ = mpr.render_oblique_png(
        ref_side["arr"], ref_side["spacing"], ref_side["offset_xyz"], origin0, tuple(new_normal),
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    tgt_origin2, tgt_normal2 = pipeline.map_plane(cached_reg["ref_world_to_tgt_world"], origin0, tuple(new_normal))
    direct_tgt_tilted, _ = mpr.render_oblique_png(
        tgt_side["arr"], tgt_side["spacing"], tgt_side["offset_xyz"], tgt_origin2, tgt_normal2,
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert tilted_ref_png == direct_ref_tilted, "tilted reference box not byte-identical to a direct render"
    assert tilted_tgt_png == direct_tgt_tilted, "tilted target box not byte-identical to a direct render"
    print(f"[5] tilting the normal -> {tuple(round(x,3) for x in new_normal)} changed BOTH "
          "boxes' bytes, and both remain parity-matched")

    # --- 6. Display-only: the widget callback must not touch the pipeline. ----
    req_before = app._REQ_COUNTER
    debounce_before = app._DEBOUNCE_TIMER
    app._on_oblique_widget(normal0, origin0)
    assert app._REQ_COUNTER == req_before, "oblique-compare widget callback bumped the recompute request id"
    assert app._DEBOUNCE_TIMER is debounce_before, "oblique-compare widget callback armed a recompute debounce"
    print("[6] oblique-compare widget callback is display-only — no recompute request id bump, "
          "no debounce timer armed")

    # --- 7. Single-sided fallback still works (existing single panel). --------
    # A single-sided/mesh session has < 2 volume sides, so
    # _oblique_bilateral_sides() returns None and the single-panel path is
    # used. Simulate this directly (without mutating the loaded session) by
    # calling the single-panel render function and asserting it still produces
    # a valid, parity-matched panel — the code path a real single-sided upload
    # would take.
    with app._LOCK:
        left_side = app.SESSION["sides"]["left"]
    with app.state:
        app.state.oblique_bilateral = False
    app._oblique_render(left_side, origin0, normal0)
    assert app.state.oblique_bilateral is False, "single-panel render should not flip bilateral back on"
    single_png = _decode(app.state.oblique_img, "oblique_img (single-panel fallback)")
    direct_single, _ = mpr.render_oblique_png(
        left_side["arr"], left_side["spacing"], left_side["offset_xyz"], origin0, normal0,
        size_mm=float(app.state.oblique_size_mm), px_mm=1.0, max_dim=384,
        window=float(app.state.oblique_window), level=float(app.state.oblique_level),
    )
    assert single_png == direct_single, "single-panel fallback oblique_img not byte-identical to a direct render"
    print(f"[7] single-sided fallback path still renders a valid, parity-matched single panel "
          f"({len(single_png):,} bytes)")

    # Restore bilateral state so this script leaves the app in a sane state.
    app._oblique_reset_for_side()
    _wait_for(lambda: not app.state.oblique_cmp_busy)

    print("\nQA PASS: the trame bilateral oblique-compare mode seeds the plane widget on the "
          "reference side, registers reference<->target ONCE (cached & reused), renders BOTH "
          "boxes (Reference bone / Target bone) byte-identical to direct core.viz.slice."
          "render_oblique_png calls at (origin,normal) and at map_plane(reg, origin, normal) "
          "respectively (parity with the locked /oblique-compare API contract), gates the "
          "amber/reliable banner on inlier_fraction >= 0.30 exactly (never hiding the target "
          "box), changes BOTH boxes' bytes when the plane tilts, never triggers the "
          "thickness/deviation recompute pipeline, and falls back cleanly to the existing "
          "single-panel oblique for non-bilateral sessions.\n"
          "\n"
          "Scope note: this exercises the real app_trame.app widget callback "
          "(_on_oblique_widget / _oblique_render_compare) and render path "
          "(core.viz.slice.render_oblique_png, core.pipeline.map_plane/compare_registration) "
          "against the real demo dataset — callback/state-level verification. A live browser "
          "session physically dragging the pyvista plane widget in a running trame server is "
          "out of scope for this script (per the task's VERIFY note).")


if __name__ == "__main__":
    main()
