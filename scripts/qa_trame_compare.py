"""QA: the trame Phase IV compare (linked cross-sections) + Phase V AR export.

Drives the REAL ``app_trame.app`` module (its state, cache and callbacks), not a
reimplementation, so it validates the shipped path. Runs fully offscreen and does
NOT launch the long-running trame server.

Checks:
  1. Load the demo scan (bilateral) and enable compare mode: two distinct volume
     sides ("left"/"right") are available and get registered once.
  2. REGISTRATION CACHE: a second reset for the SAME (ref, tgt, params) reuses the
     cached ``compare_registration`` result — no second (heavy) registration call.
  3. CROSSHAIR MAPPING: moving the reference crosshair maps the picked reference
     voxel -> world -> ``apply_affine(reg['ref_world_to_tgt_world'], ...)`` -> a
     target voxel, and the rendered target panels are byte-identical to a DIRECT
     ``core.viz.slice.render_slice_png`` call at that mapped index (parity with
     the API's compare-slice-map contract).
  4. REFERENCE panels are byte-identical to a direct ``render_slice_png`` call at
     the (clamped) reference voxel too.
  5. RELIABLE/AMBER GATE: ``cmp_reliable`` matches ``inlier_fraction >= 0.30``
     exactly (the same threshold as the API's ``_MIN_RELIABLE_INLIER``), checked
     both for the live (normal) registration and a forced low-inlier stub.
  6. A left-click on the 3D reference surface (compare mode active) drives the
     linked crosshair via ``_on_pick_to_mpr`` -> ``_on_pick_to_compare``.
  7. Phase V: ``export_mesh(..., fmt='glb')`` on the currently computed surface
     writes a file whose first 4 bytes are ``b'glTF'``, and the app's
     ``do_export_ar_glb`` control produces a real ``/downloads`` URL + on-disk
     file with the same magic bytes.

Honesty note printed at the end: everything here is callback/state-level (the
real ``core.pipeline`` + ``core.viz.slice`` + ``core.export.mesh`` functions, run
against the real demo data) — a live browser session is out of scope for this
script (see the task's VERIFY note).
"""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402
import core.viz.slice as mpr  # noqa: E402
from core import pipeline  # noqa: E402

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_GLB_MAGIC = b"glTF"


def _decode_panel(uri: str) -> bytes:
    assert uri.startswith("data:image/png;base64,"), "not a PNG data URI"
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == _PNG_MAGIC, "not a valid PNG"
    assert len(raw) > 0, "empty PNG"
    return raw


def _wait_for(predicate, timeout: float = 300.0, interval: float = 0.2) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


def main() -> None:
    # --- 1. Load the demo (bilateral) and enable compare mode. ----------------
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run compare QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    app.state.mode = "A"
    app.state.side = "left"
    app.state.ref_side, app.state.tgt_side = "left", "right"

    assert app.state.compare_available, "compare should be available for a bilateral scan"
    app.state.compare_active = True
    app.toggle_compare()
    _wait_for(lambda: not app.state.cmp_busy and app.state.cmp_ref_side == "left")
    assert app.state.cmp_ref_side == "left" and app.state.cmp_tgt_side == "right"
    print(f"[1] compare enabled  (reference={app.state.cmp_ref_side}, "
          f"target={app.state.cmp_tgt_side}, "
          f"inlier_fraction={app.state.cmp_inlier_fraction})")

    # --- 2. Registration cache: a second reset reuses the cached result. ------
    n_cache_before = len(app._COMPARE_REG_CACHE)
    key_before = next(iter(app._COMPARE_REG_CACHE))
    reg_before = app._COMPARE_REG_CACHE[key_before]
    with app.state:
        app.state.cmp_msg = "__qa_sentinel__"  # detect the new job actually started
    app._compare_reset()
    _wait_for(lambda: app.state.cmp_msg != "__qa_sentinel__")  # job claimed cmp_busy/msg
    _wait_for(lambda: not app.state.cmp_busy)
    n_cache_after = len(app._COMPARE_REG_CACHE)
    reg_after = app._COMPARE_REG_CACHE[key_before]
    assert n_cache_after == n_cache_before, "cache grew on a repeat (ref,tgt,params) reset"
    assert reg_after is reg_before, "registration was recomputed instead of reused from cache"
    print(f"[2] registration cache reused  (cache size stays {n_cache_after}, "
          "same object identity across resets)")

    # --- 3/4. Crosshair mapping: reference + target panels match core.viz.slice. -
    with app._LOCK:
        ref = app.SESSION["sides"]["left"]
        tgt = app.SESSION["sides"]["right"]
    nz, ny, nx = ref["arr"].shape
    probe_ijk = (nx // 3, ny // 2, nz // 2)
    reg = app._get_compare_registration("left", "right")
    app._compare_sync_from_ref_voxel(probe_ijk, reg=reg)

    # Reference panels byte-identical to a direct render at the (clamped) ref voxel.
    ref_shape = ref["arr"].shape
    expected_ref_sl = mpr.slices_from_voxel(probe_ijk, ref_shape)
    for plane, img_key, idx_key in (
        ("axial", "cmp_ref_img_axial", "cmp_idx_axial"),
        ("coronal", "cmp_ref_img_coronal", "cmp_idx_coronal"),
        ("sagittal", "cmp_ref_img_sagittal", "cmp_idx_sagittal"),
    ):
        assert int(app.state[idx_key]) == expected_ref_sl[plane], f"ref {plane} index mismatch"
        ui_png = _decode_panel(app.state[img_key])
        direct = mpr.render_slice_png(
            ref["arr"], ref["spacing"], plane, int(app.state[idx_key]),
            window=float(app.state.cmp_window), level=float(app.state.cmp_level), max_dim=384)
        assert ui_png == direct, f"reference {plane} panel not byte-identical"
    print("[3] reference panels byte-identical to core.viz.slice.render_slice_png "
          f"(voxel {probe_ijk})")

    # Target voxel = apply_affine(ref_world_to_tgt_world, ref_world); panels match
    # a DIRECT render at that mapped (clamped) index — the parity guarantee.
    ref_ix = mpr.clamp_index(ref_shape, "sagittal", probe_ijk[0])
    ref_iy = mpr.clamp_index(ref_shape, "coronal", probe_ijk[1])
    ref_iz = mpr.clamp_index(ref_shape, "axial", probe_ijk[2])
    ref_world = mpr.voxel_to_world((ref_ix, ref_iy, ref_iz), ref["spacing"], ref["offset_xyz"])
    tgt_world = pipeline.apply_affine(reg["ref_world_to_tgt_world"], ref_world)
    tgt_ijk = mpr.world_to_voxel(tgt_world, tgt["spacing"], tgt["offset_xyz"])
    assert (app.state.cmp_tgt_ix, app.state.cmp_tgt_iy, app.state.cmp_tgt_iz) == tuple(
        int(v) for v in tgt_ijk), "matched target voxel does not match apply_affine mapping"
    expected_tgt_sl = mpr.slices_from_voxel(tgt_ijk, tgt["arr"].shape)
    for plane, img_key in (
        ("axial", "cmp_tgt_img_axial"),
        ("coronal", "cmp_tgt_img_coronal"),
        ("sagittal", "cmp_tgt_img_sagittal"),
    ):
        ui_png = _decode_panel(app.state[img_key])
        direct = mpr.render_slice_png(
            tgt["arr"], tgt["spacing"], plane, expected_tgt_sl[plane],
            window=float(app.state.cmp_window), level=float(app.state.cmp_level), max_dim=384)
        assert ui_png == direct, f"target {plane} panel not byte-identical to the mapped index"
    print(f"[4] reference voxel {(ref_ix, ref_iy, ref_iz)} -> apply_affine -> "
          f"target voxel {tuple(int(v) for v in tgt_ijk)}; target panels re-rendered "
          "byte-identical to a direct render_slice_png at the mapped index")

    # --- 5. Reliable/amber gate matches inlier_fraction >= 0.30. ---------------
    live_reliable = reg["inlier_fraction"] >= 0.30
    assert app.state.cmp_reliable == live_reliable, (
        f"cmp_reliable={app.state.cmp_reliable} but inlier_fraction="
        f"{reg['inlier_fraction']} (>= 0.30 -> {live_reliable})")
    print(f"[5a] live registration: inlier_fraction={reg['inlier_fraction']:.3f} -> "
          f"reliable={app.state.cmp_reliable} (gate: >= 0.30)")

    # Force a low-inlier stub through the same sync path to exercise the amber
    # branch explicitly (without needing a pathological dataset).
    stub_reg = dict(reg)
    stub_reg["inlier_fraction"] = 0.10
    app._compare_sync_from_ref_voxel(probe_ijk, reg=stub_reg)
    assert app.state.cmp_reliable is False, "forced low-inlier stub did not flip the amber gate"
    assert "unreliable" in app.state.cmp_reg_note, "amber note text missing 'unreliable'"
    # The target panel is STILL rendered (never hidden), just flagged.
    assert app.state.cmp_tgt_img_axial, "target panel was hidden when unreliable (must not be)"
    print("[5b] forced low-inlier stub (0.10 < 0.30) -> amber gate fires, "
          "target slice still rendered (not hidden), note flags it as unreliable")

    # Restore the real registration so subsequent checks reflect actual state.
    app._compare_sync_from_ref_voxel(probe_ijk, reg=reg)

    # --- 6. A 3D left-click (compare mode active) drives the linked crosshair. -
    click_ijk = (5, 10, 15)
    click_world = mpr.voxel_to_world(click_ijk, ref["spacing"], ref["offset_xyz"])
    app._on_pick_to_mpr(click_world)  # the real plotter callback, compare-mode branch
    assert (app.state.cmp_ix, app.state.cmp_iy, app.state.cmp_iz) == click_ijk, (
        "3D click in compare mode did not move the linked reference crosshair")
    print(f"[6] 3D click at voxel {click_ijk} (compare mode) -> reference crosshair moved "
          "via _on_pick_to_mpr -> _on_pick_to_compare")

    # --- 7. Phase V: GLB export (direct core call + the app's control). -------
    # Compare mode never populates _LAST_MESH (it registers via analyze_thickness
    # internally but doesn't hand the result to the 3D scene); run a real Mode A
    # compute first so a currently-displayed surface exists to export, exactly as
    # a user would see it before clicking "Download GLB for AR".
    app.state.compare_active = False
    app.state.mode = "A"
    app.state.side = "left"
    req_id = app._next_request_id()
    app._compute_worker(req_id)
    assert app._LAST_MESH["thickness"] is not None, "no computed thickness mesh to export"
    direct_glb = ROOT / "outputs" / "qa_trame_compare_direct.glb"
    from core.export.mesh import export_mesh
    export_mesh(app._LAST_MESH["thickness"], direct_glb, fmt="glb",
                scalar_name="thickness_mm", cmap_name="green_yellow_red",
                clim=(0.0, 4.0))
    raw = direct_glb.read_bytes()
    assert raw[:4] == _GLB_MAGIC, f"direct export_mesh(...,fmt='glb') bad magic: {raw[:4]!r}"
    print(f"[7a] direct export_mesh(fmt='glb') -> {direct_glb} "
          f"({len(raw):,} bytes, magic={raw[:4]!r})")

    app.do_export_ar_glb()
    _wait_for(lambda: not app.state.ar_glb_busy)
    assert not app.state.ar_glb_msg.startswith("GLB export failed"), app.state.ar_glb_msg
    assert app.state.ar_glb_url.startswith("/downloads/ar/"), (
        f"unexpected ar_glb_url: {app.state.ar_glb_url!r}")
    ui_glb_path = Path(app.state.ar_glb_path)
    assert ui_glb_path.exists(), f"UI GLB path missing on disk: {ui_glb_path}"
    ui_raw = ui_glb_path.read_bytes()
    assert ui_raw[:4] == _GLB_MAGIC, f"UI-exported GLB bad magic: {ui_raw[:4]!r}"
    print(f"[7b] app.do_export_ar_glb() -> {app.state.ar_glb_url} "
          f"(served from /downloads, on-disk {ui_glb_path}, "
          f"{len(ui_raw):,} bytes, magic={ui_raw[:4]!r})")

    print("\nQA PASS: trame compare mode registers reference<->target ONCE and reuses "
          "the cached 4x4 while the crosshair moves; reference/target panels are "
          "byte-identical to core.viz.slice.render_slice_png at the apply_affine-mapped "
          "voxel; the reliable/amber gate matches inlier_fraction >= 0.30 exactly (and "
          "never hides the target slice when unreliable); a 3D click drives the linked "
          "crosshair; and export_mesh(fmt='glb') / the app's AR-export control both write "
          "a valid GLB (b'glTF' magic) served from /downloads.\n"
          "\n"
          "Scope note: all of the above runs the real app_trame.app callbacks/state "
          "against the real demo dataset and core.pipeline/core.viz.slice/"
          "core.export.mesh — it is callback/state-level verification. A live "
          "browser session driving the actual trame server (clicking the rendered "
          "3D view, dragging sliders in a browser) is out of scope for this script.")


if __name__ == "__main__":
    main()
