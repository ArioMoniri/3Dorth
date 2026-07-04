"""QA: the trame MPR (multiplanar reformat) viewer, headless.

Asserts the shipped trame app's MPR path is correct and byte-identical to the
FastAPI ``/slice`` endpoint (both call ``core.viz.slice`` — the single source of
truth), so the two frontends never drift:

  1. Load the demo scan and point the MPR viewer at the LEFT side.
  2. ``render_slice_png`` returns a VALID PNG for each plane (axial/coronal/
     sagittal), and the UI's rendered panel is byte-identical to a direct
     ``core.viz.slice.render_slice_png`` call (parity guarantee).
  3. Crosshair math round-trips: ``world_to_voxel(voxel_to_world(ijk)) == ijk``
     across a spread of voxels (including the extreme corners).
  4. Clicking the 3D surface (``_on_pick_to_mpr`` with a world point) drives the
     crosshair via ``world_to_voxel`` + ``slices_from_voxel`` and re-renders the
     three panels — matching the API's pick-to-slices contract.
  5. Moving a plane slider mirrors into the crosshair voxel and re-renders.

Drives the real ``app_trame.app`` module (its state, reset, render and pick
callbacks), not a reimplementation, so it validates the shipped path. Runs fully
offscreen and does NOT launch the long-running trame server.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402
import core.viz.slice as mpr  # noqa: E402

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _decode_panel(img_key: str) -> bytes:
    """Return the PNG bytes behind an ``mpr_img_*`` data URI (asserts validity)."""
    uri = app.state[img_key]
    assert uri.startswith("data:image/png;base64,"), f"{img_key}: not a PNG data URI"
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == _PNG_MAGIC, f"{img_key}: not a valid PNG"
    assert len(raw) > 0, f"{img_key}: empty PNG"
    return raw


def main() -> None:
    # --- 1. Load the demo and point the MPR viewer at the LEFT side. ----------
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run MPR QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    app.state.side = "left"
    app._mpr_reset_for_side()

    assert app.state.mpr_available, "MPR viewer not available for the demo left side"
    assert app.state.mpr_side == "left", f"MPR side is {app.state.mpr_side!r}, want 'left'"
    side = app._mpr_active_side()
    assert side is not None and side.get("arr") is not None, "no volume side for MPR"
    print(f"[1] demo left side loaded  "
          f"(n_slices axial/coronal/sagittal = {app.state.mpr_n_axial}/"
          f"{app.state.mpr_n_coronal}/{app.state.mpr_n_sagittal})")

    # --- 2. Valid PNG per plane AND byte-identical to render_slice_png. -------
    panels = {
        "axial": ("mpr_img_axial", "mpr_idx_axial"),
        "coronal": ("mpr_img_coronal", "mpr_idx_coronal"),
        "sagittal": ("mpr_img_sagittal", "mpr_idx_sagittal"),
    }
    for plane, (img_key, idx_key) in panels.items():
        ui_png = _decode_panel(img_key)
        direct = mpr.render_slice_png(
            side["arr"], side["spacing"], plane, int(app.state[idx_key]),
            window=float(app.state.mpr_window), level=float(app.state.mpr_level),
            max_dim=384,
        )
        assert ui_png == direct, f"{plane}: UI panel not byte-identical to render_slice_png"
        print(f"[2] {plane:8s} PNG valid + byte-identical to core.viz.slice  "
              f"({len(ui_png):,} bytes)")

    # --- 3. Crosshair math round-trips. --------------------------------------
    sp, off = side["spacing"], side["offset_xyz"]
    nz, ny, nx = side["arr"].shape
    probes = [
        (0, 0, 0), (nx // 2, ny // 2, nz // 2),
        (nx - 1, ny - 1, nz - 1), (7, 13, 29), (nx - 3, 2, nz - 5),
    ]
    for ijk in probes:
        world = mpr.voxel_to_world(ijk, sp, off)
        back = mpr.world_to_voxel(world, sp, off)
        assert tuple(back) == tuple(ijk), f"round-trip failed: {ijk} -> {world} -> {back}"
    print(f"[3] world_to_voxel round-trip OK for {len(probes)} voxels "
          "(incl. both extreme corners)")

    # --- 4. 3D pick -> crosshair via world_to_voxel + slices_from_voxel. ------
    target = (15, 25, 35)
    world = mpr.voxel_to_world(target, sp, off)
    before = (app.state.mpr_ix, app.state.mpr_iy, app.state.mpr_iz)
    app._on_pick_to_mpr(world)  # the real left-click callback
    after = (app.state.mpr_ix, app.state.mpr_iy, app.state.mpr_iz)
    assert after == target, f"pick crosshair {after}, want {target}"
    assert after != before or before == target, "pick did not move the crosshair"
    # Per-plane indices follow slices_from_voxel exactly.
    expected = mpr.slices_from_voxel(target, side["arr"].shape)
    assert app.state.mpr_idx_axial == expected["axial"]
    assert app.state.mpr_idx_coronal == expected["coronal"]
    assert app.state.mpr_idx_sagittal == expected["sagittal"]
    # And the panels re-rendered at the picked voxel.
    for plane, (img_key, idx_key) in panels.items():
        ui_png = _decode_panel(img_key)
        direct = mpr.render_slice_png(
            side["arr"], side["spacing"], plane, int(app.state[idx_key]),
            window=float(app.state.mpr_window), level=float(app.state.mpr_level),
            max_dim=384)
        assert ui_png == direct, f"{plane}: panel stale after 3D pick"
    print(f"[4] 3D pick {tuple(map(float, (round(w,1) for w in world)))} mm -> "
          f"voxel {after}; panels re-rendered (matches slices_from_voxel)")

    # --- 5. A plane slider drives the crosshair the other way. ----------------
    new_axial = min(int(app.state.mpr_n_axial) - 1, int(app.state.mpr_idx_axial) + 10)
    app.state.mpr_idx_axial = new_axial
    app._mpr_on_plane_index_change()
    assert app.state.mpr_iz == new_axial, (
        f"axial slider {new_axial} did not set crosshair iz ({app.state.mpr_iz})")
    ui_png = _decode_panel("mpr_img_axial")
    direct = mpr.render_slice_png(side["arr"], side["spacing"], "axial", new_axial,
                                  window=float(app.state.mpr_window),
                                  level=float(app.state.mpr_level), max_dim=384)
    assert ui_png == direct, "axial panel stale after slider move"
    print(f"[5] axial slider -> crosshair iz={app.state.mpr_iz}; panel re-rendered")

    print("\nQA PASS: trame MPR renders valid, API-byte-identical slices for all "
          "three planes; the crosshair round-trips and is driven by both 3D picks "
          "and per-plane sliders.")


if __name__ == "__main__":
    main()
