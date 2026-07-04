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

from collections import OrderedDict

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

import core.parameters as P
import core.resources as R
import core.viz.slice as mpr
from core import pipeline
from core.export import export_bundle

router = APIRouter(prefix="/api")

ROOT = Path(__file__).resolve().parents[2]
WORKDIR = ROOT / "data" / "raw"
CACHE = ROOT / "outputs" / "sessions"
CACHE.mkdir(parents=True, exist_ok=True)
EXPORTS = ROOT / "outputs" / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)
# Prefer the shipped, DE-IDENTIFIED demo (NIfTI carries no patient tags) so every
# user — including on a public server — gets a demo with no patient information.
# Fall back to the local raw patient archive only if the de-identified demo is
# absent (developer machine before running scripts/make_demo.py).
_DEIDENTIFIED_DEMO = ROOT / "data" / "demo" / "shoulder_demo.nii.gz"
_PATIENT_DEMO = next((ROOT / "Bilateral Omuz BT Jul 4 2026").glob("*.zip"), None) if \
    (ROOT / "Bilateral Omuz BT Jul 4 2026").exists() else None
_DEMO = _DEIDENTIFIED_DEMO if _DEIDENTIFIED_DEMO.exists() else _PATIENT_DEMO

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
    manual_transform: list[list[float]] | None = None


class ExportReq(BaseModel):
    mode: str = "A"  # 'A' thickness | 'B' deviation
    side: str | None = None
    reference_side: str | None = None
    target_side: str | None = None
    region_label: int | None = None
    params: dict = {}
    formats: list[str] = ["png", "tiff", "stl", "vtp"]
    dpi: int = 300
    camera: dict | None = None
    manual_transform: list[list[float]] | None = None


def _params(d: dict) -> "P.Parameters":
    valid = {k: v for k, v in (d or {}).items() if k in P.registry_keys()}
    try:
        return P.Parameters(**valid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"invalid parameters: {e}")


def _evict_old_sessions() -> None:
    """Keep at most R.MAX_SESSIONS scans in memory; drop the oldest (bounds RAM)."""
    while len(SESSIONS) >= R.MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)), None)


def _new_session(arr, spacing, meta, layout: str = "auto") -> dict:
    _evict_old_sessions()
    sid = uuid.uuid4().hex[:12]
    sides = pipeline.split_sides(arr, spacing, layout=layout)
    SESSIONS[sid] = {"arr": arr, "spacing": spacing, "meta": meta, "sides": sides}
    return {"session_id": sid, "meta": meta, "sides": list(sides.keys()),
            "is_bilateral": set(sides.keys()) == {"left", "right"}}


def _new_mesh_session(mesh, meta) -> dict:
    """Create a session holding a single surface mesh (no volume analysis)."""
    _evict_old_sessions()
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"arr": None, "spacing": None, "meta": meta,
                     "sides": {"mesh": {"mesh": mesh, "side": "mesh",
                                        "offset_xyz": (0.0, 0.0, 0.0)}}}
    return {"session_id": sid, "meta": meta, "sides": ["mesh"],
            "is_bilateral": False, "is_mesh": True}


@router.post("/session")
def create_session(layout: str = "bilateral") -> dict:
    """Create a session from the bundled de-identified demo scan.

    The demo is a bilateral shoulder CT, so ``layout='bilateral'`` by default
    (the thoracic skeleton fills the midline and defeats auto gap-detection);
    pass ``?layout=auto`` or ``?layout=single`` to override.
    """
    if _DEMO is None:
        raise HTTPException(404, "no demo scan present")
    arr, spacing, meta = pipeline.load_volume_from_source(_DEMO, WORKDIR)
    return _new_session(arr, spacing, meta, layout=layout)


def _accepted_suffix(name: str) -> str | None:
    """Return the recognised SUPPORTED_UPLOAD_EXTENSIONS suffix, or None."""
    low = name.lower()
    # check the two-part .nii.gz before single suffixes
    for ext in sorted(pipeline.SUPPORTED_UPLOAD_EXTENSIONS, key=len, reverse=True):
        if low.endswith(ext):
            return ext
    return None


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "upload.zip").name
    ext = _accepted_suffix(name)
    if ext is None:
        raise HTTPException(
            400,
            "unsupported upload; accepted: "
            + ", ".join(pipeline.SUPPORTED_UPLOAD_EXTENSIONS),
        )
    dest = WORKDIR / f"upload_{uuid.uuid4().hex[:8]}_{name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())

    from core.ingest import is_mesh

    if is_mesh(dest):
        try:
            mesh = pipeline.load_mesh_source(dest)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"could not load mesh upload: {e}")
        meta = {"format": ext.lstrip("."), "kind": "mesh", "n_points": int(mesh.n_points)}
        return _new_mesh_session(mesh, meta)

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
        with R.COMPUTE_SEMAPHORE:  # bound concurrent heavy computes (peak RAM)
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


@router.get("/session/{sid}/region-thumbnails")
def region_thumbnails(sid: str, side: str) -> dict:
    """Small per-bone-region renders for the region dropdown (visual selection)."""
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    sd = s["sides"].get(side)
    if not sd:
        raise HTTPException(400, f"unknown side '{side}'")
    arr = sd.get("arr")
    if arr is None:  # bare-mesh side has no volume regions
        return {"thumbnails": []}
    with R.COMPUTE_SEMAPHORE:
        thumbs = pipeline.region_thumbnails(arr, sd["spacing"], P.default_parameters(),
                                            EXPORTS, f"{sid}_{side}")
    return {"thumbnails": thumbs}


# --------------------------------------------------------------------------- #
# MPR image viewer — slice-on-demand (see docs/IMAGING_DESIGN.md). Light work,
# outside COMPUTE_SEMAPHORE, with a small PNG LRU so scrubbing feels instant.
# --------------------------------------------------------------------------- #
_SLICE_LRU: "OrderedDict[tuple, bytes]" = OrderedDict()
_SLICE_LRU_MAX = 128


def _volume_side(sid: str, side: str):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    sd = s["sides"].get(side) if side else next(iter(s["sides"].values()), None)
    if not sd:
        raise HTTPException(400, f"unknown side '{side}'")
    if sd.get("arr") is None:
        raise HTTPException(400, "this side has no volume (mesh session)")
    return sd


class PickReq(BaseModel):
    side: str | None = None
    world_xyz_mm: list[float]


@router.get("/session/{sid}/volume-info")
def volume_info(sid: str, side: str = "") -> dict:
    sd = _volume_side(sid, side)
    return mpr.volume_info(sd["arr"], sd["spacing"], sd["offset_xyz"], sd["side"])


@router.get("/session/{sid}/slice")
def slice_png(sid: str, plane: str, index: int, side: str = "",
              window: float = mpr.BONE_WINDOW, level: float = mpr.BONE_LEVEL,
              max_dim: int = Query(512, ge=32, le=1024)) -> Response:
    if plane not in mpr.PLANES:
        raise HTTPException(422, f"plane must be one of {mpr.PLANES}")
    sd = _volume_side(sid, side)
    key = (sid, sd["side"], plane, int(index), float(window), float(level), int(max_dim))
    png = _SLICE_LRU.get(key)
    if png is None:
        png = mpr.render_slice_png(sd["arr"], sd["spacing"], plane, index,
                                   window=window, level=level, max_dim=max_dim)
        _SLICE_LRU[key] = png
        while len(_SLICE_LRU) > _SLICE_LRU_MAX:
            _SLICE_LRU.popitem(last=False)
    _SLICE_LRU.move_to_end(key)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post("/session/{sid}/pick-to-slices")
def pick_to_slices(sid: str, req: PickReq) -> dict:
    sd = _volume_side(sid, req.side or "")
    arr = sd["arr"]
    ijk = mpr.world_to_voxel(req.world_xyz_mm, sd["spacing"], sd["offset_xyz"])
    nz, ny, nx = arr.shape
    in_bounds = 0 <= ijk[0] < nx and 0 <= ijk[1] < ny and 0 <= ijk[2] < nz
    return {"voxel_ijk": list(ijk), "in_bounds": bool(in_bounds),
            "slices": mpr.slices_from_voxel(ijk, arr.shape),
            "world_xyz_mm": req.world_xyz_mm}


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
        with R.COMPUTE_SEMAPHORE:  # bound concurrent heavy computes (peak RAM)
            res = pipeline.compare_sides(ref, tgt, params,
                                         manual_transform=req.manual_transform)
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"comparison failed: {e}") from e
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


def _compute_for_export(s: dict, req: "ExportReq", params) -> tuple:
    """Run the requested compute and return (mesh, scalar_name, diverging)."""
    if req.mode.upper() == "B":
        ref_name = req.reference_side or "left"
        tgt_name = req.target_side or "right"
        ref = s["sides"].get(ref_name)
        tgt = s["sides"].get(tgt_name)
        if not ref or not tgt:
            raise HTTPException(400, "unknown side(s) for Mode B export")
        res = pipeline.compare_sides(ref, tgt, params,
                                     manual_transform=req.manual_transform)
        return res["mesh"], res["scalar"], True

    # Mode A (default): thickness on a single side.
    side_name = req.side or next(iter(s["sides"]))
    side = s["sides"].get(side_name)
    if not side:
        raise HTTPException(400, f"unknown side '{side_name}'")
    if "arr" not in side or side.get("arr") is None:
        raise HTTPException(400, "Mode A export needs a volume side, not a bare mesh")
    res = pipeline.analyze_thickness(side["arr"], side["spacing"], params,
                                     region_label=req.region_label,
                                     offset_xyz=side["offset_xyz"])
    return res["mesh"], "thickness_mm", False


@router.post("/session/{sid}/export")
def export(sid: str, req: ExportReq) -> dict:
    """Compute (Mode A thickness or Mode B deviation) then export a multi-format bundle.

    Returns ``{"files": {fmt: url}}`` where each url is served from the
    ``/api/exports`` static mount. Supported formats: png, tiff, jpg, stl, ply,
    obj, vtp, dicom.
    """
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found (create one via POST /api/session)")
    if req.mode.upper() not in ("A", "B"):
        raise HTTPException(422, "mode must be 'A' or 'B'")
    if not req.formats:
        raise HTTPException(422, "at least one export format is required")
    if req.dpi <= 0:
        raise HTTPException(422, "dpi must be positive")

    params = _params(req.params)
    try:
        mesh, scalar, diverging = _compute_for_export(s, req, params)
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"export compute failed: {e}") from e

    key = hashlib.sha256(
        f"{sid}|exp|{req.mode}|{json.dumps(req.model_dump(), sort_keys=True, default=str)}".encode()
    ).hexdigest()[:16]
    out_dir = EXPORTS / key
    try:
        files = export_bundle(mesh, scalar, params, out_dir,
                              formats=tuple(f.lower() for f in req.formats),
                              dpi=req.dpi, camera=req.camera, diverging=diverging,
                              stem="export")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    urls = {fmt: f"/api/exports/{key}/{Path(p).name}" for fmt, p in files.items()}
    return {"files": urls, "mode": req.mode.upper(), "scalar": scalar}
