"""Interactive session + compute-on-demand endpoints.

A session holds a loaded scan (server-side) split into left/right sides. The UIs
POST the current parameters to /analyze (Mode A thickness) or /compare (Mode B
signed deviation) and get back freshly computed geometry — so every parameter in
the side panel actually applies, and each side of a bilateral scan is selectable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import core.parameters as P
from core import pipeline

router = APIRouter(prefix="/api")

ROOT = Path(__file__).resolve().parents[2]
WORKDIR = ROOT / "data" / "raw"
CACHE = ROOT / "outputs" / "sessions"
CACHE.mkdir(parents=True, exist_ok=True)
_DEMO = next((ROOT / "Bilateral Omuz BT Jul 4 2026").glob("*.zip"), None) if \
    (ROOT / "Bilateral Omuz BT Jul 4 2026").exists() else None

# In-memory sessions: sid -> {arr, spacing, meta, sides}
SESSIONS: dict[str, dict] = {}


class LoadReq(BaseModel):
    source: str = "demo"


class AnalyzeReq(BaseModel):
    side: str = "left"
    region_label: int | None = None
    params: dict = {}


class CompareReq(BaseModel):
    reference_side: str = "left"
    target_side: str = "right"
    params: dict = {}


def _params(d: dict) -> "P.Parameters":
    valid = {k: v for k, v in (d or {}).items() if k in P.registry_keys()}
    try:
        return P.Parameters(**valid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"invalid parameters: {e}")


def _new_session(arr, spacing, meta) -> dict:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"arr": arr, "spacing": spacing, "meta": meta,
                     "sides": pipeline.split_sides(arr, spacing)}
    return {"session_id": sid, "meta": meta, "sides": list(SESSIONS[sid]["sides"].keys()),
            "is_bilateral": True}


@router.post("/session")
def create_session() -> dict:
    """Create a session from the bundled demo scan (no request body needed)."""
    if _DEMO is None:
        raise HTTPException(404, "no demo scan present")
    arr, spacing, meta = pipeline.load_volume_from_source(_DEMO, WORKDIR)
    return _new_session(arr, spacing, meta)


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "upload.zip").name
    if not name.lower().endswith((".zip",)):
        raise HTTPException(400, "upload a .zip containing a DICOM series")
    dest = WORKDIR / f"upload_{uuid.uuid4().hex[:8]}_{name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    try:
        arr, spacing, meta = pipeline.load_volume_from_source(dest, WORKDIR)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not ingest upload: {e}")
    return _new_session(arr, spacing, meta)


def _save_mesh(mesh, key: str) -> str:
    fn = f"{key}.vtp"
    mesh.save(str(CACHE / fn))
    return f"/api/session-geometry/{fn}"


@router.post("/session/{sid}/analyze")
def analyze(sid: str, req: AnalyzeReq) -> dict:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found (create one via POST /api/session)")
    side = s["sides"].get(req.side)
    if not side:
        raise HTTPException(400, f"unknown side '{req.side}'")
    params = _params(req.params)
    try:
        res = pipeline.analyze_thickness(side["arr"], side["spacing"], params,
                                         region_label=req.region_label,
                                         offset_xyz=side["offset_xyz"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    key = hashlib.sha256(
        f"{sid}|{req.side}|{req.region_label}|{json.dumps(req.params, sort_keys=True)}".encode()
    ).hexdigest()[:16]
    return {
        "geometry_url": _save_mesh(res["mesh"], key),
        "scalar": "thickness_mm",
        "scalar_range": [params.mode_a_range_min, params.mode_a_range_max],
        "colormap": params.mode_a_colormap,
        "steps": params.mode_a_colorbar_steps,
        "region_label": res["region_label"],
        "regions": res["regions"],
        "stats": res["stats"],
        "metal_fraction": res["metal_fraction"],
    }


@router.post("/session/{sid}/compare")
def compare(sid: str, req: CompareReq) -> dict:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    ref = s["sides"].get(req.reference_side)
    tgt = s["sides"].get(req.target_side)
    if not ref or not tgt:
        raise HTTPException(400, "unknown side(s)")
    params = _params(req.params)
    try:
        res = pipeline.compare_sides(ref, tgt, params)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"comparison failed: {e}")
    key = hashlib.sha256(
        f"{sid}|cmp|{req.reference_side}|{req.target_side}|{json.dumps(req.params, sort_keys=True)}".encode()
    ).hexdigest()[:16]
    return {
        "geometry_url": _save_mesh(res["mesh"], key),
        "scalar": res["scalar"],
        "scalar_range": [params.mode_b_center - params.mode_b_range_abs,
                         params.mode_b_center + params.mode_b_range_abs],
        "colormap": params.mode_b_colormap,
        "steps": params.mode_b_colorbar_steps,
        "stats": res["stats"],
        "registration": res["registration"],
    }
