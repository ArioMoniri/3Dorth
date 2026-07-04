#!/usr/bin/env python3
"""Phase 4 demo: descriptive cortical-thickness statistics on the real humerus.

Single subject -> descriptive only (no group inference; is_inferential_valid
guards against over-claiming). Partitions the surface into axial zones, emits a
Table-1-style CSV + results.json, and Fig-4/Fig-5-style plots.

Usage:
    .venv/bin/python scripts/stats_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.stats as S  # noqa: E402

OUT = ROOT / "outputs"


def main() -> int:
    mesh_path = OUT / "demo" / "thickness.vtp"
    if not mesh_path.exists():
        print("Run scripts/build_demo_bundle.py first.")
        return 1
    mesh = pv.read(str(mesh_path))
    th = np.asarray(mesh["thickness_mm"], dtype=float)
    z = np.asarray(mesh.points)[:, 2]

    # Four axial zones (quartiles of z along the bone), proximal->distal.
    q = np.quantile(z, [0.25, 0.5, 0.75])
    idx = np.digitize(z, q)
    groups = {f"zone {i + 1}": th[idx == i] for i in range(4)}

    summ, df = S.group_summary(groups)
    df.to_csv(OUT / "stats_thickness_by_zone.csv", index=False)

    S.fig4_boxplots(groups, OUT / "fig4_thickness_boxplots.png",
                    ylabel="Cortical thickness (mm)",
                    title="Cortical thickness by axial zone (single subject, descriptive)")
    fit = S.linear_regression(z, th)
    S.fig5_regression_scatter(z, th, fit, OUT / "fig5_thickness_vs_height.png",
                              xlabel="Axial position z (mm)", ylabel="Thickness (mm)",
                              title="Thickness vs axial position")

    inferential_ok = S.is_inferential_valid(min(len(v) for v in groups.values()))
    results = {
        "subject": "single (demo scan)",
        "inference_allowed": bool(inferential_ok),
        "note": "Single-subject descriptive statistics only; no group inference "
                "(vertex counts are not independent samples).",
        "zones": {k: v.model_dump() for k, v in summ.items()},
        "thickness_vs_z_regression": {k: (round(v, 5) if isinstance(v, float) else v)
                                      for k, v in fit.items()},
    }
    (OUT / "stats_results.json").write_text(json.dumps(results, indent=2, default=str))

    print("Cortical thickness by axial zone (mm):")
    for k, v in summ.items():
        print(f"  {k}: mean {v.mean:.2f}  median {v.median:.2f}  "
              f"SD {v.sd:.2f}  95%CI [{v.ci95_low:.2f}, {v.ci95_high:.2f}]  n={v.n}")
    print(f"\n  wrote stats_thickness_by_zone.csv, stats_results.json, "
          f"fig4_thickness_boxplots.png, fig5_thickness_vs_height.png")
    print("  (single subject -> descriptive only; no ANOVA/inference claimed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
