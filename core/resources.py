"""Resource limits + optional GPU acceleration.

Heavy compute (segmentation, local-thickness, registration) can exhaust RAM if
volumes accumulate or many computes run at once. This module bounds it on ALL
deployed devices — small laptop or big server — and uses the GPU when present:

- **Bounded concurrency:** only ``COMPUTE_CONCURRENCY`` heavy computes run at a
  time (peak RAM stays ~1x, not Nx).
- **Adaptive resolution:** the local-thickness isotropic grid is capped, so a
  huge volume is measured coarser rather than blowing up memory.
- **Volume budget:** oversized uploaded volumes are block-downsampled.
- **GPU:** rendering already uses the GPU (VTK / vtk.js). For compute, if CuPy +
  a CUDA device are present, distance transforms run on the GPU; otherwise CPU.
  Everything degrades gracefully.

All limits are environment-tunable (``THREEDORTH_*``) so a device can be sized.
"""

from __future__ import annotations

import os
import threading

import numpy as np


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


MAX_SESSIONS = _env_int("THREEDORTH_MAX_SESSIONS", 6)
COMPUTE_CONCURRENCY = _env_int("THREEDORTH_COMPUTE_CONCURRENCY", 1)
MAX_WORK_VOXELS = _env_int("THREEDORTH_MAX_WORK_VOXELS", 60_000_000)
MAX_ISO_VOXELS = _env_int("THREEDORTH_MAX_ISO_VOXELS", 24_000_000)

# Serialize heavy compute so peak memory is bounded (default: one at a time).
COMPUTE_SEMAPHORE = threading.BoundedSemaphore(COMPUTE_CONCURRENCY)


def gpu_available() -> bool:
    """True if CuPy + a CUDA device are usable (opt out with THREEDORTH_GPU=0)."""
    if os.getenv("THREEDORTH_GPU", "auto") == "0":
        return False
    try:
        import cupy  # noqa: F401
        import cupy.cuda

        return cupy.cuda.runtime.getDeviceCount() > 0
    except Exception:  # noqa: BLE001
        return False


GPU = gpu_available()


def adaptive_iso(shape, spacing, min_iso: float = 0.6,
                 max_voxels: int = MAX_ISO_VOXELS) -> float:
    """Isotropic voxel size for local thickness that keeps the iso grid under
    ``max_voxels`` — finer for small bones, coarser for large volumes."""
    sz, sy, sx = spacing[2], spacing[1], spacing[0]
    nz, ny, nx = shape
    phys_vol = (nz * sz) * (ny * sy) * (nx * sx)
    iso_for_budget = (phys_vol / max_voxels) ** (1.0 / 3.0) if phys_vol > 0 else min_iso
    return float(max(min_iso, iso_for_budget))


def downsample_to_budget(arr: np.ndarray, spacing, max_voxels: int = MAX_WORK_VOXELS):
    """Block-downsample ``arr`` (and scale spacing) if it exceeds the voxel budget."""
    if arr.size <= max_voxels:
        return arr, spacing
    f = int(np.ceil((arr.size / max_voxels) ** (1.0 / 3.0)))
    if f <= 1:
        return arr, spacing
    out = np.ascontiguousarray(arr[::f, ::f, ::f])
    sp = (spacing[0] * f, spacing[1] * f, spacing[2] * f)
    return out, sp


def distance_transform_edt(mask, sampling=None):
    """EDT on the GPU (CuPy) when available, else SciPy on the CPU."""
    if GPU:
        try:
            import cupy as cp
            from cupyx.scipy import ndimage as cndi

            d = cndi.distance_transform_edt(cp.asarray(mask), sampling=sampling)
            return cp.asnumpy(d)
        except Exception:  # noqa: BLE001 — fall back to CPU
            pass
    from scipy import ndimage

    return ndimage.distance_transform_edt(mask, sampling=sampling)


def as_hu_int16(arr: np.ndarray) -> np.ndarray:
    """Store a CT volume compactly as int16 HU (halves session RAM vs float32)."""
    return np.clip(arr, -32768, 32767).astype(np.int16)


def summary() -> dict:
    return {
        "gpu": GPU,
        "max_sessions": MAX_SESSIONS,
        "compute_concurrency": COMPUTE_CONCURRENCY,
        "max_work_voxels": MAX_WORK_VOXELS,
        "max_iso_voxels": MAX_ISO_VOXELS,
    }
