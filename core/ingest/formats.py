"""Non-DICOM input formats: NIfTI volumes and surface meshes.

Keeps the DICOM/zip path (``dicom_ingest``) untouched while adding two ways to
get data into the pipeline:

* :func:`load_nifti_volume` — a ``.nii`` / ``.nii.gz`` CT read via SimpleITK into
  the same ``(arr[z, y, x] float32 HU, spacing (sx, sy, sz) mm, meta)`` contract
  the DICOM loader returns, so every downstream analysis works unchanged.
* :func:`load_mesh_source` — a surface mesh (``.stl`` / ``.ply`` / ``.obj`` /
  ``.vtp``) read into a ``pyvista.PolyData`` for Mode-B mesh-vs-mesh comparison
  and viewing.

De-identification note: NIfTI carries no patient identifiers, and mesh files
carry only geometry, so nothing here can leak PHI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
import SimpleITK as sitk

# File extensions accepted anywhere a scan/surface can be uploaded.
NIFTI_EXTENSIONS = (".nii", ".nii.gz")
MESH_EXTENSIONS = (".stl", ".ply", ".obj", ".vtp")


def _lower_suffix(path) -> str:
    """Return the meaningful lowercase extension, handling ``.nii.gz``."""
    name = Path(path).name.lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    return Path(name).suffix


def is_nifti(path) -> bool:
    return _lower_suffix(path) in NIFTI_EXTENSIONS


def is_mesh(path) -> bool:
    return _lower_suffix(path) in MESH_EXTENSIONS


def load_nifti_volume(path) -> tuple[np.ndarray, tuple, dict]:
    """Load a NIfTI CT into ``(arr[z, y, x] float32 HU, spacing (sx, sy, sz), meta)``.

    ``SimpleITK.ReadImage`` returns an image whose array axis order is
    ``(z, y, x)`` and whose ``GetSpacing()`` is ``(sx, sy, sz)`` — the exact
    convention the DICOM loader (:func:`core.pipeline.load_volume_from_source`)
    already uses, so the two paths are interchangeable downstream.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NIfTI file not found: {path}")
    img = sitk.ReadImage(str(path))
    arr = sitk.GetArrayFromImage(img).astype(np.float32)  # (z, y, x)
    spacing = tuple(float(s) for s in img.GetSpacing())    # (sx, sy, sz)
    meta = {
        "format": "nifti",
        "shape": list(arr.shape),
        "spacing_mm": [round(s, 3) for s in spacing],
        "hu_min": float(np.min(arr)) if arr.size else None,
        "hu_max": float(np.max(arr)) if arr.size else None,
    }
    return arr, spacing, meta


def load_mesh_source(path) -> pv.PolyData:
    """Load a surface mesh (``.stl`` / ``.ply`` / ``.obj`` / ``.vtp``) as PolyData.

    This is a **surface** input, used for Mode-B mesh-vs-mesh comparison and for
    viewing. Cortical thickness needs a *volume* (a filled bone with an inner and
    outer wall); a bare surface has no wall to measure, so thickness analysis
    (Mode A) requires a DICOM/NIfTI volume, not a mesh loaded here.

    The returned mesh is triangulated and carries point normals so it can feed
    registration directly.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"mesh file not found: {path}")
    if not is_mesh(path):
        raise ValueError(
            f"unsupported mesh extension {_lower_suffix(path)!r}; "
            f"expected one of {MESH_EXTENSIONS}"
        )
    mesh = pv.read(str(path))
    if not isinstance(mesh, pv.PolyData):
        mesh = mesh.extract_surface()
    mesh = mesh.triangulate().clean()
    if mesh.n_points and "Normals" not in mesh.point_data:
        mesh.compute_normals(inplace=True, auto_orient_normals=True)
    return mesh
