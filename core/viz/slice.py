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
