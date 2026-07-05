"""Interactive session + compute-on-demand endpoints.

A session holds a loaded scan (server-side) split into left/right sides. The UIs
POST the current parameters to /analyze (Mode A thickness) or /compare (Mode B
signed deviation) and get back freshly computed geometry — so every parameter in
the side panel actually applies, and each side of a bilateral scan is selectable.
"""

from __future__ import annotations

import hashlib
import os
import json
import uuid
from pathlib import Path

from collections import OrderedDict

import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

import core.parameters as P
import core.resources as R
import core.viz.slice as mpr
from core import pipeline
from core.export import export_bundle
from core.stats.figures import FIGURE_NAMES as _FIGURE_NAMES
from core.stats.figures import descriptive_stats, render_result_figures

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

# In-memory sessions: sid -> {arr, spacing, meta, sides}. An OrderedDict so we can
# evict the least-recently-USED (not merely oldest-created) — every access touches
# the session, so a scan a user is actively viewing is never the eviction victim.
SESSIONS: "OrderedDict[str, dict]" = OrderedDict()


def _get_session(sid: str) -> dict:
    """Fetch a session and mark it most-recently-used, or 404 if it was evicted."""
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, "session not found or expired — reload to start a "
                                 "fresh session (create one via POST /api/session)")
    SESSIONS.move_to_end(sid)
    return s


class LoadReq(BaseModel):
    source: str = "demo"


class AnalyzeReq(BaseModel):
    side: str = "left"
    region_label: int | None = None
    params: dict = {}
    whole_bone: bool = False  # mesh EVERY bone region (the whole side), not one piece


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
    # Optional Fig-2 measurement annotations overlaid on the raster figure(s):
    #   {"sampling_line": true | {"p0":[x,y,z],"p1":[x,y,z],"n":3},
    #    "height": true | {"axis":"z","lower":..,"upper":..,"band":[lo,hi]}}
    # Either panel is auto-placed at the surgical-neck / lesser-tuberosity base
    # when coordinates are omitted. Sampled thickness values are read off the
    # computed scalar (never fabricated); the annotated figure is descriptive /
    # single-subject. Applies to raster formats (png/tiff/jpg) + the DICOM SC.
    annotate: dict | None = None


class FiguresReq(BaseModel):
    mode: str = "A"  # 'A' thickness | 'B' deviation
    side: str | None = None
    reference_side: str | None = None
    target_side: str | None = None
    region_label: int | None = None
    params: dict = {}
    which: list[str] | None = None   # subset of FIGURE_NAMES (histogram/ecdf/table/by_region); None = all that apply
    manual_transform: list[list[float]] | None = None


class ExportFiguresReq(FiguresReq):
    formats: list[str] = ["png"]
    dpi: int = 300


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


# Cap the vertex count of the mesh SHIPPED TO THE BROWSER so client-side vtk.js stays
# smooth and the download over a tunnel is small. Stats are computed on the FULL mesh
# (before this), so accuracy is unaffected — only the rendered surface is lighter.
# Env-tunable; per-request override via the analyze/compare `render_max_verts` param.
_RENDER_MAX_VERTS = int(os.getenv("THREEDORTH_RENDER_MAX_VERTS", "150000"))


def _save_mesh(mesh, key: str, max_verts: int | None = None) -> str:
    fn = f"{key}.vtp"
    cap = _RENDER_MAX_VERTS if max_verts is None else int(max_verts)
    out = mesh
    try:
        n = int(mesh.n_points)
        if cap > 0 and n > cap:
            frac = 1.0 - (cap / n)
            out = mesh.triangulate().decimate_pro(frac)      # decimate_pro keeps point scalars
    except Exception:  # noqa: BLE001 — never fail the request over decimation
        out = mesh
    out.save(str(CACHE / fn))
    return f"/api/session-geometry/{fn}"


def _stash_ar_mesh(s: dict, mesh, scalar: str, clim, cmap: str) -> None:
    """Remember the most recent computed surface so GET /model.glb can serve it
    for AR without re-running the (heavy) compute. Bumps a version so a stale GLB
    byte-cache is discarded when parameters change."""
    s["ar"] = {"mesh": mesh, "scalar": scalar, "clim": tuple(clim), "cmap": cmap}
    s.pop("ar_glb", None)


@router.post("/session/{sid}/analyze")
def analyze(sid: str, req: AnalyzeReq) -> dict:
    s = _get_session(sid)
    side = s["sides"].get(req.side)
    if not side:
        raise HTTPException(400, f"unknown side '{req.side}'")
    params = _params(req.params)
    # Cache by (side, region, compute params): switching views / re-selecting the
    # same region / toggling a display-only knob then back must NOT re-run the
    # (slow) segmentation + local-thickness. Display-only params don't change the
    # geometry, so keying on the full param dict is safe (it just caches more keys).
    key = hashlib.sha256(
        f"{req.side}|{req.region_label}|{req.whole_bone}|{json.dumps(req.params, sort_keys=True)}".encode()
    ).hexdigest()[:16]
    cache = s.setdefault("analyze_cache", OrderedDict())
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        _stash_ar_mesh(s, hit["mesh"], "thickness_mm", hit["clim"], params.mode_a_colormap)
        return hit["response"]
    try:
        with R.COMPUTE_SEMAPHORE:  # bound concurrent heavy computes (peak RAM)
            res = pipeline.analyze_thickness(side["arr"], side["spacing"], params,
                                             region_label=req.region_label,
                                             offset_xyz=side["offset_xyz"],
                                             whole_bone=req.whole_bone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    clim = (params.mode_a_range_min, params.mode_a_range_max)
    _stash_ar_mesh(s, res["mesh"], "thickness_mm", clim, params.mode_a_colormap)
    response = {
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
    cache[key] = {"response": response, "mesh": res["mesh"], "clim": clim}
    while len(cache) > 6:            # bound RAM: a handful of recent results per session
        cache.popitem(last=False)
    return response


@router.get("/session/{sid}/region-thumbnails")
def region_thumbnails(sid: str, side: str) -> dict:
    """Small per-bone-region renders for the region dropdown (visual selection)."""
    s = _get_session(sid)
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
_OBLIQUE_LRU: "OrderedDict[tuple, dict]" = OrderedDict()
_OBLIQUE_LRU_MAX = 64


def _volume_side(sid: str, side: str):
    s = _get_session(sid)
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


# --------------------------------------------------------------------------- #
# Oblique / arbitrary cross-section (Phase VII): sample the volume on ANY plane
# (origin + normal), so the 3D cut widget and the 2D reformat are matched at every
# pixel. Returns the image AND the plane basis so the caller can map pixel<->world.
# Light work, LRU-cached; outside COMPUTE_SEMAPHORE.
# --------------------------------------------------------------------------- #
class ObliqueReq(BaseModel):
    side: str | None = None
    origin_xyz_mm: list[float]
    normal: list[float]
    up: list[float] | None = None
    size_mm: float = 220.0
    px_mm: float = 1.0
    max_dim: int = 512
    window: float = mpr.BONE_WINDOW
    level: float = mpr.BONE_LEVEL


@router.post("/session/{sid}/oblique-slice")
def oblique_slice(sid: str, req: ObliqueReq) -> dict:
    sd = _volume_side(sid, req.side or "")
    if len(req.origin_xyz_mm) != 3 or len(req.normal) != 3:
        raise HTTPException(422, "origin_xyz_mm and normal must be length-3")
    max_dim = int(max(32, min(1024, req.max_dim)))
    px_mm = float(min(max(req.px_mm, 0.1), 10.0))
    size_mm = float(min(max(req.size_mm, 10.0), 1000.0))
    key = (sid, sd["side"], tuple(round(x, 2) for x in req.origin_xyz_mm),
           tuple(round(x, 4) for x in req.normal),
           tuple(round(x, 4) for x in req.up) if req.up else None,
           size_mm, px_mm, max_dim, float(req.window), float(req.level))
    cached = _OBLIQUE_LRU.get(key)
    if cached is None:
        try:
            png, meta = mpr.render_oblique_png(
                sd["arr"], sd["spacing"], sd["offset_xyz"], req.origin_xyz_mm,
                req.normal, up=req.up, size_mm=size_mm, px_mm=px_mm, max_dim=max_dim,
                window=req.window, level=req.level)
        except ValueError as e:
            raise HTTPException(422, str(e))
        import base64
        cached = {"image_png_base64": base64.b64encode(png).decode("ascii"), "meta": meta}
        _OBLIQUE_LRU[key] = cached
        while len(_OBLIQUE_LRU) > _OBLIQUE_LRU_MAX:
            _OBLIQUE_LRU.popitem(last=False)
    _OBLIQUE_LRU.move_to_end(key)
    return cached


# --------------------------------------------------------------------------- #
# AR asset — binary glTF of the most-recently-computed surface (Phase V). A
# phone's <model-viewer> GETs this URL directly (Scene Viewer / Quick Look). The
# colour field is baked to per-vertex RGB so the map survives the format.
# --------------------------------------------------------------------------- #
@router.get("/session/{sid}/model.glb")
def model_glb(sid: str) -> Response:
    s = _get_session(sid)
    ar = s.get("ar")
    if not ar:
        raise HTTPException(409, "no computed surface yet — run /analyze or /compare first")
    glb = s.get("ar_glb")
    if glb is None:
        from core.export.mesh import export_mesh  # local: pulls trimesh only on demand
        out = CACHE / f"{sid}_model.glb"
        with R.COMPUTE_SEMAPHORE:  # decimate + write can be non-trivial on a big mesh
            export_mesh(ar["mesh"], out, fmt="glb", scalar_name=ar["scalar"],
                        cmap_name=ar["cmap"], clim=ar["clim"])
        glb = out.read_bytes()
        s["ar_glb"] = glb
    return Response(content=glb, media_type="model/gltf-binary",
                    headers={"Content-Disposition": 'inline; filename="bone.glb"',
                             "Cache-Control": "private, max-age=300"})


# --------------------------------------------------------------------------- #
# Linked cross-sections (Phase IV): register two sides once, cache the world-map,
# then map a crosshair on the reference volume to the matching slice on the target.
# The linkage is *gated* on registration quality — a low inlier fraction (e.g. a
# thorax-fused bone) is reported as unreliable rather than silently trusted.
# --------------------------------------------------------------------------- #
_MIN_RELIABLE_INLIER = 0.30


class CompareSliceReq(BaseModel):
    reference_side: str = "left"
    target_side: str = "right"
    world_xyz_mm: list[float]
    params: dict = {}
    manual_transform: list[list[float]] | None = None


def _compare_map(s: dict, reference_side: str, target_side: str,
                 params_dict: dict, manual_transform):
    """Return (ref, tgt, reg) with the registration world-map for the side pair,
    computed once and cached per (sides, params, manual) — reused by both the
    linked-slice and the oblique-compare endpoints."""
    ref = s["sides"].get(reference_side)
    tgt = s["sides"].get(target_side)
    if not ref or not tgt:
        raise HTTPException(400, "unknown side(s)")
    if ref.get("arr") is None or tgt.get("arr") is None:
        raise HTTPException(400, "both sides must be volumes (not bare meshes)")
    ckey = hashlib.sha256(
        f"{reference_side}|{target_side}|{json.dumps(params_dict, sort_keys=True)}"
        f"|{manual_transform}".encode()
    ).hexdigest()[:16]
    cache = s.setdefault("compare_maps", OrderedDict())
    reg = cache.get(ckey)
    if reg is None:
        params = _params(params_dict)
        with R.COMPUTE_SEMAPHORE:
            reg = pipeline.compare_registration(ref, tgt, params,
                                                manual_transform=manual_transform)
        cache[ckey] = reg
        while len(cache) > 4:            # a handful of param sets per session
            cache.popitem(last=False)
    return ref, tgt, reg


def _reg_gate(reg: dict) -> dict:
    """Uniform reliability gate + note for the compare endpoints."""
    reliable = reg["inlier_fraction"] >= _MIN_RELIABLE_INLIER
    return {
        "rms_mm": round(reg["rms"], 3),
        "inlier_fraction": round(reg["inlier_fraction"], 3),
        "reliable": bool(reliable),
        "note": ("registration is well-constrained" if reliable else
                 "low overlap — the matched target reformat is unreliable "
                 "(isolate the bone / adjust registration first)"),
    }


def _side_slices(sd: dict, world_xyz) -> dict:
    ijk = mpr.world_to_voxel(world_xyz, sd["spacing"], sd["offset_xyz"])
    nz, ny, nx = sd["arr"].shape
    in_bounds = 0 <= ijk[0] < nx and 0 <= ijk[1] < ny and 0 <= ijk[2] < nz
    return {"world_xyz_mm": [round(float(w), 3) for w in world_xyz],
            "voxel_ijk": list(ijk), "in_bounds": bool(in_bounds),
            "slices": mpr.slices_from_voxel(ijk, sd["arr"].shape)}


@router.post("/session/{sid}/compare-slice-map")
def compare_slice_map(sid: str, req: CompareSliceReq) -> dict:
    s = _get_session(sid)
    ref, tgt, reg = _compare_map(s, req.reference_side, req.target_side,
                                 req.params, req.manual_transform)
    tgt_world = pipeline.apply_affine(reg["ref_world_to_tgt_world"], req.world_xyz_mm)
    return {
        "reference": _side_slices(ref, req.world_xyz_mm),
        "target": _side_slices(tgt, tgt_world),
        "registration": _reg_gate(reg),
    }


# --------------------------------------------------------------------------- #
# Oblique compare (the two-bone matched cross-section): ONE movable oblique plane
# on the reference bone, mapped through the cached registration onto the target
# bone, so both bones' 2D reformats are shown side by side ("2 boxes") for the
# same anatomical cut. Same reliability gate as the linked-slice endpoint.
# --------------------------------------------------------------------------- #
class ObliqueCompareReq(BaseModel):
    reference_side: str = "left"
    target_side: str = "right"
    origin_xyz_mm: list[float]
    normal: list[float]
    up: list[float] | None = None
    size_mm: float = 220.0
    px_mm: float = 1.0
    max_dim: int = 512
    window: float = mpr.BONE_WINDOW
    level: float = mpr.BONE_LEVEL
    params: dict = {}
    manual_transform: list[list[float]] | None = None


def _oblique_of(sd: dict, origin, normal, req: "ObliqueCompareReq") -> dict:
    import base64
    png, meta = mpr.render_oblique_png(
        sd["arr"], sd["spacing"], sd["offset_xyz"], origin, normal, up=req.up,
        size_mm=float(min(max(req.size_mm, 10.0), 1000.0)),
        px_mm=float(min(max(req.px_mm, 0.1), 10.0)),
        max_dim=int(max(32, min(1024, req.max_dim))),
        window=req.window, level=req.level)
    return {"image_png_base64": base64.b64encode(png).decode("ascii"), "meta": meta}


@router.post("/session/{sid}/oblique-compare")
def oblique_compare(sid: str, req: ObliqueCompareReq) -> dict:
    s = _get_session(sid)
    if len(req.origin_xyz_mm) != 3 or len(req.normal) != 3:
        raise HTTPException(422, "origin_xyz_mm and normal must be length-3")
    ref, tgt, reg = _compare_map(s, req.reference_side, req.target_side,
                                 req.params, req.manual_transform)
    # Same physical cut on both bones: map the reference plane through the rigid
    # registration onto the target (origin by the affine, normal by its rotation).
    tgt_origin, tgt_normal = pipeline.map_plane(
        reg["ref_world_to_tgt_world"], req.origin_xyz_mm, req.normal)
    try:
        return {
            "reference": _oblique_of(ref, req.origin_xyz_mm, req.normal, req),
            "target": _oblique_of(tgt, tgt_origin, tgt_normal, req),
            "registration": _reg_gate(reg),
        }
    except ValueError as e:
        raise HTTPException(422, str(e))


def _compare_cache_key(req: "CompareReq") -> str:
    return hashlib.sha256(
        f"cmp|{req.reference_side}|{req.target_side}|"
        f"{json.dumps(req.params, sort_keys=True)}|{req.manual_transform}".encode()
    ).hexdigest()[:16]


@router.post("/session/{sid}/compare")
def compare(sid: str, req: CompareReq) -> dict:
    s = _get_session(sid)
    ref = s["sides"].get(req.reference_side)
    tgt = s["sides"].get(req.target_side)
    if not ref or not tgt:
        raise HTTPException(400, "unknown side(s)")
    params = _params(req.params)
    # Cache by (sides, compare params, manual nudge) — mirrors /analyze's
    # analyze_cache so switching back to an already-computed comparison (or the
    # figures endpoint below) never re-runs registration + signed-distance.
    key = _compare_cache_key(req)
    cache = s.setdefault("compare_cache", OrderedDict())
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        _stash_ar_mesh(s, hit["mesh"], hit["scalar"], hit["clim"], params.mode_b_colormap)
        return hit["response"]
    try:
        with R.COMPUTE_SEMAPHORE:  # bound concurrent heavy computes (peak RAM)
            res = pipeline.compare_sides(ref, tgt, params,
                                         manual_transform=req.manual_transform)
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"comparison failed: {e}") from e
    clim = (params.mode_b_center - params.mode_b_range_abs,
            params.mode_b_center + params.mode_b_range_abs)
    _stash_ar_mesh(s, res["mesh"], res["scalar"], clim, params.mode_b_colormap)
    response = {
        "geometry_url": _save_mesh(res["mesh"], key),
        "scalar": res["scalar"],
        "scalar_range": [clim[0], clim[1]],
        "colormap": params.mode_b_colormap,
        "steps": params.mode_b_colorbar_steps,
        "stats": res["stats"],
        "registration": res["registration"],
        "hover_scalars": res.get("hover_scalars", [res["scalar"]]),
    }
    cache[key] = {"response": response, "mesh": res["mesh"], "scalar": res["scalar"], "clim": clim}
    while len(cache) > 6:            # bound RAM: a handful of recent results per session
        cache.popitem(last=False)
    return response


# --------------------------------------------------------------------------- #
# Statistics figures (publication-style PNG/TIFF/JPG of the active scalar field
# + per-region summary) — reuses the SAME analyze/compare cache the interactive
# viewer already populates, so it never re-runs the heavy pipeline just to draw
# a histogram. Light work (matplotlib only); outside COMPUTE_SEMAPHORE on a
# cache hit, and only takes the semaphore on a genuine cache miss (identical to
# /analyze and /compare's own behaviour).
# --------------------------------------------------------------------------- #
def _result_for_figures(s: dict, req: "FiguresReq", params) -> tuple[object, str, list[dict] | None]:
    """Return (mesh, scalar_name, regions) for the requested mode, reusing the
    analyze_cache (Mode A) / compare_cache (Mode B) populated by /analyze and
    /compare — computing (under COMPUTE_SEMAPHORE) only on a cache miss."""
    if req.mode.upper() == "B":
        ref_name = req.reference_side or "left"
        tgt_name = req.target_side or "right"
        ref = s["sides"].get(ref_name)
        tgt = s["sides"].get(tgt_name)
        if not ref or not tgt:
            raise HTTPException(400, "unknown side(s) for Mode B figures")
        creq = CompareReq(reference_side=ref_name, target_side=tgt_name,
                          params=req.params, manual_transform=req.manual_transform)
        key = _compare_cache_key(creq)
        cache = s.setdefault("compare_cache", OrderedDict())
        hit = cache.get(key)
        if hit is not None:
            cache.move_to_end(key)
            mesh = hit["mesh"]
        else:
            try:
                with R.COMPUTE_SEMAPHORE:
                    res = pipeline.compare_sides(ref, tgt, params,
                                                 manual_transform=req.manual_transform)
            except NotImplementedError as e:
                raise HTTPException(501, str(e)) from e
            except Exception as e:  # noqa: BLE001
                raise HTTPException(422, f"comparison failed: {e}") from e
            clim = (params.mode_b_center - params.mode_b_range_abs,
                    params.mode_b_center + params.mode_b_range_abs)
            _stash_ar_mesh(s, res["mesh"], res["scalar"], clim, params.mode_b_colormap)
            response = {
                "geometry_url": _save_mesh(res["mesh"], key),
                "scalar": res["scalar"],
                "scalar_range": [clim[0], clim[1]],
                "colormap": params.mode_b_colormap,
                "steps": params.mode_b_colorbar_steps,
                "stats": res["stats"],
                "registration": res["registration"],
                "hover_scalars": res.get("hover_scalars", [res["scalar"]]),
            }
            cache[key] = {"response": response, "mesh": res["mesh"],
                         "scalar": res["scalar"], "clim": clim}
            while len(cache) > 6:
                cache.popitem(last=False)
            mesh = res["mesh"]
        return mesh, "deviation_mm", None  # Mode B has no per-region breakdown (single reg. surface)

    # Mode A (default): thickness on a single side, reusing analyze_cache.
    side_name = req.side or next(iter(s["sides"]))
    side = s["sides"].get(side_name)
    if not side:
        raise HTTPException(400, f"unknown side '{side_name}'")
    key = hashlib.sha256(
        f"{side_name}|{req.region_label}|{json.dumps(req.params, sort_keys=True)}".encode()
    ).hexdigest()[:16]
    cache = s.setdefault("analyze_cache", OrderedDict())
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        return hit["mesh"], "thickness_mm", hit["response"]["regions"]

    if side.get("arr") is None:
        raise HTTPException(400, "Mode A figures need a volume side, not a bare mesh")
    try:
        with R.COMPUTE_SEMAPHORE:
            res = pipeline.analyze_thickness(side["arr"], side["spacing"], params,
                                             region_label=req.region_label,
                                             offset_xyz=side["offset_xyz"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    clim = (params.mode_a_range_min, params.mode_a_range_max)
    _stash_ar_mesh(s, res["mesh"], "thickness_mm", clim, params.mode_a_colormap)
    response = {
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
    cache[key] = {"response": response, "mesh": res["mesh"], "clim": clim}
    while len(cache) > 6:
        cache.popitem(last=False)
    return res["mesh"], "thickness_mm", res["regions"]


@router.post("/session/{sid}/figures")
def figures(sid: str, req: FiguresReq) -> dict:
    """Render publication-style statistics figures for the (cached) computed result.

    Body: ``{mode: 'A'|'B', side|reference_side/target_side, region_label, params,
    which?: ['histogram','by_region']}``. Reuses the /analyze or /compare cache
    (see ``_result_for_figures``) so this never re-runs segmentation/thickness/
    registration just to draw a figure.

    Returns ``{"figures": {name: base64 PNG}, "note": str}``. ``note`` states the
    single-subject / descriptive scope, and — when ``by_region`` was requested
    but omitted (fewer than 2 regions, or Mode B) — explains why.
    """
    import base64

    s = _get_session(sid)
    if req.mode.upper() not in ("A", "B"):
        raise HTTPException(422, "mode must be 'A' or 'B'")
    params = _params(req.params)
    mesh, scalar_name, regions = _result_for_figures(s, req, params)

    values = np.asarray(mesh.point_data.get(scalar_name), dtype=np.float64) \
        if mesh is not None and scalar_name in getattr(mesh, "point_data", {}) else None
    if values is None or values.size == 0:
        raise HTTPException(422, f"no '{scalar_name}' scalar on the computed surface")

    which = req.which if req.which else list(_FIGURE_NAMES)
    unknown = [w for w in which if w not in _FIGURE_NAMES]
    if unknown:
        raise HTTPException(422, f"unknown figure name(s) {unknown}; expected {_FIGURE_NAMES}")

    raw = render_result_figures(scalar_values=values, scalar_name=scalar_name,
                                regions=regions, which=which, fmt="png", dpi=300)
    encoded = {name: base64.b64encode(png).decode("ascii") for name, png in raw.items()}

    note = ("Single-subject descriptive statistics — distribution and per-region "
            "summaries for this scan only; not a group comparison and not for "
            "diagnostic use.")
    if "by_region" in which and "by_region" not in raw:
        reason = ("Mode B has one registered surface (no per-region breakdown)."
                  if req.mode.upper() == "B" else
                  "fewer than 2 bone regions were segmented — nothing to compare.")
        note += f" 'by_region' omitted: {reason}"

    # Descriptive stat block (percentiles / IQR / %>1mm / %>2mm) — the same
    # numbers the Table-1 figure renders, exposed for programmatic use.
    stats_block = descriptive_stats(values, scalar_name=scalar_name)
    if regions and len(regions) > 1:
        stats_block["per_region"] = [
            {"label": r["label"], "volume_cm3": r["volume_cm3"],
             "boneness": r.get("boneness")} for r in regions]

    return {"figures": encoded, "stats": stats_block, "note": note}


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
    s = _get_session(sid)
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
                              stem="export", annotate=req.annotate)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    urls = {fmt: f"/api/exports/{key}/{Path(p).name}" for fmt, p in files.items()}
    return {"files": urls, "mode": req.mode.upper(), "scalar": scalar}


_FIGURE_RASTER_FORMATS = ("png", "tiff", "jpg")


@router.post("/session/{sid}/export-figures")
def export_figures(sid: str, req: ExportFiguresReq) -> dict:
    """Render the statistics figures to DOWNLOADABLE files at a chosen dpi/format.

    Body: same as ``/figures`` plus ``{formats: ["png","tiff",...], dpi}``.
    Writes ``histogram.<fmt>`` / ``by_region.<fmt>`` under ``/api/exports/<key>/``
    (mirroring the geometry export's directory-per-request convention) and
    returns ``{"files": {"histogram": url, "by_region": url, ...}, "note": str}``.
    Each requested figure is written in EVERY requested format (so 2 figures x 2
    formats = 4 files), named ``<figure>.<fmt>``; when >1 format is requested the
    keys become ``<figure>_<fmt>``.
    """
    import base64

    s = _get_session(sid)
    if req.mode.upper() not in ("A", "B"):
        raise HTTPException(422, "mode must be 'A' or 'B'")
    if not req.formats:
        raise HTTPException(422, "at least one export format is required")
    fmts = [f.lower() for f in req.formats]
    bad = [f for f in fmts if f not in _FIGURE_RASTER_FORMATS]
    if bad:
        raise HTTPException(422, f"unsupported figure format(s) {bad}; expected {_FIGURE_RASTER_FORMATS}")
    if req.dpi <= 0:
        raise HTTPException(422, "dpi must be positive")

    params = _params(req.params)
    mesh, scalar_name, regions = _result_for_figures(s, req, params)
    values = np.asarray(mesh.point_data.get(scalar_name), dtype=np.float64) \
        if mesh is not None and scalar_name in getattr(mesh, "point_data", {}) else None
    if values is None or values.size == 0:
        raise HTTPException(422, f"no '{scalar_name}' scalar on the computed surface")

    which = req.which if req.which else list(_FIGURE_NAMES)
    unknown = [w for w in which if w not in _FIGURE_NAMES]
    if unknown:
        raise HTTPException(422, f"unknown figure name(s) {unknown}; expected {_FIGURE_NAMES}")

    key = hashlib.sha256(
        f"{sid}|figexp|{req.mode}|{json.dumps(req.model_dump(), sort_keys=True, default=str)}".encode()
    ).hexdigest()[:16]
    out_dir = EXPORTS / key
    out_dir.mkdir(parents=True, exist_ok=True)

    urls: dict[str, str] = {}
    produced: set[str] = set()
    for fmt in fmts:
        raw = render_result_figures(scalar_values=values, scalar_name=scalar_name,
                                    regions=regions, which=which, fmt=fmt, dpi=req.dpi)
        produced |= set(raw)
        for name, data in raw.items():
            out_name = f"{name}.{fmt}" if len(fmts) == 1 else f"{name}_{fmt}.{fmt}"
            (out_dir / out_name).write_bytes(data)
            out_key = name if len(fmts) == 1 else f"{name}_{fmt}"
            urls[out_key] = f"/api/exports/{key}/{out_name}"

    note = ("Single-subject descriptive statistics — distribution and per-region "
            "summaries for this scan only; not a group comparison and not for "
            "diagnostic use.")
    if "by_region" in which and "by_region" not in produced:
        reason = ("Mode B has one registered surface (no per-region breakdown)."
                  if req.mode.upper() == "B" else
                  "fewer than 2 bone regions were segmented — nothing to compare.")
        note += f" 'by_region' omitted: {reason}"

    stats_block = descriptive_stats(values, scalar_name=scalar_name)
    if regions and len(regions) > 1:
        stats_block["per_region"] = [
            {"label": r["label"], "volume_cm3": r["volume_cm3"],
             "boneness": r.get("boneness")} for r in regions]

    return {"files": urls, "mode": req.mode.upper(), "scalar": scalar_name,
            "stats": stats_block, "note": note}
