"""QA: verify the reworked trame scene builders render a computed mesh offscreen.

Computes a Mode A thickness surface (and, if --deviation, a Mode B deviation
surface) from the demo bilateral scan, renders via app_trame.scene builders, and
saves a screenshot to outputs/qa_trame_rework.png.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

import core.parameters as P  # noqa: E402
from app_trame.scene import build_deviation_scene, build_thickness_scene  # noqa: E402
from core import pipeline  # noqa: E402

pv.OFF_SCREEN = True

WORKDIR = ROOT / "data" / "raw"
OUT = ROOT / "outputs" / "qa_trame_rework.png"
OUT.parent.mkdir(parents=True, exist_ok=True)
DEMO_ZIP = next((ROOT / "Bilateral Omuz BT Jul 4 2026").glob("*.zip"))


def main(do_deviation: bool = False) -> None:
    arr, spacing, meta = pipeline.load_volume_from_source(DEMO_ZIP, WORKDIR)
    sides = pipeline.split_sides(arr, spacing)
    params = P.Parameters()

    left = sides["left"]
    res = pipeline.analyze_thickness(left["arr"], left["spacing"], params,
                                     offset_xyz=left["offset_xyz"])
    assert "thickness_mm" in res["mesh"].array_names
    plotter = pv.Plotter(off_screen=True, window_size=(1100, 800))
    build_thickness_scene(plotter, res["mesh"], params=params, side_label="Left")
    plotter.screenshot(str(OUT))
    print(f"Mode A thickness scene rendered -> {OUT} "
          f"(npoints={res['mesh'].n_points}, mean={res['stats']['mean']} mm)")

    if do_deviation:
        cres = pipeline.compare_sides(sides["left"], sides["right"],
                                      P.Parameters(mirror_sagittal=True))
        assert "deviation_mm" in cres["mesh"].array_names
        p2 = pv.Plotter(off_screen=True, window_size=(1100, 800))
        build_deviation_scene(p2, cres["mesh"], params=P.Parameters())
        dev_out = ROOT / "outputs" / "qa_trame_rework_deviation.png"
        p2.screenshot(str(dev_out))
        print(f"Mode B deviation scene rendered -> {dev_out} "
              f"(rms={cres['registration']['rms']:.3f} mm)")


if __name__ == "__main__":
    main(do_deviation="--deviation" in sys.argv)
