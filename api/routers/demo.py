"""Demo-bundle endpoints: serve the precomputed manifest for the sample scan.

The heavy analysis (segmentation, thickness) is produced offline by
``scripts/build_demo_bundle.py`` into ``outputs/demo/``; geometry files are
served as static ``.vtp`` under ``/api/geometry``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api")
_DEMO = Path(__file__).resolve().parents[2] / "outputs" / "demo"


@router.get("/demo/manifest")
def manifest() -> dict:
    f = _DEMO / "manifest.json"
    if not f.exists():
        raise HTTPException(404, "demo bundle not built (run scripts/build_demo_bundle.py)")
    return json.loads(f.read_text())
