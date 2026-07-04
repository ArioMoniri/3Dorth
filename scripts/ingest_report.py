#!/usr/bin/env python3
"""Phase 0 gate: ingest both sample archives and print a de-identified findings
table (geometry, laterality, hardware, distinct-scan). Writes
outputs/phase0_ingest.json.

Usage:
    .venv/bin/python scripts/ingest_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ingest import compare_scans, ingest_source  # noqa: E402

DATA = ROOT / "Bilateral Omuz BT Jul 4 2026"
WORKDIR = ROOT / "data" / "raw"
OUT = ROOT / "outputs"


def fmt_series(s: dict) -> str:
    ps = s.get("pixel_spacing")
    ps_str = f"{ps[0]:.3g}x{ps[1]:.3g}" if ps else "?"
    return (
        f"    - {s['modality'] or '?':3} | inst={s['n_instances']:4d} | "
        f"{(s['rows'] or 0)}x{(s['cols'] or 0)} | px={ps_str}mm | "
        f"thk={s['slice_thickness']}mm | iso={s['is_isotropic']} | "
        f"lat={s['laterality']} | body={s['body_part'] or '-'} | "
        f"desc={s['description'][:32] or '-'}"
    )


def main() -> int:
    OUT.mkdir(exist_ok=True)
    zips = sorted(DATA.glob("*.zip"))
    if not zips:
        print(f"No zips found in {DATA}")
        return 1

    reports = []
    print("\n" + "=" * 78)
    print("  PHASE 0 — INGEST FINDINGS (de-identified)")
    print("=" * 78)
    for z in zips:
        print(f"\n[SOURCE] {z.name}  ({z.stat().st_size/1e6:.0f} MB)")
        rep = ingest_source(z, WORKDIR, load_pixels=True)
        reports.append(rep)
        pub = rep.public_dict()
        print(f"  patient_hash={pub['patient_hash']}  source_hash={pub['source_hash']}")
        print(f"  dicom_root_found={pub['dicom_root_found']}  "
              f"n_dicom_files={pub['n_dicom_files']}  n_series={pub['n_series']}")
        print(f"  laterality={pub['laterality']}  "
              f"HU=[{pub['hu_min']}, {pub['hu_max']}]  "
              f"metal_present={pub['metal_present']} (frac={pub['metal_fraction']})")
        print("  series:")
        for s in pub["series"][:8]:
            print(fmt_series(s))
        if len(pub["series"]) > 8:
            print(f"    ... (+{len(pub['series'])-8} more series)")
        prim = rep.primary_series()
        if prim:
            print(f"  -> PRIMARY: {prim.modality} series, {prim.n_instances} slices, "
                  f"{prim.rows}x{prim.cols}, isotropic={prim.is_isotropic}")

    result = None
    if len(reports) >= 2:
        result = compare_scans(reports[0], reports[1])
        print("\n" + "-" * 78)
        print("  DISTINCT-SCAN CHECK")
        print("-" * 78)
        print(f"  distinct={result.distinct}  same_patient={result.same_patient}")
        print(f"  reason: {result.reason}")

    doc = {
        "phase": 0,
        "sources": [r.public_dict() for r in reports],
        "distinct_scan": result.model_dump() if result else None,
    }
    (OUT / "phase0_ingest.json").write_text(json.dumps(doc, indent=2))
    print(f"\n  wrote {OUT/'phase0_ingest.json'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
