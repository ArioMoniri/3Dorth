"""QA: trame "Statistics & Figures" section (parity with the API's
POST /session/{sid}/figures + /export-figures, at the core.stats.figures level).

Drives the REAL ``app_trame.app`` module (its state and callbacks), not a
reimplementation, so it validates the shipped path. Runs fully offscreen and
does NOT launch the long-running trame server.

Checks:
  1. After a Mode A compute, ``refresh_stats_figures`` populates
     ``state.stats_figures`` with valid PNG data URIs (histogram, and
     by_region when >= 2 bone regions were segmented) plus a
     single-subject/descriptive ``stats_figures_note``.
  2. The panel's histogram data-URI matches a DIRECT call to
     ``core.stats.figures.render_result_figures`` on the SAME mesh's own
     scalar array (byte-identical) — proves the panel doesn't fabricate or
     diverge from the shared core module.
  3. ``do_export_figures`` (PNG + TIFF, two different DPIs) writes real files
     under outputs/exports/figures/<key>/ that are valid PNG/TIFF and whose
     byte length CHANGES with DPI (raster export honesty check, mirroring the
     3D export's own DPI check).
  4. Mode B (deviation): "by_region" is correctly omitted (no per-region
     breakdown for a single registered surface) and the note explains why.
  5. python -c "import app_trame.app" stays clean (checked by the caller /
     the shell command in the task, re-verified here for convenience).

Honesty note printed at the end: everything here is callback/state-level (the
real ``core.pipeline`` + ``app_trame.app`` functions run against the real demo
data) — a live browser session is out of scope for this script.
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
from core.stats.figures import render_result_figures  # noqa: E402

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TIFF_MAGIC_LE = b"II*\x00"
_TIFF_MAGIC_BE = b"MM\x00*"


def _load_demo_bilateral() -> None:
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run figures QA.")
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()


def _decode(data_uri: str) -> bytes:
    assert data_uri.startswith("data:image/png;base64,"), f"not a PNG data URI: {data_uri[:40]!r}"
    return base64.b64decode(data_uri.split(",", 1)[1])


def main() -> None:
    _load_demo_bilateral()
    print(f"[0] demo loaded; sides = {app._side_names()}")

    # ======================================================================= #
    # 1. MODE A compute -> stats_figures populated
    # ======================================================================= #
    with app.state:
        app.state.mode = "A"
        app.state.side = "left"
    app._compute_worker(app._next_request_id())

    mesh_a = app._LAST_MESH["thickness"]
    assert mesh_a is not None, "Mode A compute did not populate _LAST_MESH['thickness']"
    regions = app._LAST_REGIONS
    assert regions, "Mode A compute did not populate _LAST_REGIONS"
    print(f"[1] Mode A computed: {mesh_a.n_points:,} vertices, {len(regions)} region(s)")

    figs = app.state.stats_figures
    assert "histogram" in figs, f"stats_figures missing 'histogram': {list(figs)}"
    hist_png = _decode(figs["histogram"])
    assert hist_png[:8] == _PNG_MAGIC, "histogram is not a valid PNG"
    note = app.state.stats_figures_note
    assert "single-subject" in note.lower() or "descriptive" in note.lower(), (
        f"stats_figures_note does not state the single-subject/descriptive scope: {note!r}")
    print(f"[2] state.stats_figures has a valid histogram PNG "
          f"({len(hist_png):,} bytes); note states single-subject/descriptive scope")

    if len(regions) >= 2:
        assert "by_region" in figs, (
            f">= 2 regions ({len(regions)}) but 'by_region' missing: {list(figs)}")
        by_region_png = _decode(figs["by_region"])
        assert by_region_png[:8] == _PNG_MAGIC, "by_region is not a valid PNG"
        print(f"[3] by_region figure present ({len(regions)} regions, "
              f"{len(by_region_png):,} bytes)")
    else:
        assert "by_region" not in figs, "single region but 'by_region' was fabricated"
        print("[3] single region -> by_region correctly omitted")

    # ======================================================================= #
    # 2. Panel data-URI matches a DIRECT core.stats.figures call on the same
    #    mesh scalar (byte-identical render_result_figures output at dpi=150,
    #    the panel's fixed preview DPI).
    # ======================================================================= #
    values = np.asarray(mesh_a.point_data["thickness_mm"], dtype=np.float64)
    direct = render_result_figures(scalar_values=values, scalar_name="thickness_mm",
                                   regions=regions, dpi=150)
    assert direct["histogram"] == hist_png, (
        "panel histogram PNG bytes differ from a direct core.stats.figures call "
        "on the identical scalar array")
    print(f"[4] panel histogram bytes are IDENTICAL to a direct "
          f"core.stats.figures.render_result_figures call ({len(hist_png):,} bytes)")
    if "by_region" in direct and "by_region" in figs:
        assert direct["by_region"] == by_region_png, (
            "panel by_region PNG bytes differ from a direct core call")
        print("[5] panel by_region bytes also match the direct core call")

    # ======================================================================= #
    # 3. Export figures: PNG + TIFF at two DPIs -> real files, valid magic,
    #    byte length changes with DPI.
    # ======================================================================= #
    with app.state:
        app.state.figures_export_formats = ["png", "tiff"]
        app.state.figures_export_dpi = 150
    app._figures_export_worker()
    assert not app.state.figures_export_msg.startswith("Export failed"), (
        f"export failed: {app.state.figures_export_msg}")
    links_150 = {(l["name"], l["fmt"]): l["url"] for l in app.state.figures_export_links}
    expected_names = set(figs.keys())
    got_names = {name for name, _fmt in links_150}
    assert got_names == expected_names, (
        f"exported figure set {got_names} != panel figure set {expected_names}")
    print(f"[6] export (dpi=150, png+tiff): {len(links_150)} file(s) written: "
          f"{sorted(links_150)}")

    # Resolve the served /downloads/... URL back to a real file under EXPORTS_DIR.
    def _resolve(url: str) -> Path:
        rel = url.split("/downloads/", 1)[1]
        return app.EXPORTS_DIR / rel

    hist_png_path = _resolve(links_150[("histogram", "png")])
    hist_tiff_path = _resolve(links_150[("histogram", "tiff")])
    assert hist_png_path.is_file(), f"missing exported file: {hist_png_path}"
    assert hist_tiff_path.is_file(), f"missing exported file: {hist_tiff_path}"
    png_bytes_150 = hist_png_path.read_bytes()
    tiff_bytes_150 = hist_tiff_path.read_bytes()
    assert png_bytes_150[:8] == _PNG_MAGIC, "exported histogram.png is not a valid PNG"
    assert tiff_bytes_150[:4] in (_TIFF_MAGIC_LE, _TIFF_MAGIC_BE), (
        "exported histogram.tiff is not a valid TIFF")
    print(f"[7] exported histogram.png ({len(png_bytes_150):,} B) and "
          f"histogram.tiff ({len(tiff_bytes_150):,} B) have valid magic bytes")

    with app.state:
        app.state.figures_export_formats = ["png", "tiff"]
        app.state.figures_export_dpi = 600
    app._figures_export_worker()
    links_600 = {(l["name"], l["fmt"]): l["url"] for l in app.state.figures_export_links}
    png_bytes_600 = _resolve(links_600[("histogram", "png")]).read_bytes()
    tiff_bytes_600 = _resolve(links_600[("histogram", "tiff")]).read_bytes()
    assert len(png_bytes_600) != len(png_bytes_150), (
        "PNG byte length did not change between dpi=150 and dpi=600")
    assert len(tiff_bytes_600) != len(tiff_bytes_150), (
        "TIFF byte length did not change between dpi=150 and dpi=600")
    print(f"[8] DPI actually changes output size: PNG {len(png_bytes_150):,} -> "
          f"{len(png_bytes_600):,} B; TIFF {len(tiff_bytes_150):,} -> "
          f"{len(tiff_bytes_600):,} B (150 -> 600 dpi)")

    # ======================================================================= #
    # 4. Mode B (deviation): by_region correctly omitted, note explains why.
    # ======================================================================= #
    with app.state:
        app.state.mode = "B"
        app.state.b_view = "deviation"
        app.state.ref_side = "left"
        app.state.tgt_side = "right"
    app._compute_worker(app._next_request_id())

    mesh_b = app._LAST_MESH["deviation"]
    assert mesh_b is not None, "Mode B compute did not populate _LAST_MESH['deviation']"
    figs_b = app.state.stats_figures
    assert "histogram" in figs_b, "Mode B histogram missing"
    assert "by_region" not in figs_b, "Mode B fabricated a by_region figure"
    note_b = app.state.stats_figures_note.lower()
    assert "by-region" in note_b or "by_region" in note_b, (
        f"Mode B note doesn't explain by_region omission: {app.state.stats_figures_note!r}")
    print("[9] Mode B (deviation): by_region correctly omitted; note explains why")

    print("\nQA PASS: Statistics & Figures panel renders the SAME PNG bytes as a "
          "direct core.stats.figures call on the active mesh's own scalar array; "
          "export writes real PNG/TIFF files whose size changes with DPI; "
          "per-region figures are only shown when >= 2 regions genuinely exist "
          "(Mode A) and are correctly omitted for Mode B's single registered "
          "surface — no fabricated groups, single-subject/descriptive framing "
          "throughout. (callback/state-level; live browser out of scope.)")


if __name__ == "__main__":
    main()
