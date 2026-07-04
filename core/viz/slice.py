"""Shared MPR slice logic — the single source of truth for both frontends.

The FastAPI ``/slice`` endpoint and the trame UI both call these functions, so a
slice at ``(plane, index, window, level)`` is byte-identical across the two UIs.

The volume is ``arr[z, y, x]`` int16 HU with ``spacing = (sx, sy, sz)`` mm. The
app world frame is ``world = idx * spacing + offset`` (identity direction — the
DICOM origin/direction were discarded upstream), so planes are *array-oriented*
(labeled as such; we never assert radiological A/P/S/I). Plane ↔ axis:

    axial    : fix z -> arr[k]        image (rows=y, cols=x)  spacings (row=sy, col=sx)
    coronal  : fix y -> arr[:, k, :]  image (rows=z, cols=x)  spacings (row=sz, col=sx)
    sagittal : fix x -> arr[:, :, k]  image (rows=z, cols=y)  spacings (row=sz, col=sy)
"""

from __future__ import annotations

import io

import numpy as np
from scipy import ndimage

BONE_WINDOW = 1800.0
BONE_LEVEL = 400.0

# plane -> (fixed axis in arr, row spacing selector, col spacing selector)
# spacing is (sx, sy, sz) = index 0,1,2
_PLANE = {
    "axial": {"axis": 0, "row_sp": 1, "col_sp": 0},     # rows=y(sy), cols=x(sx)
    "coronal": {"axis": 1, "row_sp": 2, "col_sp": 0},   # rows=z(sz), cols=x(sx)
    "sagittal": {"axis": 2, "row_sp": 2, "col_sp": 1},  # rows=z(sz), cols=y(sy)
}
PLANES = tuple(_PLANE)


def n_slices(shape_zyx, plane: str) -> int:
    return int(shape_zyx[_PLANE[plane]["axis"]])


def clamp_index(shape_zyx, plane: str, index: int) -> int:
    return int(max(0, min(int(index), n_slices(shape_zyx, plane) - 1)))


def extract_slice(arr: np.ndarray, plane: str, index: int) -> np.ndarray:
    """2D HU slice (a view where possible); ``index`` is clamped into range."""
    if plane not in _PLANE:
        raise ValueError(f"unknown plane {plane!r}")
    k = clamp_index(arr.shape, plane, index)
    axis = _PLANE[plane]["axis"]
    return np.take(arr, k, axis=axis)


def window_to_uint8(sl: np.ndarray, window: float, level: float) -> np.ndarray:
    """Map HU to 0..255 via window/level (width/center)."""
    window = float(window) if window else 1.0
    lo = float(level) - window / 2.0
    out = (sl.astype(np.float32) - lo) / window
    return (np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)


def aspect_resample(img: np.ndarray, row_sp: float, col_sp: float,
                    max_dim: int = 512) -> np.ndarray:
    """Resample a 2D image to physically-square pixels, long edge ≤ ``max_dim``."""
    nrows, ncols = img.shape[:2]
    h_mm, w_mm = nrows * row_sp, ncols * col_sp
    if h_mm <= 0 or w_mm <= 0:
        return img
    px = max(h_mm, w_mm) / float(max_dim)          # target mm/pixel to hit max_dim
    px = max(px, min(row_sp, col_sp))              # don't upsample past native
    out_rows = max(1, int(round(h_mm / px)))
    out_cols = max(1, int(round(w_mm / px)))
    if (out_rows, out_cols) == (nrows, ncols):
        return img
    zoom = (out_rows / nrows, out_cols / ncols)
    if img.ndim == 3:  # RGB
        zoom = zoom + (1,)
    return ndimage.zoom(img, zoom, order=1)


def encode_png(img: np.ndarray) -> bytes:
    """PNG bytes for a 2D (grayscale) or 3-channel (RGB) uint8 array."""
    from PIL import Image

    mode = "L" if img.ndim == 2 else "RGB"
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(img), mode=mode).save(buf, format="PNG")
    return buf.getvalue()


def render_slice_png(arr: np.ndarray, spacing, plane: str, index: int,
                     window: float = BONE_WINDOW, level: float = BONE_LEVEL,
                     max_dim: int = 512, overlay_mask: np.ndarray | None = None) -> bytes:
    """Full slice pipeline: extract → window → (optional bone overlay) → aspect → PNG."""
    sl = extract_slice(arr, plane, index)
    gray = window_to_uint8(sl, window, level)
    p = _PLANE[plane]
    row_sp, col_sp = float(spacing[p["row_sp"]]), float(spacing[p["col_sp"]])
    if overlay_mask is not None:
        m = np.take(overlay_mask, clamp_index(arr.shape, plane, index), axis=p["axis"])
        rgb = np.stack([gray, gray, gray], axis=-1)
        rgb[m.astype(bool), 0] = np.maximum(rgb[m.astype(bool), 0], 200)  # tint red
        img = aspect_resample(rgb, row_sp, col_sp, max_dim)
    else:
        img = aspect_resample(gray, row_sp, col_sp, max_dim)
    return encode_png(img)


# --------------------------------------------------------------------------- #
# world <-> voxel (the app frame: world = idx*spacing + offset, identity dir)
# --------------------------------------------------------------------------- #
def world_to_voxel(world_xyz, spacing, offset=(0.0, 0.0, 0.0)) -> tuple[int, int, int]:
    ix = int(round((world_xyz[0] - offset[0]) / spacing[0]))
    iy = int(round((world_xyz[1] - offset[1]) / spacing[1]))
    iz = int(round((world_xyz[2] - offset[2]) / spacing[2]))
    return ix, iy, iz


def voxel_to_world(ijk, spacing, offset=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    return (ijk[0] * spacing[0] + offset[0],
            ijk[1] * spacing[1] + offset[1],
            ijk[2] * spacing[2] + offset[2])


def slices_from_voxel(ijk, shape_zyx) -> dict:
    """Voxel (ix,iy,iz) -> clamped slice index per plane."""
    ix, iy, iz = ijk
    return {
        "axial": clamp_index(shape_zyx, "axial", iz),
        "coronal": clamp_index(shape_zyx, "coronal", iy),
        "sagittal": clamp_index(shape_zyx, "sagittal", ix),
    }


# --------------------------------------------------------------------------- #
# Oblique / arbitrary-plane reformat — "any shape of cross-section". A plane is a
# world-space point (origin) + a unit normal; we sample the volume on a square
# grid in that plane so the 3D cut and the 2D reformat are matched at *every*
# pixel: pixel (r, c) <-> world = origin + (c-cx)*px*u + (r-cy)*px*v. The three
# orthogonal planes are just the axis-aligned special case; this handles any tilt.
# --------------------------------------------------------------------------- #
def plane_basis(normal, up=None):
    """Right-handed orthonormal (n, u, v): ``u`` is the image column axis, ``v`` the
    row axis, both in the plane ⟂ ``n``. Deterministic, so 3D and 2D agree."""
    n = np.asarray(normal, dtype=np.float64)
    ln = np.linalg.norm(n)
    if ln < 1e-9:
        raise ValueError("normal must be non-zero")
    n = n / ln
    if up is None:
        up = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    up = np.asarray(up, dtype=np.float64)
    u = up - np.dot(up, n) * n
    if np.linalg.norm(u) < 1e-6:                    # up ∥ n: pick any in-plane axis
        alt = np.array([1.0, 0.0, 0.0])
        u = alt - np.dot(alt, n) * n
    u = u / np.linalg.norm(u)
    v = np.cross(n, u)
    v = v / np.linalg.norm(v)
    return n, u, v


def oblique_grid_world(origin, normal, up=None, size_mm=200.0, px_mm=1.0,
                       max_dim: int = 512):
    """(world_points[H,W,3], meta) for a square plane grid centred at ``origin``."""
    n, u, v = plane_basis(normal, up)
    npx = int(max(2, min(int(max_dim), round(float(size_mm) / float(px_mm)))))
    off = (np.arange(npx) - (npx - 1) / 2.0) * float(px_mm)
    cc, rr = np.meshgrid(off, off)                  # cc→columns(u), rr→rows(v)
    origin = np.asarray(origin, dtype=np.float64)
    world = origin[None, None, :] + cc[..., None] * u + rr[..., None] * v
    meta = {"origin_xyz_mm": [float(x) for x in origin],
            "normal": [float(x) for x in n], "u": [float(x) for x in u],
            "v": [float(x) for x in v], "px_mm": float(px_mm), "size_px": npx,
            "size_mm": float(px_mm) * npx}
    return world, meta


def oblique_slice(arr: np.ndarray, spacing, offset, origin, normal, *, up=None,
                  size_mm=200.0, px_mm=1.0, max_dim: int = 512,
                  window: float = BONE_WINDOW, level: float = BONE_LEVEL,
                  overlay_mask: np.ndarray | None = None):
    """Sample ``arr`` on an arbitrary plane → (uint8 image, meta). Trilinear; out-of
    -volume samples read as air (arr.min()). Grayscale, or RGB if an overlay mask
    is given (bone tint). ``meta`` carries the basis so callers can map pixel↔world."""
    sx, sy, sz = (float(s) for s in spacing)
    ox, oy, oz = (float(o) for o in offset)
    world, meta = oblique_grid_world(origin, normal, up, size_mm, px_mm, max_dim)
    wx, wy, wz = world[..., 0], world[..., 1], world[..., 2]
    # world = idx*spacing + offset  (world x↔ix↔arr axis2, y↔iy↔axis1, z↔iz↔axis0)
    ix = (wx - ox) / sx
    iy = (wy - oy) / sy
    iz = (wz - oz) / sz
    coords = np.stack([iz, iy, ix], axis=0)          # arr is [z, y, x]
    sampled = ndimage.map_coordinates(arr, coords, order=1, mode="constant",
                                      cval=float(arr.min()))
    gray = window_to_uint8(sampled, window, level)
    if overlay_mask is not None:
        m = ndimage.map_coordinates(overlay_mask.astype(np.float32), coords,
                                    order=0, mode="constant", cval=0.0) > 0.5
        rgb = np.stack([gray, gray, gray], axis=-1)
        rgb[m, 0] = np.maximum(rgb[m, 0], 200)
        return rgb, meta
    return gray, meta


def render_oblique_png(arr, spacing, offset, origin, normal, *, up=None,
                       size_mm=200.0, px_mm=1.0, max_dim: int = 512,
                       window: float = BONE_WINDOW, level: float = BONE_LEVEL,
                       overlay_mask=None):
    """Oblique reformat as (PNG bytes, meta)."""
    img, meta = oblique_slice(arr, spacing, offset, origin, normal, up=up,
                              size_mm=size_mm, px_mm=px_mm, max_dim=max_dim,
                              window=window, level=level, overlay_mask=overlay_mask)
    return encode_png(img), meta


def oblique_pixel_to_world(meta, row: float, col: float) -> tuple:
    """Pixel (row, col) on an oblique reformat → world (x, y, z) mm (exact inverse
    of the sampling grid, so a 2D click lands on the matching 3D point)."""
    o = np.asarray(meta["origin_xyz_mm"], dtype=np.float64)
    u = np.asarray(meta["u"], dtype=np.float64)
    v = np.asarray(meta["v"], dtype=np.float64)
    c0 = (meta["size_px"] - 1) / 2.0
    p = o + (float(col) - c0) * meta["px_mm"] * u + (float(row) - c0) * meta["px_mm"] * v
    return (float(p[0]), float(p[1]), float(p[2]))


def world_to_oblique_pixel(meta, world) -> tuple:
    """World (x, y, z) → (row, col) on the oblique reformat (project onto the plane
    basis). Fractional; caller rounds. The out-of-plane component is dropped."""
    o = np.asarray(meta["origin_xyz_mm"], dtype=np.float64)
    u = np.asarray(meta["u"], dtype=np.float64)
    v = np.asarray(meta["v"], dtype=np.float64)
    d = np.asarray(world, dtype=np.float64) - o
    c0 = (meta["size_px"] - 1) / 2.0
    col = float(np.dot(d, u)) / meta["px_mm"] + c0
    row = float(np.dot(d, v)) / meta["px_mm"] + c0
    return (row, col)


def volume_info(arr: np.ndarray, spacing, offset, side: str) -> dict:
    sx, sy, sz = (float(s) for s in spacing)
    ox, oy, oz = (float(o) for o in offset)
    nz, ny, nx = arr.shape
    lo, hi = int(arr.min()), int(arr.max())
    return {
        "side": side,
        "shape_zyx": [nz, ny, nx],
        "spacing_mm": [round(sx, 4), round(sy, 4), round(sz, 4)],
        "offset_xyz_mm": [round(ox, 3), round(oy, 3), round(oz, 3)],
        "origin_mm": [0.0, 0.0, 0.0],
        "extent_mm": {"x": [ox, ox + nx * sx], "y": [oy, oy + ny * sy],
                      "z": [oz, oz + nz * sz]},
        "hu_range": [lo, hi],
        "default_window": BONE_WINDOW, "default_level": BONE_LEVEL,
        "planes": list(PLANES),
        "n_slices": {p: n_slices(arr.shape, p) for p in PLANES},
        "orientation": "array",  # NOT radiological — see docs/IMAGING_DESIGN.md
    }
