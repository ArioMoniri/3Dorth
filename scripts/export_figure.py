#!/usr/bin/env python3
"""Export a publication-quality Fig-2 figure (crisp discrete colorbar, no text
overlap) from the demo thickness mesh.

Usage:
    .venv/bin/python scripts/export_figure.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

import core.parameters as P  # noqa: E402
from core.viz import render_thickness_figure  # noqa: E402

DEMO = ROOT / "outputs" / "demo"
OUT = ROOT / "outputs"


def main() -> int:
    mesh_path = DEMO / "thickness.vtp"
    if not mesh_path.exists():
        print("Run scripts/build_demo_bundle.py first.")
        return 1
    mesh = pv.read(str(mesh_path))
    out = render_thickness_figure(
        mesh, "thickness_mm", P.default_parameters(),
        OUT / "figure_thickness.png", view="xz", dpi=300,
    )
    print(f"wrote {out} (300 DPI)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
